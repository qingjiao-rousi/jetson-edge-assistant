#!/usr/bin/env python3
"""Read-only offline delivery contract verification for an EdgeOmni checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sqlite3
import struct
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_VCS = 3
UPSTREAM = "third_party/llama.cpp-omni"
RUNTIME_CONTRACT = "configs/contracts/runtime-contract.json"
RAG_CONTRACT = "configs/contracts/rag-r2.2-delivery-contract.json"


@dataclass(frozen=True)
class Check:
    id: str
    state: str
    path: str | None
    expected: Any
    observed: Any
    message: str

    def json_value(self) -> dict[str, Any]:
        return {"id": self.id, "state": self.state, "path": self.path, "expected": self.expected,
                "observed": self.observed, "message": self.message}


class UsageError(ValueError):
    pass


class VcsUnavailable(RuntimeError):
    pass


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Verifier:
    def __init__(self, root: pathlib.Path, config_name: str,
                 git_runner: Callable[[list[str]], str] | None = None):
        self.root = root.resolve()
        self.config_name = config_name
        self.git_runner = git_runner or self._run_git
        self.checks: list[Check] = []
        self.vcs_unavailable = False
        self.config_invalid = False

    def _run_git(self, args: list[str]) -> str:
        try:
            return subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as error:
            raise VcsUnavailable(str(error)) from error

    def add(self, identifier: str, ok: bool, path: str | None = None, expected: Any = None,
            observed: Any = None, message: str = "") -> None:
        self.checks.append(Check(identifier, "pass" if ok else "fail", path, expected, observed, message))

    def repo_path(self, value: str, identifier: str) -> pathlib.Path | None:
        if not isinstance(value, str) or not value:
            self.add(identifier, False, None, "repository-relative path", value, "path is missing")
            return None
        pure = pathlib.PurePosixPath(value)
        if "\\" in value or pure.is_absolute() or ".." in pure.parts or pure.as_posix() != value:
            self.add(identifier, False, value, "repository-relative path without '..'", value, "unsafe path")
            return None
        resolved = (self.root / pure).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError:
            self.add(identifier, False, value, "path inside repository root", str(resolved), "symbolic link escapes root")
            return None
        return resolved

    def load_json(self, value: str, identifier: str) -> tuple[pathlib.Path | None, dict[str, Any] | None]:
        path = self.repo_path(value, identifier + ".path")
        if path is None:
            return None, None
        if not path.is_file():
            self.add(identifier, False, value, "JSON file", None, "file is missing")
            return path, None
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            self.add(identifier, False, value, "valid JSON", None, f"cannot parse: {error}")
            if identifier == "assistant_config":
                self.config_invalid = True
            return path, None
        if not isinstance(parsed, dict):
            self.add(identifier, False, value, "JSON object", type(parsed).__name__, "top-level value is not an object")
            if identifier == "assistant_config":
                self.config_invalid = True
            return path, None
        self.add(identifier, True, value, "valid JSON object", "valid", "parsed")
        return path, parsed

    def regular_file(self, value: str, identifier: str) -> pathlib.Path | None:
        path = self.repo_path(value, identifier + ".path")
        if path is None:
            return None
        self.add(identifier, path.is_file(), value, "regular file", "regular file" if path.is_file() else None,
                 "present" if path.is_file() else "file is missing or not regular")
        return path if path.is_file() else None

    def asset(self, spec: dict[str, Any], identifier: str) -> None:
        if not isinstance(spec, dict) or not isinstance(spec.get("path"), str):
            self.add(identifier, False, None, "asset path/size_bytes/sha256", None, "invalid asset specification")
            return
        path = self.regular_file(spec["path"], identifier)
        expected_size, expected_hash = spec.get("size_bytes"), spec.get("sha256")
        if path is None:
            return
        size = path.stat().st_size
        self.add(identifier + ".size", isinstance(expected_size, int) and size == expected_size, spec["path"],
                 expected_size, size, "size matches" if size == expected_size else "size mismatch")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            self.add(identifier + ".sha256", False, spec["path"], "64-character SHA-256", expected_hash,
                     "invalid expected SHA-256")
            return
        actual = sha256_file(path)
        self.add(identifier + ".sha256", actual.lower() == expected_hash.lower(), spec["path"], expected_hash,
                 actual, "SHA-256 matches" if actual.lower() == expected_hash.lower() else "SHA-256 mismatch")

    def embedding_asset(self, spec: dict[str, Any]) -> None:
        if not isinstance(spec, dict):
            self.add("embedding_model", False, None, "embedding model object", None, "invalid embedding specification")
            return
        self.asset({
            "path": spec.get("model_path"),
            "size_bytes": spec.get("model_size_bytes"),
            "sha256": spec.get("model_sha256"),
        }, "embedding_model")

    def elf_aarch64(self, value: str, identifier: str) -> None:
        path = self.regular_file(value, identifier)
        if path is None:
            return
        try:
            with path.open("rb") as handle:
                header = handle.read(20)
            ok = len(header) >= 20 and header[:4] == b"\x7fELF" and header[4] == 2 and header[5] == 1 and struct.unpack("<H", header[18:20])[0] == 183
        except OSError:
            ok = False
        self.add(identifier + ".elf", ok, value, "ELF64 little-endian AArch64", "valid" if ok else "invalid",
                 "AArch64 ELF header" if ok else "not an AArch64 ELF binary")

    def contract(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None,
                                dict[str, Any] | None, dict[str, Any] | None]:
        for name in ("CMakeLists.txt", "runtime/CMakeLists.txt", f"{UPSTREAM}/include", f"{UPSTREAM}/ggml/include",
                     f"{UPSTREAM}/tools/mtmd", f"{UPSTREAM}/vendor/cpp-httplib"):
            path = self.repo_path(name, "contract.path")
            exists = path.is_dir() if path and name.endswith(("include", "mtmd", "cpp-httplib")) else bool(path and path.is_file())
            self.add("contract." + name.replace("/", "."), exists, name, "present", "present" if exists else None,
                     "present" if exists else "required source path is missing")
        _, config = self.load_json(self.config_name, "assistant_config")
        _, embedding = self.load_json("configs/embedding.json", "embedding_config")
        _, runtime_contract = self.load_json(RUNTIME_CONTRACT, "runtime_delivery_contract")
        _, rag_contract = self.load_json(RAG_CONTRACT, "rag_delivery_contract")
        if config is None:
            return None, embedding, runtime_contract, rag_contract
        runtime = config.get("runtime")
        modules = config.get("modules")
        valid = isinstance(runtime, dict) and isinstance(modules, dict) and isinstance(config.get("rag"), dict)
        self.add("assistant_config.contract", valid, self.config_name, "M12 runtime/modules/rag object", "valid" if valid else None,
                 "valid" if valid else "missing required assistant sections")
        if not valid:
            self.config_invalid = True
        if valid:
            for key in ("manual_qa_config", "voice_gateway_config"):
                self.regular_file(modules.get(key, ""), "assistant_config.modules." + key)
            self.regular_file("configs/manual-qa.json", "manual_config")
            self.regular_file("configs/voice-gateway.json", "voice_config")
        if self.valid_runtime_contract(runtime_contract):
            self.check_submodule(runtime_contract)
        if not self.valid_rag_contract(rag_contract):
            rag_contract = None
        return config, embedding, runtime_contract, rag_contract

    def valid_runtime_contract(self, contract: dict[str, Any] | None) -> bool:
        submodule = (contract or {}).get("submodule")
        build = (contract or {}).get("upstream_build")
        valid = (isinstance(submodule, dict) and submodule.get("path") == UPSTREAM and
                 isinstance(submodule.get("commit"), str) and len(submodule["commit"]) == 40 and
                 isinstance(build, dict) and isinstance(build.get("path"), str) and
                 isinstance(build.get("build_inputs"), list) and len(build["build_inputs"]) == 4 and
                 isinstance(build.get("assistant_tools"), list) and len(build["assistant_tools"]) == 2 and
                 all(isinstance(item, str) for item in build["build_inputs"] + build["assistant_tools"]))
        self.add("runtime_delivery_contract.contract", valid, RUNTIME_CONTRACT,
                 "runtime delivery contract", "valid" if valid else None,
                 "valid" if valid else "missing required runtime delivery fields")
        return valid

    def valid_rag_contract(self, contract: dict[str, Any] | None) -> bool:
        database = (contract or {}).get("database")
        metadata = (contract or {}).get("index_metadata")
        sources = (contract or {}).get("sources")
        required = {"algorithm_version", "embedding_fingerprint", "r2_2_index_fingerprint"}
        valid_sources = (isinstance(sources, list) and len(sources) == 3 and
                         all(isinstance(item, dict) and set(item) == {"source_path", "document_id", "revision", "content_sha256"}
                             and all(isinstance(item[field], str) and item[field] for field in item)
                             for item in sources))
        valid = (isinstance(database, dict) and isinstance(database.get("path"), str) and
                 isinstance(database.get("size_bytes"), int) and isinstance(metadata, dict) and
                 set(metadata) == required and all(isinstance(metadata[key], str) and metadata[key] for key in required) and
                 valid_sources)
        self.add("rag_delivery_contract.contract", valid, RAG_CONTRACT, "R2.2 delivery contract",
                 "valid" if valid else None, "valid" if valid else "missing required RAG delivery fields")
        return valid

    def check_submodule(self, contract: dict[str, Any]) -> None:
        expected = contract["submodule"]["commit"]
        try:
            observed = self.git_runner(["git", "-C", str(self.root / UPSTREAM), "rev-parse", "HEAD"])
        except VcsUnavailable as error:
            self.vcs_unavailable = True
            self.add("upstream.commit", False, UPSTREAM, expected, None, f"local Git unavailable: {error}")
            return
        self.add("upstream.commit", observed == expected, UPSTREAM, expected, observed,
                 "commit matches" if observed == expected else "submodule commit mismatch")

    def build_inputs(self, contract: dict[str, Any] | None) -> None:
        if contract is None:
            return
        build = contract["upstream_build"]
        for name in build["build_inputs"]:
            self.elf_aarch64(str(pathlib.PurePosixPath(build["path"]) / name), "upstream." + pathlib.PurePosixPath(name).name)

    def assistant(self, config: dict[str, Any], embedding: dict[str, Any] | None,
                  runtime_contract: dict[str, Any] | None, rag_contract: dict[str, Any] | None) -> None:
        runtime = config.get("runtime", {})
        self.elf_aarch64(runtime.get("executable", ""), "runtime_host")
        self.asset(runtime.get("model", {}), "vlm_model")
        self.asset(runtime.get("mmproj", {}), "vlm_mmproj")
        if runtime_contract is not None:
            build = runtime_contract["upstream_build"]
            for name in build["assistant_tools"]:
                self.elf_aarch64(str(pathlib.PurePosixPath(build["path"]) / name),
                                 "upstream." + pathlib.PurePosixPath(name).name.replace("-", "_"))
        if embedding is not None:
            self.embedding_asset(embedding.get("embedding", {}))
            self.check_knowledge(embedding)
        rag_path = ((config.get("rag") or {}).get("database"))
        self.check_rag(rag_path, embedding, rag_contract)

    def check_knowledge(self, embedding: dict[str, Any]) -> None:
        for index, source in enumerate(embedding.get("sources", [])):
            identifier = f"knowledge.{index}"
            if not isinstance(source, dict):
                self.add(identifier, False, None, "source object", None, "invalid source")
                continue
            path = self.regular_file(source.get("source_path", ""), identifier)
            expected = source.get("content_sha256")
            if path is not None:
                if not isinstance(expected, str) or len(expected) != 64:
                    self.add(identifier + ".sha256", False, source.get("source_path"), "64-character SHA-256",
                             expected, "invalid expected source SHA-256")
                    continue
                actual = sha256_file(path)
                self.add(identifier + ".sha256", actual == expected, source["source_path"], expected, actual,
                         "source hash matches" if actual == expected else "source hash mismatch")

    def check_rag(self, value: Any, embedding: dict[str, Any] | None, contract: dict[str, Any] | None) -> None:
        if not isinstance(value, str):
            self.add("rag.database", False, None, "repository-relative SQLite path", value, "invalid database path")
            return
        path = self.regular_file(value, "rag.database")
        if embedding is not None and contract is not None:
            expected_paths = [embedding.get("generated_database"), contract["database"]["path"]]
            self.add("rag.config_binding", value == expected_paths[0] == expected_paths[1], value, expected_paths, value,
                     "assistant, embedding, and delivery contract agree" if value == expected_paths[0] == expected_paths[1]
                     else "RAG paths differ")
        if path is None:
            return
        if contract is not None:
            expected_size = contract["database"]["size_bytes"]
            self.add("rag.size", path.stat().st_size == expected_size, value, expected_size, path.stat().st_size,
                     "size matches delivery contract" if path.stat().st_size == expected_size else "size differs from delivery contract")
            contract_sources = {
                (item["source_path"], item["document_id"], item["revision"], item["content_sha256"])
                for item in contract["sources"]
            }
            config_sources = {
                (item.get("source_path"), item.get("document_id"), item.get("revision"), item.get("content_sha256"))
                for item in (embedding or {}).get("sources", []) if isinstance(item, dict)
            }
            self.add("rag.source_binding", contract_sources == config_sources, value, sorted(contract_sources),
                     sorted(config_sources), "delivery contract and embedding sources agree" if contract_sources == config_sources
                     else "delivery contract and embedding sources differ")
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                connection.execute("PRAGMA schema_version").fetchone()
                if contract is not None:
                    documents = set(connection.execute(
                        "SELECT source_path, document_id, revision, content_sha256 FROM documents").fetchall())
                    expected_documents = {
                        (item["source_path"], item["document_id"], item["revision"], item["content_sha256"])
                        for item in contract["sources"]
                    }
                    self.add("rag.documents_binding", documents == expected_documents, value, sorted(expected_documents),
                             sorted(documents), "SQLite documents match delivery contract" if documents == expected_documents
                             else "SQLite documents differ from delivery contract")
                    metadata = dict(connection.execute(
                        "SELECT key, value FROM index_metadata WHERE key IN (?, ?, ?)",
                        ("algorithm_version", "embedding_fingerprint", "r2_2_index_fingerprint")).fetchall())
                    for key, expected in contract["index_metadata"].items():
                        observed = metadata.get(key)
                        self.add("rag.metadata." + key, observed == expected, value, expected, observed,
                                 "SQLite metadata matches delivery contract" if observed == expected
                                 else "SQLite metadata differs from delivery contract")
            finally:
                connection.close()
            self.add("rag.readonly", True, value, "read-only SQLite open", "opened", "opened read-only")
        except sqlite3.Error as error:
            self.add("rag.readonly", False, value, "read-only SQLite open", None, f"cannot open: {error}")

    def voice(self) -> None:
        _, voice = self.load_json("configs/voice-gateway.json", "voice_config")
        if voice is None:
            return
        for name in ("asr_model", "vad_model", "tts_model"):
            self.asset(voice.get(name, {}), "voice." + name)

    def run(self, profile: str) -> tuple[int, list[Check]]:
        config, embedding, runtime_contract, rag_contract = self.contract()
        if profile in {"build-inputs", "assistant", "voice"}:
            self.build_inputs(runtime_contract)
        if profile in {"assistant", "voice"} and config is not None:
            self.assistant(config, embedding, runtime_contract, rag_contract)
        if profile == "voice":
            self.voice()
        if self.vcs_unavailable:
            return EXIT_VCS, self.checks
        if self.config_invalid:
            return EXIT_USAGE, self.checks
        return (EXIT_OK if all(item.state == "pass" for item in self.checks) else EXIT_FAILED), self.checks


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repository root to inspect")
    parser.add_argument("--config", default="configs/assistant.json", help="repository-relative assistant config")
    parser.add_argument("--profile", choices=("contract", "build-inputs", "assistant", "voice"), default="assistant")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    root = pathlib.Path(args.root)
    if not root.is_dir():
        result = {"status": "usage_error", "exit_code": EXIT_USAGE, "checks": [], "message": "--root is not a directory"}
        print(json.dumps(result, sort_keys=True) if args.format == "json" else "usage error: --root is not a directory")
        return EXIT_USAGE
    verifier = Verifier(root, args.config)
    code, checks = verifier.run(args.profile)
    status = "pass" if code == EXIT_OK else "vcs_unavailable" if code == EXIT_VCS else "usage_error" if code == EXIT_USAGE else "fail"
    if args.format == "json":
        print(json.dumps({"exit_code": code, "profile": args.profile, "root": str(verifier.root), "status": status,
                          "checks": [item.json_value() for item in checks]}, ensure_ascii=False, sort_keys=True))
    else:
        for item in checks:
            print(f"[{item.state.upper()}] {item.id}: {item.message}")
        print(f"offline asset verification: {status} (exit {code})")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
