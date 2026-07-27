#!/usr/bin/env python3
"""Run the frozen M3 four-model CLI comparison after all pre-run gates pass.

This script deliberately refuses a formal run from a dirty project checkout.
Use --validate-only, --print-commands, or --dry-run for non-inference checks.
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


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "third_party/llama.cpp-omni"
SELECTION_CONFIG = ROOT / "configs/model-selection-v1.json"
PROMPTS_CONFIG = ROOT / "configs/model-selection-prompts-v1.json"
MANIFEST = ROOT / "manifests/model-selection.json"
DEFAULT_OUTPUT = ROOT / "benchmark-results/model-selection"
OFFLOAD_RE = re.compile(r"offloaded\s+(\d+)\s*/\s*(\d+)\s+layers\s+to\s+GPU", re.I)
PROMPT_TIMING_RE = re.compile(r"prompt eval time\s*=\s*([0-9.]+) ms\s*/\s*([0-9]+) tokens.*?([0-9.]+) tokens per second", re.I)
DECODE_TIMING_RE = re.compile(r"eval time\s*=\s*([0-9.]+) ms\s*/\s*([0-9]+) (?:tokens|runs).*?([0-9.]+) tokens per second", re.I)
TOTAL_TIMING_RE = re.compile(r"total time\s*=\s*([0-9.]+) ms", re.I)
TIMING_LINE_RE = re.compile(r"^\[\s*Prompt:.*\]\s*$", re.M)
CUDA_ERROR_RE = re.compile(r"(?:cuda|cublas|nvmap|nvrm|memory manager).*(?:error|failed|not supported)|failed to initialize CUDA", re.I)
FATAL_RE = re.compile(r"out of memory|\boom\b|failed to load|unsupported model|error.*(?:gguf|tokenizer|chat template|template)|(?:gguf|tokenizer|chat template|template).*error", re.I)
THINK_RE = re.compile(r"<think>\s*(?P<body>[\s\S]*?)\s*</think>|\[Start thinking\](?P<alt>[\s\S]*?)\[End thinking\]", re.I)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def git_value(path: Path, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", str(path), *args], check=False, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def command_environment(binary: Path) -> dict[str, str]:
    """Use the same build-library precedence as the frozen Qwen2.5 baseline."""
    env = os.environ.copy()
    current = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = str(binary.parent) if not current else f"{binary.parent}:{current}"
    return env


def read_metadata(path: Path) -> dict[str, Any]:
    sys.path.insert(0, str(RUNTIME / "gguf-py"))
    from gguf import GGUFReader  # type: ignore

    reader = GGUFReader(str(path), "r")
    result: dict[str, Any] = {}
    for key in ("general.architecture", "general.file_type", "tokenizer.ggml.model", "tokenizer.chat_template"):
        field = reader.get_field(key)
        if field is None:
            result[key] = None
        elif key == "tokenizer.chat_template":
            result[key] = {"present": True, "content_recorded": False}
        else:
            value = field.contents()
            result[key] = value.item() if hasattr(value, "item") else value
    return result


def candidate_assets(config: dict[str, Any], candidate_ids: list[str]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for candidate_id in candidate_ids:
        expected = config["candidates"][candidate_id]
        path = ROOT / expected["model"]
        item: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
        if path.is_file():
            item["size_bytes"] = path.stat().st_size
            item["size_matches"] = item["size_bytes"] == expected["size_bytes"]
            item["sha256"] = sha256_file(path)
            item["sha256_matches"] = item["sha256"] == expected["sha256"]
            try:
                metadata = read_metadata(path)
                item["metadata"] = metadata
                item["architecture_matches"] = metadata["general.architecture"] == expected["architecture"]
                item["q4_k_m"] = metadata["general.file_type"] == 15
                item["tokenizer_present"] = metadata["tokenizer.ggml.model"] is not None
                item["chat_template_present"] = bool(metadata["tokenizer.chat_template"])
            except Exception as exc:  # Persist parser errors as an auditable hard gate.
                item["metadata_error"] = str(exc)
        required = ("exists", "size_matches", "sha256_matches", "architecture_matches", "q4_k_m", "tokenizer_present", "chat_template_present")
        item["failures"] = [name for name in required if item.get(name) is not True]
        if item.get("metadata_error"):
            item["failures"].append("metadata_error")
        checks[candidate_id] = item
    return checks


def cli_probe(binary: Path, required: list[str]) -> dict[str, Any]:
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return {"error": "llama-cli missing or not executable", "required_options_missing": required}
    env = command_environment(binary)
    help_result = subprocess.run([str(binary), "--help"], check=False, capture_output=True, text=True, env=env)
    devices_result = subprocess.run([str(binary), "--list-devices"], check=False, capture_output=True, text=True, env=env)
    help_text = f"{help_result.stdout}\n{help_result.stderr}"
    device_text = f"{devices_result.stdout}\n{devices_result.stderr}"
    return {
        "help_exit_code": help_result.returncode,
        "list_devices_exit_code": devices_result.returncode,
        "required_options_missing": [option for option in required if option not in help_text],
        "cuda0_orin": bool(re.search(r"CUDA0\s*:\s*Orin", device_text, re.I)),
        "devices_output": device_text.strip(),
        "ld_library_path": env["LD_LIBRARY_PATH"],
    }


def power_mode() -> dict[str, Any]:
    result = subprocess.run(["nvpmodel", "-q"], check=False, capture_output=True, text=True)
    output = f"{result.stdout}\n{result.stderr}".strip()
    return {"exit_code": result.returncode, "output": output, "matches_mode_30w_id_2": bool(re.search(r"NV Power Mode:\s*MODE_30W\s*\n\s*2\b", output))}


def validate(config: dict[str, Any], manifest: dict[str, Any], candidate_ids: list[str]) -> dict[str, Any]:
    binary = ROOT / config["cli"]
    project_commit = git_value(ROOT, "rev-parse", "HEAD")
    project_dirty = bool(git_value(ROOT, "status", "--porcelain", "--untracked-files=all"))
    probe = cli_probe(binary, config["required_cli_options"])
    assets = candidate_assets(config, candidate_ids)
    power = power_mode()
    failures: list[str] = []
    if project_commit is None:
        failures.append("project_has_no_head")
    if project_dirty:
        failures.append("project_worktree_dirty")
    if git_value(RUNTIME, "rev-parse", "--abbrev-ref", "HEAD") != config["runtime_branch"]:
        failures.append("runtime_branch")
    if git_value(RUNTIME, "rev-parse", "HEAD") != config["runtime_commit"]:
        failures.append("runtime_commit")
    if not binary.is_file() or sha256_file(binary) != config["cli_sha256"]:
        failures.append("cli_sha256")
    if manifest.get("runtime", {}).get("branch") != config["runtime_branch"] or manifest.get("runtime", {}).get("commit") != config["runtime_commit"]:
        failures.append("manifest_runtime_identity")
    if manifest.get("cli", {}).get("sha256") != config["cli_sha256"]:
        failures.append("manifest_cli_sha256")
    if probe.get("help_exit_code") != 0 or probe.get("required_options_missing"):
        failures.append("required_cli_options")
    if not probe.get("cuda0_orin"):
        failures.append("cuda0_orin")
    if not power["matches_mode_30w_id_2"]:
        failures.append("power_mode")
    if shutil.which("tegrastats") is None:
        failures.append("tegrastats")
    for candidate_id, asset in assets.items():
        if asset["failures"]:
            failures.append(f"asset:{candidate_id}:{','.join(asset['failures'])}")
    return {
        "valid": not failures,
        "failures": failures,
        "project_git": {"commit": project_commit, "branch": git_value(ROOT, "rev-parse", "--abbrev-ref", "HEAD"), "dirty": project_dirty},
        "runtime": {"branch": git_value(RUNTIME, "rev-parse", "--abbrev-ref", "HEAD"), "commit": git_value(RUNTIME, "rev-parse", "HEAD")},
        "cli": {"path": str(binary), "sha256": sha256_file(binary) if binary.is_file() else None, "probe": probe},
        "power_mode": power,
        "assets": assets,
    }


def command_for(config: dict[str, Any], candidate_id: str, prompt: str, n_predict: int) -> list[str]:
    candidate = config["candidates"][candidate_id]
    common = list(config["common_args"])
    index = common.index("--n-predict")
    common[index + 1] = str(n_predict)
    return [str(ROOT / config["cli"]), "--model", str(ROOT / candidate["model"]), "--prompt", prompt, *common, *candidate.get("extra_args", [])]


def extract_response(stdout: str, prompt: str) -> str:
    marker = f"> {prompt}"
    index = stdout.rfind(marker)
    answer = stdout[index + len(marker):] if index >= 0 else stdout
    answer = answer.lstrip("\r\n")
    answer = TIMING_LINE_RE.split(answer, maxsplit=1)[0]
    answer = re.split(r"^Exiting\.\.\.\s*$", answer, maxsplit=1, flags=re.M)[0]
    return answer.strip()


def runtime_metrics(stderr: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {"runtime_prompt_eval_ms": None, "runtime_prompt_tokens": None, "runtime_prompt_tokens_per_second": None, "runtime_decode_eval_ms": None, "runtime_decode_tokens": None, "runtime_decode_tokens_per_second": None, "runtime_total_ms": None}
    if match := PROMPT_TIMING_RE.search(stderr):
        metrics.update({"runtime_prompt_eval_ms": float(match.group(1)), "runtime_prompt_tokens": int(match.group(2)), "runtime_prompt_tokens_per_second": float(match.group(3))})
    if match := DECODE_TIMING_RE.search(stderr):
        metrics.update({"runtime_decode_eval_ms": float(match.group(1)), "runtime_decode_tokens": int(match.group(2)), "runtime_decode_tokens_per_second": float(match.group(3))})
    if match := TOTAL_TIMING_RE.search(stderr):
        metrics["runtime_total_ms"] = float(match.group(1))
    return metrics


def telemetry_peaks(path: Path) -> dict[str, int | None]:
    values: dict[str, list[int]] = {"peak_ram_mb": [], "peak_gr3d_percent": [], "peak_gpu_temp_c": [], "peak_tj_temp_c": [], "peak_vdd_gpu_soc_mw": []}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            patterns = {
                "peak_ram_mb": r"\bRAM\s+(\d+)/",
                "peak_gr3d_percent": r"\bGR3D_FREQ\s+(\d+)%",
                "peak_gpu_temp_c": r"\bGPU@([0-9]+(?:\.[0-9]+)?)C",
                "peak_tj_temp_c": r"\bTJ@([0-9]+(?:\.[0-9]+)?)C",
                "peak_vdd_gpu_soc_mw": r"\bVDD_GPU_SOC\s+(\d+)mW",
            }
            for key, pattern in patterns.items():
                if match := re.search(pattern, line):
                    values[key].append(round(float(match.group(1))))
    return {key: max(samples) if samples else None for key, samples in values.items()}


def automatic_checks(prompt_id: str, response: str, metrics: dict[str, Any], n_predict: int) -> dict[str, Any]:
    json_valid: bool | None = None
    if prompt_id in {"J-05", "J-10"}:
        try:
            json.loads(response)
            json_valid = True
        except json.JSONDecodeError:
            json_valid = False
    step_lines = re.findall(r"(?m)^\s*(?:[0-9]+[.)、]|第[一二三四五六七八九十]+步)", response)
    return {
        "json_valid": json_valid,
        "exact_ready_match": response == "READY" if prompt_id == "J-09" else None,
        "exact_four_steps": len(step_lines) == 4 if prompt_id == "J-03" else None,
        "suspected_n_predict_truncation": metrics.get("runtime_decode_tokens") is not None and metrics["runtime_decode_tokens"] >= n_predict and not re.search(r"[。.!?}\]）)]$", response),
    }


def output_details(stdout: str, stderr: str, prompt: str, candidate_id: str, n_predict: int) -> dict[str, Any]:
    response = extract_response(stdout, prompt)
    combined = f"{stdout}\n{stderr}"
    offloads = [{"offloaded": int(match.group(1)), "total": int(match.group(2))} for match in OFFLOAD_RE.finditer(combined)]
    thinking = [(match.group("body") or match.group("alt") or "").strip() for match in THINK_RE.finditer(response)]
    metrics = runtime_metrics(stderr)
    return {
        "response_text": response,
        "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
        "output_complete": bool(response) and bool(re.search(r"^Exiting\.\.\.\s*$", stdout, re.M)),
        "offload_matches": offloads,
        "offload_all_layers": bool(offloads) and any(item["offloaded"] == item["total"] for item in offloads),
        "error_lines": [line.strip() for line in combined.splitlines() if CUDA_ERROR_RE.search(line) or FATAL_RE.search(line)],
        "qwen3_reasoning_nonempty": candidate_id == "qwen3" and any(thinking),
        "qwen3_empty_reasoning_tags": candidate_id == "qwen3" and bool(thinking) and all(not body for body in thinking),
        "automatic_checks": automatic_checks("", response, metrics, n_predict),
        **metrics,
    }


def run_once(config: dict[str, Any], provenance: dict[str, Any], candidate_id: str, prompt: dict[str, Any], phase: str, attempt: int, directory: Path, n_predict: int) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=False)
    command = command_for(config, candidate_id, prompt["text"], n_predict)
    (directory / "command.json").write_text(json.dumps({"argv": command}, indent=2) + "\n", encoding="utf-8")
    stdout_path, stderr_path, telemetry_path = directory / "stdout.log", directory / "stderr.log", directory / "tegrastats.log"
    telemetry_stream = telemetry_path.open("w", encoding="utf-8")
    telemetry = subprocess.Popen([str(shutil.which("tegrastats")), "--interval", str(config["tegrastats_interval_ms"])], stdout=telemetry_stream, stderr=subprocess.STDOUT, text=True)
    started = time.monotonic_ns()
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            completed = subprocess.run(command, check=False, stdout=stdout, stderr=stderr, text=True, env=command_environment(Path(command[0])))
        exit_code = completed.returncode
    finally:
        if telemetry.poll() is None:
            telemetry.terminate()
            try:
                telemetry.wait(timeout=5)
            except subprocess.TimeoutExpired:
                telemetry.kill()
                telemetry.wait(timeout=5)
        telemetry_stream.close()
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    details = output_details(stdout, stderr, prompt["text"], candidate_id, n_predict)
    details["automatic_checks"] = automatic_checks(prompt["id"], details["response_text"], details, n_predict)
    valid = exit_code == 0 and details["output_complete"] and details["offload_all_layers"] and not details["error_lines"] and (candidate_id != "qwen3" or not details["qwen3_reasoning_nonempty"])
    return {
        "schema_version": 1, "run_id": provenance["run_id"], "candidate_id": candidate_id, "prompt_id": prompt["id"], "phase": phase, "attempt": attempt, "valid": valid, "exit_code": exit_code,
        "project_git": provenance["project_git"], "runtime_commit": provenance["runtime_commit"], "runtime_branch": provenance["runtime_branch"], "cli_sha256": provenance["cli_sha256"], "model_sha256": provenance["model_sha256"][candidate_id], "script_sha256": provenance["script_sha256"], "selection_config_sha256": provenance["selection_config_sha256"], "prompts_config_sha256": provenance["prompts_config_sha256"], "manifest_sha256": provenance["manifest_sha256"],
        "wall_time_ms": round((time.monotonic_ns() - started) / 1_000_000, 3), "artifacts": {"command": str((directory / "command.json").relative_to(ROOT)), "stdout": str(stdout_path.relative_to(ROOT)), "stderr": str(stderr_path.relative_to(ROOT)), "telemetry": str(telemetry_path.relative_to(ROOT))},
        **details, **telemetry_peaks(telemetry_path),
    }


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--print-commands", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--candidate", choices=["qwen25", "qwen3", "phi35", "llama32"])
    parser.add_argument("--prompt-id")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--preconditioning-runs", type=int, default=1)
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    config, prompts, manifest = load_json(SELECTION_CONFIG), load_json(PROMPTS_CONFIG), load_json(MANIFEST)
    candidate_ids = [args.candidate] if args.candidate else list(config["candidates"])
    prompt_list = [item for item in prompts["prompts"] if not args.prompt_id or item["id"] == args.prompt_id]
    if not prompt_list:
        parser.error("--prompt-id is not in configs/model-selection-prompts-v1.json")
    if args.runs < 1 or args.preconditioning_runs < 1 or args.max_attempts < args.runs:
        parser.error("--runs and --preconditioning-runs must be positive; --max-attempts must be >= --runs")
    validation = validate(config, manifest, candidate_ids)
    plan = {"candidates": candidate_ids, "prompts": [item["id"] for item in prompt_list], "preconditioning_processes": len(candidate_ids) * args.preconditioning_runs, "required_measured_processes": len(candidate_ids) * len(prompt_list) * args.runs, "maximum_measured_processes": len(candidate_ids) * len(prompt_list) * args.max_attempts}
    if args.validate_only:
        print(json.dumps(validation, indent=2, ensure_ascii=False))
        return 0 if validation["valid"] else 2
    if args.print_commands:
        print(json.dumps({"validation": validation, "commands": {candidate: {prompt["id"]: command_for(config, candidate, prompt["text"], prompts["n_predict"]) for prompt in prompt_list} for candidate in candidate_ids}}, indent=2, ensure_ascii=False))
        return 0 if validation["valid"] else 2
    if args.dry_run:
        print(json.dumps({"validation": validation, "plan": plan, "note": "dry-run starts no model or telemetry process"}, indent=2, ensure_ascii=False))
        return 0 if validation["valid"] else 2
    if not validation["valid"]:
        print(json.dumps(validation, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2
    run_id = f"model-selection-v1-{utc_now()}-{os.getpid()}"
    run_dir = args.output_root.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    provenance = {"run_id": run_id, "project_git": validation["project_git"], "runtime_commit": validation["runtime"]["commit"], "runtime_branch": validation["runtime"]["branch"], "cli_sha256": validation["cli"]["sha256"], "model_sha256": {key: value["sha256"] for key, value in validation["assets"].items()}, "script_sha256": sha256_file(Path(__file__).resolve()), "selection_config_sha256": sha256_file(SELECTION_CONFIG), "prompts_config_sha256": sha256_file(PROMPTS_CONFIG), "manifest_sha256": sha256_file(MANIFEST)}
    (run_dir / "config.json").write_text(json.dumps({"run_id": run_id, "provenance": provenance, "validation": validation, "plan": plan, "n_predict": prompts["n_predict"]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (run_dir / "validation.json").write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    records_path, blind_path, map_path = run_dir / "runs.jsonl", run_dir / "blind-review.jsonl", run_dir / "blind-review-map.json"
    blind_map: dict[str, Any] = {}
    for candidate_id in candidate_ids:
        precondition = next(item for item in prompts["prompts"] if item["id"] == "J-09")
        for attempt in range(1, args.preconditioning_runs + 1):
            record = run_once(config, provenance, candidate_id, precondition, "preconditioning", attempt, run_dir / "candidates" / candidate_id / "preconditioning" / f"attempt-{attempt:02d}", prompts["n_predict"])
            append_jsonl(records_path, record)
            if not record["valid"]:
                print(f"preconditioning failed for {candidate_id}; stopping", file=sys.stderr)
                return 1
        for prompt in prompt_list:
            valid = 0
            for attempt in range(1, args.max_attempts + 1):
                record = run_once(config, provenance, candidate_id, prompt, "measured", attempt, run_dir / "candidates" / candidate_id / prompt["id"] / f"attempt-{attempt:02d}", prompts["n_predict"])
                if record["valid"]:
                    valid += 1
                    response_id = hashlib.sha256(f"{run_id}:{candidate_id}:{prompt['id']}:{attempt}".encode()).hexdigest()[:16]
                    blind = {"response_id": response_id, "prompt_id": prompt["id"], "response_text": record["response_text"], "response_sha256": record["response_sha256"], "scorer_a": None, "scorer_b": None, "disagreement": None, "final_score": None, "notes": None}
                    append_jsonl(blind_path, blind)
                    blind_map[response_id] = {"candidate_id": candidate_id, "prompt_id": prompt["id"], "attempt": attempt, "response_sha256": record["response_sha256"]}
                append_jsonl(records_path, record)
                if valid >= args.runs:
                    break
            if valid < args.runs:
                print(f"{candidate_id} {prompt['id']} has {valid}/{args.runs} valid runs", file=sys.stderr)
    map_path.write_text(json.dumps(blind_map, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"artifacts: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
