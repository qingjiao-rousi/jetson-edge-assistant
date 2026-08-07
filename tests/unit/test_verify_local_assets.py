import contextlib
import hashlib
import io
import json
import pathlib
import sqlite3
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_local_assets as verify


COMMIT = "19cc26967140407efe34006a355ab445b35b16ac"


def write(path: pathlib.Path, data: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": path.as_posix(), "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def elf(path: pathlib.Path) -> None:
    header = bytearray(20)
    header[:4], header[4], header[5] = b"\x7fELF", 2, 1
    struct.pack_into("<H", header, 18, 183)
    write(path, bytes(header))


class OfflineAssetVerifierTest(unittest.TestCase):
    def make_tree(self) -> pathlib.Path:
        self.temp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.temp.name) / "repo"
        root.mkdir()
        def asset(relative: str, data: bytes) -> dict:
            metadata = write(root / relative, data)
            metadata["path"] = relative
            return metadata
        for name in ("CMakeLists.txt", "runtime/CMakeLists.txt", "third_party/llama.cpp-omni/include/x.h",
                     "third_party/llama.cpp-omni/ggml/include/x.h", "third_party/llama.cpp-omni/tools/mtmd/x.h",
                     "third_party/llama.cpp-omni/vendor/cpp-httplib/x.h"):
            write(root / name, b"source")
        for name in ("libllama.so", "libmtmd.so", "libggml.so", "libggml-cuda.so", "llama-embedding", "llama-tokenize"):
            elf(root / "third_party/llama.cpp-omni/build-jetson-release/bin" / name)
        elf(root / "build-runtime/runtime/edgeomni_vlm_service_host")
        main = asset("models/main.gguf", b"main")
        mmproj = asset("models/mmproj.gguf", b"mmproj")
        embedding = asset("models/embedding.gguf", b"embedding")
        asr = asset("models/asr.onnx", b"asr")
        vad = asset("models/vad.onnx", b"vad")
        tts = asset("models/tts.onnx", b"tts")
        source = asset("knowledge/manual.md", b"manual")
        database = root / "generated/rag-m9.1b-r2.2/hybrid.sqlite3"
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE items (id INTEGER)")
        connection.commit()
        connection.close()
        database_size = database.stat().st_size
        (root / "configs").mkdir()
        (root / "configs/manual-qa.json").write_text("{}")
        (root / "configs/assistant.json").write_text(json.dumps({
            "runtime": {"executable": "build-runtime/runtime/edgeomni_vlm_service_host", "model": main,
                        "mmproj": mmproj},
            "rag": {"database": "generated/rag-m9.1b-r2.2/hybrid.sqlite3"},
            "modules": {"manual_qa_config": "configs/manual-qa.json", "voice_gateway_config": "configs/voice-gateway.json"},
        }))
        (root / "configs/embedding.json").write_text(json.dumps({
            "embedding": {"model_path": embedding["path"], "model_size_bytes": embedding["size_bytes"],
                          "model_sha256": embedding["sha256"]},
            "generated_database": "generated/rag-m9.1b-r2.2/hybrid.sqlite3",
            "sources": [{"source_path": "knowledge/manual.md", "content_sha256": source["sha256"]}],
        }))
        def voice_spec(value): return {**value, "language": "zh", "sample_rate": 16000, "license": "Apache-2.0"}
        (root / "configs/voice-gateway.json").write_text(json.dumps({"asr_model": voice_spec(asr), "vad_model": voice_spec(vad), "tts_model": voice_spec(tts)}))
        manifest = {"submodule": {"commit": COMMIT}}
        write(root / "evidence/benchmarks/manifests/runtime.json", json.dumps(manifest).encode())
        write(root / "evidence/milestones/evaluation/rag-hybrid-m9.1b-r2.2-index-manifest.json",
              json.dumps({"database_size_bytes": database_size,
                          "documents": [{"source_path": "knowledge/manual.md", "content_sha256": source["sha256"]}]}).encode())
        return root

    def tearDown(self):
        self.temp.cleanup()

    def verifier(self, root, commit=COMMIT):
        return verify.Verifier(root, "configs/assistant.json", git_runner=lambda _: commit)

    def test_all_profiles_pass_on_minimal_offline_tree(self):
        root = self.make_tree()
        for profile in ("contract", "build-inputs", "assistant", "voice"):
            code, checks = self.verifier(root).run(profile)
            self.assertEqual(code, verify.EXIT_OK, profile)
            self.assertTrue(all(item.state == "pass" for item in checks))

    def test_path_escape_missing_and_hash_mismatch_fail(self):
        root = self.make_tree()
        config_path = root / "configs/assistant.json"
        config = json.loads(config_path.read_text())
        config["runtime"]["model"]["path"] = "../outside.gguf"
        config_path.write_text(json.dumps(config))
        code, checks = self.verifier(root).run("assistant")
        self.assertEqual(code, verify.EXIT_FAILED)
        self.assertTrue(any(item.id == "vlm_model.path" and item.state == "fail" for item in checks))
        config["runtime"]["model"]["path"] = "models\\main.gguf"
        config_path.write_text(json.dumps(config))
        code, checks = self.verifier(root).run("assistant")
        self.assertEqual(code, verify.EXIT_FAILED)
        self.assertTrue(any(item.id == "vlm_model.path" and item.state == "fail" for item in checks))
        config["runtime"]["model"]["path"] = "models/main.gguf"
        config["runtime"]["model"]["sha256"] = "0" * 64
        config_path.write_text(json.dumps(config))
        code, checks = self.verifier(root).run("assistant")
        self.assertEqual(code, verify.EXIT_FAILED)
        self.assertTrue(any(item.id == "vlm_model.sha256" and item.state == "fail" for item in checks))
        (root / "third_party/llama.cpp-omni/build-jetson-release/bin/libmtmd.so").unlink()
        code, checks = self.verifier(root).run("build-inputs")
        self.assertEqual(code, verify.EXIT_FAILED)
        self.assertTrue(any(item.id == "upstream.libmtmd.so" and item.state == "fail" for item in checks))

    def test_wrong_commit_and_missing_git_return_distinct_codes(self):
        root = self.make_tree()
        code, _ = self.verifier(root, "bad").run("contract")
        self.assertEqual(code, verify.EXIT_FAILED)
        def missing_git(_): raise verify.VcsUnavailable("git absent")
        code, checks = verify.Verifier(root, "configs/assistant.json", git_runner=missing_git).run("contract")
        self.assertEqual(code, verify.EXIT_VCS)
        self.assertTrue(any(item.id == "upstream.commit" and item.state == "fail" for item in checks))

    def test_sqlite_readonly_failure_and_json_cli_output(self):
        root = self.make_tree()
        database = root / "generated/rag-m9.1b-r2.2/hybrid.sqlite3"
        database.write_bytes(b"not sqlite")
        code, checks = self.verifier(root).run("assistant")
        self.assertEqual(code, verify.EXIT_FAILED)
        self.assertTrue(any(item.id == "rag.readonly" and item.state == "fail" for item in checks))
        with mock.patch.object(verify.Verifier, "_run_git", return_value=COMMIT), contextlib.redirect_stdout(io.StringIO()) as output:
            code = verify.main(["--root", str(root), "--profile", "contract", "--format", "json"])
        result = json.loads(output.getvalue())
        self.assertEqual((code, result["exit_code"], result["status"]), (verify.EXIT_OK, verify.EXIT_OK, "pass"))
        self.assertEqual([item["id"] for item in result["checks"]], [item.id for item in self.verifier(root).run("contract")[1]])
        self.assertEqual(verify.main(["--root", str(root / "missing")]), verify.EXIT_USAGE)

    def test_invalid_assistant_configuration_returns_usage_error(self):
        root = self.make_tree()
        (root / "configs/assistant.json").write_text("{")
        code, checks = self.verifier(root).run("assistant")
        self.assertEqual(code, verify.EXIT_USAGE)
        self.assertTrue(any(item.id == "assistant_config" and item.state == "fail" for item in checks))


if __name__ == "__main__":
    unittest.main()
