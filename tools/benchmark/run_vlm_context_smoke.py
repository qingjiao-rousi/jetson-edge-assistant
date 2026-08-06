#!/usr/bin/env python3
"""Reproducible, explicit-only VLM context smoke runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "evidence/milestones/configs/vlm/vlm-context-smoke-m7.4.json"
ALLOWED_CONTEXTS = (4096, 8192, 16384, 32768)
REQUIRED_RESULT_PATHS = (
    "context",
    "batch",
    "ubatch",
    "assets.binary.sha256",
    "assets.main_model.sha256",
    "assets.mmproj.sha256",
    "assets.image.sha256",
    "git.project.commit",
    "git.project.dirty",
    "git.runtime.commit",
    "git.runtime.dirty",
    "kv_cache.total_mib",
    "vision.image_grid_x",
    "vision.image_grid_y",
    "vision.image_tokens",
    "timings_ms.vision_encode",
    "timings_ms.image_embedding_decode",
    "timings_ms.prompt_eval",
    "timings_ms.decode",
    "timings_ms.cli_total",
    "timings_ms.wall_clock",
    "telemetry.peak_uma_used_mb",
    "telemetry.peak_gr3d_percent",
    "telemetry.peak_temperature_c",
    "telemetry.power_rails_mw",
    "process.exit_code",
    "process.inference_run_count",
    "process.retry_count",
    "finish_reason",
    "failure_class",
    "output.summary",
)


class SmokeError(RuntimeError):
    def __init__(self, message: str, failure_class: str = "launcher_preflight_failed") -> None:
        super().__init__(message)
        self.failure_class = failure_class


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_context(context: int, config: dict[str, Any]) -> None:
    configured = tuple(config.get("allowed_contexts", ()))
    if context not in ALLOWED_CONTEXTS or context not in configured:
        raise ValueError(f"unsupported context {context}; allowed: {ALLOWED_CONTEXTS}")


def validate_execution_context(context: int, config: dict[str, Any]) -> None:
    validate_context(context, config)
    if context not in config.get("m7_4a_execute_contexts", []):
        raise ValueError(f"context {context} is not executable in M7.4A")


def build_model_command(config: dict[str, Any], context: int, root: Path = ROOT) -> list[str]:
    validate_context(context, config)
    fixed = config["fixed_parameters"]
    assets = config["assets"]
    command = [
        str(root / config["binary"]["path"]),
        "--model", str(root / assets["main_model"]["path"]),
        "--mmproj", str(root / assets["mmproj"]["path"]),
        "--image", str(root / assets["image"]["path"]),
        "--ctx-size", str(context),
        "--batch-size", str(fixed["batch"]),
        "--ubatch-size", str(fixed["ubatch"]),
        "--gpu-layers", str(fixed["gpu_layers"]),
        "--flash-attn", str(fixed["flash_attention"]),
        "--temperature", str(fixed["temperature"]),
        "--seed", str(fixed["seed"]),
        "--predict", str(fixed["max_new_tokens"]),
        "--mmproj-offload",
        "--perf",
        "--offline",
        "--verbose",
        "--log-timestamps",
        "--log-colors", "off",
        "--no-warmup",
        "--prompt", str(fixed["prompt"]),
    ]
    rendered = shlex.join(command)
    if "/usr/bin/time" in rendered or " -hf " in f" {rendered} " or "--hf-repo" in rendered:
        raise SmokeError("forbidden command dependency or download argument", "launcher_preflight_failed")
    return command


def build_launch_command(config: dict[str, Any], model_command: list[str]) -> list[str]:
    launcher = config["launcher"]
    timeout_path = shutil.which("timeout") or "timeout"
    return [
        timeout_path,
        "--signal=TERM",
        f"--kill-after={launcher['timeout_kill_after_seconds']}s",
        f"{launcher['timeout_seconds']}s",
        *model_command,
    ]


def verify_file(root: Path, expected: dict[str, Any], role: str, executable: bool = False) -> dict[str, Any]:
    path = root / expected["path"]
    if not path.is_file():
        raise SmokeError(f"{role} missing: {path}", "launcher_preflight_failed")
    if executable and not os.access(path, os.X_OK):
        raise SmokeError(f"{role} is not executable: {path}", "launcher_preflight_failed")
    actual_size = path.stat().st_size
    if actual_size != expected["size_bytes"]:
        raise SmokeError(
            f"{role} size mismatch: expected {expected['size_bytes']}, got {actual_size}",
            "asset_hash_mismatch",
        )
    actual_sha = sha256_file(path)
    if actual_sha != expected["sha256"]:
        raise SmokeError(
            f"{role} sha256 mismatch: expected {expected['sha256']}, got {actual_sha}",
            "asset_hash_mismatch",
        )
    return {
        "path": str(path.relative_to(root)),
        "size_bytes": actual_size,
        "sha256": actual_sha,
        "verification_status": "VERIFIED",
    }


def git_identity(path: Path) -> dict[str, Any]:
    def query(*args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True, check=False
        )
        if completed.returncode:
            raise SmokeError(completed.stderr.strip() or "git identity failed")
        return completed.stdout.strip()

    return {
        "path": str(path),
        "commit": query("rev-parse", "HEAD"),
        "branch": query("branch", "--show-current") or None,
        "dirty": bool(query("status", "--porcelain", "--untracked-files=all")),
    }


def run_preflight(config: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    dependencies: dict[str, str] = {}
    for name in ("date", "timeout", "tegrastats", "ldd"):
        path = shutil.which(name)
        if path is None:
            raise SmokeError(f"launcher dependency missing: {name}", "launcher_dependency_missing")
        dependencies[name] = path

    binary = verify_file(root, config["binary"], "binary", executable=True)
    assets = {
        role: verify_file(root, expected, role)
        for role, expected in config["assets"].items()
    }
    ldd = subprocess.run(
        [dependencies["ldd"], str(root / config["binary"]["path"])],
        capture_output=True,
        text=True,
        check=False,
    )
    if ldd.returncode or "not found" in f"{ldd.stdout}\n{ldd.stderr}".lower():
        raise SmokeError("binary has unresolved dynamic dependencies", "launcher_dependency_missing")

    project = git_identity(root)
    runtime_path = root / config["runtime"]["path"]
    runtime = git_identity(runtime_path)
    if runtime["commit"] != config["runtime"]["commit"]:
        raise SmokeError(
            f"runtime commit mismatch: expected {config['runtime']['commit']}, got {runtime['commit']}",
            "launcher_preflight_failed",
        )
    if runtime["dirty"]:
        raise SmokeError("runtime worktree is dirty", "launcher_preflight_failed")

    return {
        "status": "PASSED",
        "dependencies": dependencies,
        "assets": {"binary": binary, **assets},
        "git": {"project": project, "runtime": runtime},
        "ldd_not_found_count": 0,
        "automatic_download": False,
        "usr_bin_time_used": False,
    }


def read_date_ns(date_path: str) -> int:
    completed = subprocess.run([date_path, "+%s%N"], capture_output=True, text=True, check=True)
    return int(completed.stdout.strip())


def parse_kv_cache(stderr: str) -> dict[str, Any]:
    pattern = re.compile(
        r"llama_kv_cache: size =\s*([0-9.]+) MiB \(\s*(\d+) cells,\s*(\d+) layers.*?"
        r"K \(([^)]+)\):\s*([0-9.]+) MiB, V \(([^)]+)\):\s*([0-9.]+) MiB"
    )
    matches = list(pattern.finditer(stderr))
    if not matches:
        return {
            "total_mib": None,
            "cells": None,
            "layers": None,
            "k_type": None,
            "k_mib": None,
            "v_type": None,
            "v_mib": None,
            "measurement_status": "NOT_EMITTED_BY_CLI",
        }
    match = matches[-1]
    return {
        "total_mib": float(match.group(1)),
        "cells": int(match.group(2)),
        "layers": int(match.group(3)),
        "k_type": match.group(4),
        "k_mib": float(match.group(5)),
        "v_type": match.group(6),
        "v_mib": float(match.group(7)),
        "measurement_status": "DIRECTLY_PARSED_FROM_CLI_LOG",
        "raw_line": match.group(0),
    }


def parse_runtime_log(stderr: str) -> dict[str, Any]:
    def last_float(pattern: str) -> float | None:
        matches = re.findall(pattern, stderr, flags=re.IGNORECASE)
        return float(matches[-1]) if matches else None

    def last_int(pattern: str) -> int | None:
        matches = re.findall(pattern, stderr, flags=re.IGNORECASE)
        return int(matches[-1]) if matches else None

    grid_x = last_int(r"image_tokens->nx\s*=\s*(\d+)")
    grid_y = last_int(r"image_tokens->ny\s*=\s*(\d+)")
    image_batches = [int(value) for value in re.findall(r"decoding image batch \d+/\d+, n_tokens_batch = (\d+)", stderr)]
    prompt_match = re.findall(r"prompt eval time =\s*([0-9.]+) ms /\s*(\d+) tokens", stderr)
    decode_match = re.findall(r"(?<!prompt )eval time =\s*([0-9.]+) ms /\s*(\d+) runs", stderr)
    total_match = re.findall(r"total time =\s*([0-9.]+) ms /\s*(\d+) tokens", stderr)
    offload_match = re.findall(r"offloaded\s+(\d+)/(\d+) layers to GPU", stderr)
    mmproj_match = re.findall(r"loaded\s+(\d+) tensors from .*mmproj[^\n]*", stderr)
    actual_context = last_int(r"llama_context: n_ctx\s*=\s*(\d+)")
    actual_batch = last_int(r"llama_context: n_batch\s*=\s*(\d+)")
    actual_ubatch = last_int(r"llama_context: n_ubatch\s*=\s*(\d+)")
    return {
        "actual_context": actual_context,
        "actual_batch": actual_batch,
        "actual_ubatch": actual_ubatch,
        "kv_cache": parse_kv_cache(stderr),
        "main_model_loaded": bool(offload_match),
        "offloaded_layers": f"{offload_match[-1][0]}/{offload_match[-1][1]}" if offload_match else None,
        "mmproj_loaded": bool(mmproj_match),
        "mmproj_tensor_count": int(mmproj_match[-1]) if mmproj_match else None,
        "mmproj_cuda": "clip_ctx: CLIP using CUDA0 backend" in stderr,
        "flash_attention": "flash_attn    = enabled" in stderr,
        "cuda_evidence": bool(re.search(r"using device CUDA0|assigned to device CUDA0|CUDA Graph", stderr)),
        "vision": {
            "image_decode_succeeded": grid_x is not None and grid_y is not None,
            "vision_preprocess_succeeded": grid_x is not None and grid_y is not None,
            "vision_encode_succeeded": "image slice encoded in" in stderr,
            "embedding_injection_succeeded": "image decoded (batch" in stderr,
            "image_grid_x": grid_x,
            "image_grid_y": grid_y,
            "image_tokens": sum(image_batches) if image_batches else None,
            "image_tokens_measurement_status": "DIRECTLY_PARSED_FROM_CLI_LOG" if image_batches else "NOT_EMITTED_BY_CLI",
            "image_positions": None,
            "image_positions_measurement_status": "NOT_EMITTED_BY_CLI_NO_ESTIMATE",
        },
        "tokens": {
            "prompt_tokens": int(prompt_match[-1][1]) if prompt_match else None,
            "output_tokens": int(decode_match[-1][1]) if decode_match else None,
            "output_tokens_measurement_status": "LLAMA_PERF_EVAL_RUN_COUNT" if decode_match else "NOT_EMITTED_BY_CLI",
        },
        "timings_ms": {
            "vision_preprocess": None,
            "vision_preprocess_measurement_status": "NOT_EMITTED_BY_CLI_NO_ESTIMATE",
            "vision_encode": last_float(r"image slice encoded in\s*(\d+) ms"),
            "image_embedding_decode": last_float(r"image decoded \(batch \d+/\d+\) in\s*(\d+) ms"),
            "prompt_eval": float(prompt_match[-1][0]) if prompt_match else None,
            "decode": float(decode_match[-1][0]) if decode_match else None,
            "cli_total": float(total_match[-1][0]) if total_match else None,
        },
    }


def parse_telemetry(path: Path) -> dict[str, Any]:
    values: dict[str, list[float]] = {
        "uma_used": [],
        "uma_total": [],
        "gr3d": [],
        "temperature": [],
    }
    sensor_temps: dict[str, list[float]] = {}
    rails: dict[str, list[int]] = {}
    sample_count = 0
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            ram = re.search(r"\bRAM\s+(\d+)/(\d+)MB", line)
            if ram:
                sample_count += 1
                values["uma_used"].append(float(ram.group(1)))
                values["uma_total"].append(float(ram.group(2)))
            if gr3d := re.search(r"\bGR3D_FREQ\s+(\d+)%", line):
                values["gr3d"].append(float(gr3d.group(1)))
            for name, raw in re.findall(r"\b([A-Za-z0-9_]+)@([0-9]+(?:\.[0-9]+)?)C", line):
                temperature = float(raw)
                values["temperature"].append(temperature)
                sensor_temps.setdefault(name, []).append(temperature)
            for name, raw in re.findall(r"\b([A-Z][A-Z0-9_]+)\s+(\d+)mW(?:/\d+mW)?", line):
                rails.setdefault(name, []).append(int(raw))
    return {
        "sample_count": sample_count,
        "peak_uma_used_mb": int(max(values["uma_used"])) if values["uma_used"] else None,
        "uma_total_mb": int(max(values["uma_total"])) if values["uma_total"] else None,
        "peak_gr3d_percent": int(max(values["gr3d"])) if values["gr3d"] else None,
        "peak_temperature_c": max(values["temperature"]) if values["temperature"] else None,
        "temperature_sensors_c": {key: max(items) for key, items in sorted(sensor_temps.items())},
        "power_rails_mw": {key: max(items) for key, items in sorted(rails.items())},
        "measurement_status": "DIRECTLY_PARSED_FROM_TEGRASTATS" if sample_count else "NO_VALID_SAMPLE",
    }


def classify_failure(exit_code: int, stderr: str, stdout: str, telemetry_valid: bool = True) -> str | None:
    combined = f"{stderr}\n{stdout}".lower()
    if exit_code in (124, 137):
        return "timeout"
    if "out of memory" in combined or re.search(r"\boom\b", combined) or "allocation failed" in combined:
        return "oom_or_allocation_failed"
    if "context overflow" in combined or "exceeds context" in combined or "failed to find a memory slot" in combined:
        return "context_limit"
    if "failed to load vision model" in combined or "mmproj" in combined and "failed" in combined:
        return "mmproj_load_failed"
    if "failed to load model" in combined or "error loading model" in combined:
        return "model_load_failed"
    if "unable to load image" in combined or "failed to load image" in combined or "image decode failed" in combined:
        return "image_decode_failed"
    if "failed to encode image" in combined or "unable to preprocess image" in combined:
        return "vision_encode_failed"
    if "cuda error" in combined or "ggml_cuda" in combined and "failed" in combined:
        return "cuda_error"
    if "failed to decode token" in combined or "unable to eval prompt" in combined or "failed to decode text" in combined:
        return "decode_failed"
    if not telemetry_valid:
        return "telemetry_missing"
    if exit_code != 0:
        return "internal"
    return None


def summarize_output(stdout: str) -> str | None:
    compact = " ".join(stdout.split())
    return compact[:500] if compact else None


def finish_reason(exit_code: int, output_tokens: int | None, max_new_tokens: int) -> tuple[str, str]:
    if exit_code in (124, 137):
        return "timeout", "DIRECTLY_FROM_TIMEOUT_EXIT_CODE"
    if exit_code != 0:
        return "error", "DIRECTLY_FROM_NONZERO_EXIT_CODE"
    if output_tokens is not None and output_tokens >= max_new_tokens:
        return "length", "DERIVED_FROM_LLAMA_PERF_EVAL_RUN_COUNT"
    return "eog", "CLI_DID_NOT_EMIT_EXPLICIT_REASON; SUCCESS_BELOW_MAX_WITHOUT_TIMEOUT"


def initial_result(context: int, config: dict[str, Any]) -> dict[str, Any]:
    fixed = config["fixed_parameters"]
    return {
        "schema_version": 1,
        "milestone": "M7.4A",
        "status": "PENDING",
        "success_gate_passed": False,
        "context": context,
        "batch": fixed["batch"],
        "ubatch": fixed["ubatch"],
        "assets": {
            "binary": {"sha256": None},
            "main_model": {"sha256": None},
            "mmproj": {"sha256": None},
            "image": {"sha256": None},
        },
        "git": {
            "project": {"commit": None, "dirty": None},
            "runtime": {"commit": None, "dirty": None},
        },
        "kv_cache": {"total_mib": None},
        "vision": {"image_grid_x": None, "image_grid_y": None, "image_tokens": None},
        "timings_ms": {
            "vision_encode": None,
            "image_embedding_decode": None,
            "prompt_eval": None,
            "decode": None,
            "cli_total": None,
            "wall_clock": None,
        },
        "telemetry": {
            "peak_uma_used_mb": None,
            "peak_gr3d_percent": None,
            "peak_temperature_c": None,
            "power_rails_mw": {},
        },
        "process": {"exit_code": None, "inference_run_count": 0, "retry_count": 0},
        "finish_reason": None,
        "failure_class": None,
        "output": {"summary": None},
    }


def missing_required_result_fields(result: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for dotted in REQUIRED_RESULT_PATHS:
        current: Any = result
        for part in dotted.split("."):
            if not isinstance(current, dict) or part not in current:
                missing.append(dotted)
                break
            current = current[part]
    return missing


def wait_for_telemetry(process: subprocess.Popen[Any], path: Path) -> bool:
    for _ in range(40):
        if process.poll() is not None:
            return False
        if path.is_file() and path.stat().st_size > 0:
            return True
        time.sleep(0.05)
    return False


def execute_run(args: argparse.Namespace, config: dict[str, Any], root: Path = ROOT) -> int:
    validate_execution_context(args.context, config)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f%z")
    output_root = Path(args.output_root) if args.output_root else root / config["launcher"]["output_root"]
    run_dir = output_root / timestamp
    run_dir.mkdir(parents=True, exist_ok=False)

    result = initial_result(args.context, config)
    result["timestamp_directory"] = timestamp
    result["result_directory"] = str(run_dir.relative_to(root)) if run_dir.is_relative_to(root) else str(run_dir)
    model_command = build_model_command(config, args.context, root)
    launch_command = build_launch_command(config, model_command)
    (run_dir / "command.txt").write_text(shlex.join(launch_command) + "\n", encoding="utf-8")
    write_json(run_dir / "config.snapshot.json", config)

    try:
        preflight = run_preflight(config, root)
    except SmokeError as error:
        result.update({
            "status": "FAILED",
            "failure_class": error.failure_class,
            "finish_reason": "launcher_preflight_failed",
            "failure_detail": str(error),
        })
        write_json(run_dir / "launcher-preflight.json", {
            "status": "FAILED", "failure_class": error.failure_class, "detail": str(error)
        })
        write_json(run_dir / "result.json", result)
        print(json.dumps({"status": "FAILED", "result_directory": str(run_dir), "failure_class": error.failure_class}))
        return 2

    write_json(run_dir / "launcher-preflight.json", preflight)
    result["assets"] = preflight["assets"]
    result["git"] = preflight["git"]
    result["command"] = {
        "argv": launch_command,
        "model_argv": model_command,
        "offline": True,
        "warmup": False,
        "timeout_seconds": config["launcher"]["timeout_seconds"],
    }

    telemetry_path = run_dir / "tegrastats.log"
    telemetry_stdout = (run_dir / "tegrastats.stdout.log").open("w", encoding="utf-8")
    telemetry_stderr = (run_dir / "tegrastats.stderr.log").open("w", encoding="utf-8")
    telemetry_process: subprocess.Popen[Any] | None = None
    try:
        telemetry_process = subprocess.Popen(
            [
                preflight["dependencies"]["tegrastats"],
                "--interval", str(config["launcher"]["telemetry_interval_ms"]),
                "--logfile", str(telemetry_path),
            ],
            cwd=root,
            stdout=telemetry_stdout,
            stderr=telemetry_stderr,
            text=True,
        )
        if not wait_for_telemetry(telemetry_process, telemetry_path):
            raise SmokeError("tegrastats did not produce a writable sample", "launcher_preflight_failed")
    except (OSError, SmokeError) as error:
        if telemetry_process is not None and telemetry_process.poll() is None:
            telemetry_process.terminate()
            telemetry_process.wait(timeout=5)
        telemetry_stdout.close()
        telemetry_stderr.close()
        result.update({
            "status": "FAILED",
            "failure_class": getattr(error, "failure_class", "launcher_preflight_failed"),
            "finish_reason": "launcher_preflight_failed",
            "failure_detail": str(error),
        })
        write_json(run_dir / "result.json", result)
        return 2

    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    start_iso = datetime.now().astimezone().isoformat()
    start_ns = read_date_ns(preflight["dependencies"]["date"])
    result["process"].update({"llama_mtmd_cli_invoked": True, "inference_run_count": 1, "retry_count": 0})
    write_json(run_dir / "invocation-status.json", result["process"])
    with stdout_path.open("w", encoding="utf-8") as stdout_stream, stderr_path.open("w", encoding="utf-8") as stderr_stream:
        completed = subprocess.run(
            launch_command,
            cwd=root,
            stdout=stdout_stream,
            stderr=stderr_stream,
            text=True,
            check=False,
        )
    end_ns = read_date_ns(preflight["dependencies"]["date"])
    end_iso = datetime.now().astimezone().isoformat()
    elapsed_ms = (end_ns - start_ns) // 1_000_000

    if telemetry_process.poll() is None:
        telemetry_process.terminate()
        try:
            telemetry_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            telemetry_process.kill()
            telemetry_process.wait(timeout=5)
    telemetry_stdout.close()
    telemetry_stderr.close()

    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    parsed = parse_runtime_log(stderr)
    telemetry = parse_telemetry(telemetry_path)
    failure = classify_failure(completed.returncode, stderr, stdout, telemetry["sample_count"] > 0)
    finish, finish_status = finish_reason(
        completed.returncode, parsed["tokens"]["output_tokens"], config["fixed_parameters"]["max_new_tokens"]
    )
    output_summary = summarize_output(stdout)
    no_errors = failure is None
    success_criteria = {
        "actual_context_matches": parsed["actual_context"] == args.context,
        "actual_batch_matches": parsed["actual_batch"] == config["fixed_parameters"]["batch"],
        "actual_ubatch_matches": parsed["actual_ubatch"] == config["fixed_parameters"]["ubatch"],
        "main_model_loaded": parsed["main_model_loaded"],
        "mmproj_loaded": parsed["mmproj_loaded"],
        "cuda_offload_37_of_37": parsed["offloaded_layers"] == "37/37",
        "image_decoded": parsed["vision"]["image_decode_succeeded"],
        "vision_encoded": parsed["vision"]["vision_encode_succeeded"],
        "embedding_injected": parsed["vision"]["embedding_injection_succeeded"],
        "cuda_path_logged": parsed["cuda_evidence"] and parsed["mmproj_cuda"],
        "output_nonempty": output_summary is not None,
        "telemetry_sample_present": telemetry["sample_count"] > 0,
        "no_disqualifying_error": no_errors,
    }
    success = completed.returncode == 0 and all(success_criteria.values())
    if completed.returncode == 0 and not success and failure is None:
        failure = "internal"

    result.update({
        "status": "SUCCESS" if success else "FAILED",
        "success_gate_passed": success,
        "failure_class": None if success else failure,
        "failure_detail": None if success else "one or more success gates failed; inspect stderr.log",
        "actual_runtime": {
            "context": parsed["actual_context"],
            "batch": parsed["actual_batch"],
            "ubatch": parsed["actual_ubatch"],
            "offloaded_layers": parsed["offloaded_layers"],
            "mmproj_tensor_count": parsed["mmproj_tensor_count"],
            "mmproj_cuda": parsed["mmproj_cuda"],
            "flash_attention": "enabled" if parsed["flash_attention"] else None,
        },
        "kv_cache": parsed["kv_cache"],
        "vision": parsed["vision"],
        "tokens": parsed["tokens"],
        "timings_ms": {**parsed["timings_ms"], "wall_clock": elapsed_ms, "wall_clock_measurement": "date +%s%N"},
        "telemetry": telemetry,
        "process": {
            "start": start_iso,
            "end": end_iso,
            "start_ns": start_ns,
            "end_ns": end_ns,
            "elapsed_ms": elapsed_ms,
            "exit_code": completed.returncode,
            "timed_out": completed.returncode in (124, 137),
            "llama_mtmd_cli_invoked": True,
            "inference_run_count": 1,
            "retry_count": 0,
        },
        "finish_reason": finish,
        "finish_reason_measurement_status": finish_status,
        "output": {
            "nonempty": output_summary is not None,
            "size_bytes": stdout_path.stat().st_size,
            "sha256": sha256_file(stdout_path),
            "summary": output_summary,
        },
        "success_criteria": success_criteria,
        "artifacts": {
            "command": "command.txt",
            "launcher_preflight": "launcher-preflight.json",
            "stdout": "stdout.log",
            "stderr": "stderr.log",
            "telemetry": "tegrastats.log",
            "result": "result.json",
        },
        "scope": "SINGLE_8192_CONTEXT_SMOKE_NOT_STABILITY_OR_DEPLOYMENT_EVIDENCE",
    })
    missing = missing_required_result_fields(result)
    if missing:
        result["status"] = "FAILED"
        result["success_gate_passed"] = False
        result["failure_class"] = "internal"
        result["failure_detail"] = f"result schema missing fields: {missing}"
    write_json(run_dir / "result.json", result)
    (run_dir / "process-status.txt").write_text(
        f"start={start_iso}\nend={end_iso}\nelapsed_ms={elapsed_ms}\nexit_code={completed.returncode}\n"
        "llama_mtmd_cli_invoked=true\ninference_run_count=1\nretry_count=0\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result["status"],
        "result_directory": str(run_dir),
        "exit_code": completed.returncode,
        "failure_class": result["failure_class"],
    }))
    return 0 if result["status"] == "SUCCESS" else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--context", type=int, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the plan without running preflight or subprocesses")
    mode.add_argument("--execute", action="store_true", help="run the model once after all preflight gates pass")
    parser.add_argument("--output-root", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = read_json(args.config)
    validate_context(args.context, config)
    model_command = build_model_command(config, args.context)
    plan = {
        "mode": "execute" if args.execute else "dry-run",
        "execute_requested": args.execute,
        "model_process_started": False,
        "context": args.context,
        "model_command": model_command,
        "launch_command": build_launch_command(config, model_command),
        "preflight_performed": False,
        "automatic_download": False,
        "retry_count": 0,
    }
    if not args.execute:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    validate_execution_context(args.context, config)
    return execute_run(args, config)


if __name__ == "__main__":
    sys.exit(main())
