#!/usr/bin/env python3
"""M2 runtime-only preflight for the four frozen text-model candidates.

The script has two non-inference modes: ``--validate-only`` validates fixed
inputs and the CUDA probe, while ``--parse-stdout`` parses a prior CLI log.
Neither mode loads a model. Normal execution is intentionally blocked before
starting llama-cli when an asset or fixed-runtime gate fails.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "tools/benchmark/configs/model-selection-v1.json"
MANIFEST_PATH = ROOT / "manifests/model-selection.json"
RUNTIME = ROOT / "third_party/llama.cpp-omni"
DEFAULT_OUTPUT = ROOT / "benchmark-results/model-selection/preflight"
OFFLOAD_RE = re.compile(r"offloaded\s+(\d+)\s*/\s*(\d+)\s+layers\s+to\s+GPU", re.I)
CUDA_ERROR_RE = re.compile(
    r"(?:cuda|cublas|nvmap|nvrm|memory manager).*(?:error|failed|not supported)|failed to initialize CUDA",
    re.I,
)
FATAL_RE = re.compile(
    r"out of memory|\boom\b|failed to load|unsupported model|error.*(?:gguf|tokenizer|chat template|template)|(?:gguf|tokenizer|chat template|template).*error",
    re.I,
)
TIMING_RE = re.compile(r"^\[\s*Prompt:.*\]\s*$", re.M)
THINK_RE = re.compile(r"<think>\s*(?P<body>[\s\S]*?)\s*</think>", re.I)
ALT_THINK_RE = re.compile(r"\[Start thinking\](?P<body>[\s\S]*?)\[End thinking\]", re.I)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def git_value(path: Path, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", str(path), *args], check=False, capture_output=True, text=True)
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def project_state() -> dict[str, Any]:
    return {
        "commit": git_value(ROOT, "rev-parse", "HEAD"),
        "branch": git_value(ROOT, "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(git_value(ROOT, "status", "--porcelain", "--untracked-files=all")),
    }


def command_environment(binary: Path) -> dict[str, str]:
    """Match the baseline launcher: binary directory precedes existing libs."""
    env = os.environ.copy()
    binary_dir = str(binary.parent)
    current = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = binary_dir if not current else f"{binary_dir}:{current}"
    return env


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_gguf_metadata(path: Path) -> dict[str, Any]:
    sys.path.insert(0, str(RUNTIME / "gguf-py"))
    from gguf import GGUFReader  # type: ignore

    reader = GGUFReader(str(path), "r")
    values: dict[str, Any] = {}
    for key in (
        "general.architecture",
        "general.name",
        "general.file_type",
        "general.quantization_version",
        "general.license",
        "tokenizer.ggml.model",
        "tokenizer.chat_template",
    ):
        field = reader.get_field(key)
        if field is None:
            values[key] = None
        elif key == "tokenizer.chat_template":
            values[key] = {"present": True, "content_recorded": False}
        else:
            content = field.contents()
            values[key] = content.item() if hasattr(content, "item") else content
    return values


def cli_probe(binary: Path, required_options: list[str]) -> dict[str, Any]:
    env = command_environment(binary)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return {"binary_error": f"llama-cli is missing or not executable: {binary}", "required_options_missing": required_options}
    help_result = subprocess.run([str(binary), "--help"], check=False, capture_output=True, text=True, env=env)
    list_result = subprocess.run([str(binary), "--list-devices"], check=False, capture_output=True, text=True, env=env)
    help_text = f"{help_result.stdout}\n{help_result.stderr}"
    devices_text = f"{list_result.stdout}\n{list_result.stderr}"
    missing = [option for option in required_options if option not in help_text]
    has_cuda0 = bool(re.search(r"CUDA0\s*:\s*Orin", devices_text, re.I))
    device_node_visible = Path("/dev/nvmap").exists()
    return {
        "help_exit_code": help_result.returncode,
        "list_devices_exit_code": list_result.returncode,
        "required_options_missing": missing,
        "devices_output": devices_text.strip(),
        "cuda0_orin": has_cuda0,
        "device_node_visible": device_node_visible,
        "blocked_by_sandbox": not device_node_visible and not has_cuda0,
        "ld_library_path": env["LD_LIBRARY_PATH"],
    }


def command_for(config: dict[str, Any], candidate_id: str) -> list[str]:
    candidate = config["candidates"][candidate_id]
    binary = ROOT / config["cli"]
    command = [str(binary), "--model", str(ROOT / candidate["model"]), "--prompt", config["prompt"]]
    command.extend(config["common_args"])
    command.extend(candidate.get("extra_args", []))
    return command


def asset_failures(item: dict[str, Any]) -> list[str]:
    required = ("exists", "size_matches", "sha256_matches", "architecture_matches", "q4_k_m", "tokenizer_present", "chat_template_present")
    failures = [name for name in required if item.get(name) is not True]
    if item.get("metadata_error"):
        failures.append("metadata_error")
    return failures


def validate_assets(config: dict[str, Any], candidate_ids: list[str]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for candidate_id in candidate_ids:
        candidate = config["candidates"][candidate_id]
        path = ROOT / candidate["model"]
        item: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
        if path.is_file():
            item["size_bytes"] = path.stat().st_size
            item["size_matches"] = item["size_bytes"] == candidate["size_bytes"]
            item["sha256"] = sha256_file(path)
            item["sha256_matches"] = item["sha256"] == candidate["sha256"]
            try:
                metadata = load_gguf_metadata(path)
                item["metadata"] = metadata
                item["architecture_matches"] = metadata.get("general.architecture") == candidate["architecture"]
                item["q4_k_m"] = metadata.get("general.file_type") == 15
                item["tokenizer_present"] = metadata.get("tokenizer.ggml.model") is not None
                item["chat_template_present"] = bool(metadata.get("tokenizer.chat_template"))
            except Exception as exc:  # noqa: BLE001 - saved to make an asset block auditable
                item["metadata_error"] = str(exc)
        item["failures"] = asset_failures(item)
        item["status"] = "PASS" if not item["failures"] else "BLOCKED_ASSET"
        checks[candidate_id] = item
    return checks


def runtime_gate(config: dict[str, Any], manifest: dict[str, Any], binary: Path, probe: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    expected_commit = config["runtime_commit"]
    expected_branch = config["runtime_branch"]
    expected_cli_sha = config["cli_sha256"]
    if git_value(RUNTIME, "rev-parse", "HEAD") != expected_commit:
        failures.append("runtime_commit")
    if git_value(RUNTIME, "rev-parse", "--abbrev-ref", "HEAD") != expected_branch:
        failures.append("runtime_branch")
    if not binary.is_file() or sha256_file(binary) != expected_cli_sha:
        failures.append("cli_sha256")
    if manifest.get("runtime", {}).get("commit") != expected_commit or manifest.get("runtime", {}).get("branch") != expected_branch:
        failures.append("manifest_runtime_identity")
    if manifest.get("cli", {}).get("sha256") != expected_cli_sha:
        failures.append("manifest_cli_sha256")
    if probe.get("help_exit_code") != 0:
        failures.append("cli_help")
    if probe.get("required_options_missing"):
        failures.append("required_cli_options")
    return failures


def extract_response_text(stdout: str, prompt: str) -> str:
    """Remove the interactive CLI framing without altering the generated text."""
    marker = f"> {prompt}"
    start = stdout.rfind(marker)
    response = stdout[start + len(marker):] if start >= 0 else stdout
    response = response.lstrip("\r\n")
    response = TIMING_RE.split(response, maxsplit=1)[0]
    response = re.split(r"^Exiting\.\.\.\s*$", response, maxsplit=1, flags=re.M)[0]
    return response.strip()


def summarize_output(stdout: str, stderr: str, candidate_id: str, prompt: str) -> dict[str, Any]:
    combined = f"{stdout}\n{stderr}"
    offloads = [{"offloaded": int(match.group(1)), "total": int(match.group(2))} for match in OFFLOAD_RE.finditer(combined)]
    response = extract_response_text(stdout, prompt)
    error_lines = [line.strip() for line in combined.splitlines() if CUDA_ERROR_RE.search(line) or FATAL_RE.search(line)]
    thinking_bodies = [match.group("body").strip() for match in THINK_RE.finditer(response)]
    thinking_bodies.extend(match.group("body").strip() for match in ALT_THINK_RE.finditer(response))
    return {
        "response_text": response,
        "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
        "output_nonempty": bool(response),
        "output_complete": bool(response) and bool(re.search(r"^Exiting\.\.\.\s*$", stdout, re.M)),
        "exact_ready_match": response == "READY",
        "offload_matches": offloads,
        "offload_all_layers": bool(offloads) and any(item["offloaded"] == item["total"] for item in offloads),
        "error_lines": error_lines,
        "qwen3_reasoning_nonempty": candidate_id == "qwen3" and any(thinking_bodies),
        "qwen3_empty_reasoning_tags": candidate_id == "qwen3" and bool(thinking_bodies) and all(not body for body in thinking_bodies),
    }


def run_candidate(config: dict[str, Any], candidate_id: str, directory: Path, timeout: int) -> dict[str, Any]:
    command = command_for(config, candidate_id)
    (directory / "command.json").write_text(json.dumps({"argv": command}, indent=2) + "\n", encoding="utf-8")
    stdout_path = directory / "stdout.log"
    stderr_path = directory / "stderr.log"
    tegrastats_path = directory / "tegrastats.log"
    tegrastats: subprocess.Popen[str] | None = None
    tegrastats_stream = None
    started = time.monotonic()
    try:
        if shutil.which("tegrastats"):
            tegrastats_stream = tegrastats_path.open("w", encoding="utf-8")
            tegrastats = subprocess.Popen(["tegrastats", "--interval", str(config["tegrastats_interval_ms"])], stdout=tegrastats_stream, stderr=subprocess.STDOUT, text=True)
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, text=True, timeout=timeout, check=False, env=command_environment(Path(command[0])))
        details = summarize_output(stdout_path.read_text(encoding="utf-8", errors="replace"), stderr_path.read_text(encoding="utf-8", errors="replace"), candidate_id, config["prompt"])
        passed = result.returncode == 0 and details["output_nonempty"] and details["output_complete"] and details["offload_all_layers"] and not details["error_lines"]
        if candidate_id == "qwen3":
            passed = passed and not details["qwen3_reasoning_nonempty"]
        return {"status": "PASS" if passed else "FAIL", "exit_code": result.returncode, "wall_time_ms": round((time.monotonic() - started) * 1000, 3), **details}
    except subprocess.TimeoutExpired:
        return {"status": "FAIL", "error": "timeout", "wall_time_ms": round((time.monotonic() - started) * 1000, 3)}
    finally:
        if tegrastats is not None and tegrastats.poll() is None:
            tegrastats.terminate()
            try:
                tegrastats.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tegrastats.kill()
                tegrastats.wait(timeout=5)
        if tegrastats_stream is not None:
            tegrastats_stream.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--print-commands", action="store_true")
    parser.add_argument("--parse-stdout", type=Path, help="parse an existing stdout log without running llama-cli")
    parser.add_argument("--candidate", choices=["qwen25", "qwen3", "phi35", "llama32"])
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.parse_stdout and not args.candidate:
        parser.error("--parse-stdout requires --candidate")
    config = load_json(CONFIG_PATH)
    manifest = load_json(MANIFEST_PATH)
    candidate_ids = [args.candidate] if args.candidate else list(config["candidates"])
    binary = ROOT / config["cli"]
    required_options = config["required_cli_options"]
    probe = cli_probe(binary, required_options)
    assets = validate_assets(config, candidate_ids)
    gate_failures = runtime_gate(config, manifest, binary, probe)
    result: dict[str, Any] = {
        "schema_version": 2,
        "run_id": utc_now(),
        "project_git": project_state(),
        "runtime_commit": git_value(RUNTIME, "rev-parse", "HEAD"),
        "runtime_branch": git_value(RUNTIME, "rev-parse", "--abbrev-ref", "HEAD"),
        "preflight_script_sha256": sha256_file(Path(__file__).resolve()),
        "config_sha256": sha256_file(CONFIG_PATH),
        "manifest_sha256": sha256_file(MANIFEST_PATH),
        "cli": {"path": str(binary), "sha256": sha256_file(binary) if binary.is_file() else None, "probe": probe},
        "nvpmodel": subprocess.run(["nvpmodel", "-q"], check=False, capture_output=True, text=True).stdout.strip(),
        "runtime_gate_failures": gate_failures,
        "assets": assets,
        "candidates": {},
    }
    if args.print_commands:
        result["commands"] = {candidate_id: command_for(config, candidate_id) for candidate_id in candidate_ids}
    if args.parse_stdout:
        stdout = args.parse_stdout.read_text(encoding="utf-8", errors="replace")
        result["parsed_stdout"] = summarize_output(stdout, "", args.candidate, config["prompt"])
        result["status"] = "PASS"
    elif gate_failures:
        result["status"] = "FAIL"
        result["candidates"] = {candidate_id: {"status": "FAIL", "reason": "fixed runtime/CLI gate failed"} for candidate_id in candidate_ids}
    elif any(item["status"] == "BLOCKED_ASSET" for item in assets.values()):
        result["status"] = "BLOCKED_ASSET"
        result["candidates"] = {candidate_id: {"status": item["status"], "asset_failures": item["failures"]} for candidate_id, item in assets.items()}
    elif probe.get("blocked_by_sandbox"):
        result["status"] = "BLOCKED_SANDBOX"
        result["candidates"] = {candidate_id: {"status": "BLOCKED_SANDBOX", "reason": "CUDA0 and /dev/nvmap are both unavailable in this environment"} for candidate_id in candidate_ids}
    elif not probe.get("cuda0_orin"):
        result["status"] = "FAIL"
        result["candidates"] = {candidate_id: {"status": "FAIL", "reason": "host device node is visible but CUDA0: Orin did not initialize"} for candidate_id in candidate_ids}
    elif args.validate_only or args.print_commands:
        result["status"] = "PASS"
        result["candidates"] = {candidate_id: {"status": "PASS", "mode": "validate_only"} for candidate_id in candidate_ids}
    else:
        args.output_root.mkdir(parents=True, exist_ok=True)
        for candidate_id in candidate_ids:
            directory = args.output_root / result["run_id"] / candidate_id
            directory.mkdir(parents=True, exist_ok=True)
            result["candidates"][candidate_id] = run_candidate(config, candidate_id, directory, config["timeout_seconds"])
        result["status"] = "PASS" if all(item["status"] == "PASS" for item in result["candidates"].values()) else "FAIL"
    output_dir = args.output_root / result["run_id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] in {"PASS", "BLOCKED_SANDBOX", "BLOCKED_ASSET"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
