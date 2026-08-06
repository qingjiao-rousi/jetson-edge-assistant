#!/usr/bin/env python3
"""Reproducible Qwen2.5 llama-cli benchmark for the stage-one Jetson baseline."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = Path(__file__).resolve()
RUNTIME_DIR = PROJECT_ROOT / "third_party/llama.cpp-omni"
BINARY = RUNTIME_DIR / "build-jetson-release/bin/llama-cli"
BUILD_CACHE = RUNTIME_DIR / "build-jetson-release/CMakeCache.txt"
COMPILE_COMMANDS = RUNTIME_DIR / "build-jetson-release/compile_commands.json"
BUILD_MANIFEST = PROJECT_ROOT / "manifests/build.json"
MODEL = PROJECT_ROOT / "models/qwen2.5-3b-instruct-q4_k_m.gguf"
EXPECTED_RUNTIME_COMMIT = "19cc26967140407efe34006a355ab445b35b16ac"
EXPECTED_RUNTIME_BRANCH = "jetson-runtime-dev"
EXPECTED_MODEL_SHA256 = "626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d"

PROMPT = (
    "You are an industrial maintenance assistant. Give exactly five concise, "
    "actionable checks a technician should perform before diagnosing an "
    "overheating electric motor. Use a numbered list and no preamble."
)

FIXED_CONFIG: dict[str, Any] = {
    "benchmark": "qwen2.5-3b-instruct-q4_k_m-jetson-cuda",
    "prompt": PROMPT,
    "context_size": 4096,
    "batch_size": 2048,
    "ubatch_size": 512,
    "gpu_layers": 99,
    "device": "CUDA0",
    "split_mode": "none",
    "threads": 8,
    "output_tokens_max": 128,
    "seed": 424242,
    "sampling": {
        "temperature": 0.0,
        "top_k": 1,
        "top_p": 1.0,
        "min_p": 0.0,
        "repeat_penalty": 1.0,
    },
    "flash_attention": "on",
    "mmap": True,
    "fit": "off",
    "tegrastats_interval_ms": 1000,
    "runtime_same_process_warmup": False,
    "preconditioning_semantics": (
        "A separate llama-cli process executed before measured runs; it can precondition "
        "filesystem caches, CUDA state, and device clocks, but not the measured process."
    ),
    "build_requirements": {
        "cuda_architecture": "87",
        "nccl": False,
    },
}

PROMPT_TIMING_RE = re.compile(
    r"prompt eval time\s*=\s*([0-9.]+) ms\s*/\s*([0-9]+) tokens.*?"
    r"([0-9.]+) tokens per second"
)
DECODE_TIMING_RE = re.compile(
    r"eval time\s*=\s*([0-9.]+) ms\s*/\s*([0-9]+) (?:tokens|runs).*?"
    r"([0-9.]+) tokens per second"
)
TOTAL_TIMING_RE = re.compile(r"total time\s*=\s*([0-9.]+) ms")
GPU_OFFLOAD_RE = re.compile(r"offloaded\s+([0-9]+)/([0-9]+) layers to GPU")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def command_environment() -> dict[str, str]:
    env = os.environ.copy()
    binary_dir = str(BINARY.parent)
    current = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = binary_dir if not current else f"{binary_dir}:{current}"
    return env


def benchmark_command() -> list[str]:
    sampling = FIXED_CONFIG["sampling"]
    return [
        str(BINARY),
        "--model",
        str(MODEL),
        "--prompt",
        PROMPT,
        "--ctx-size",
        str(FIXED_CONFIG["context_size"]),
        "--batch-size",
        str(FIXED_CONFIG["batch_size"]),
        "--ubatch-size",
        str(FIXED_CONFIG["ubatch_size"]),
        "--gpu-layers",
        str(FIXED_CONFIG["gpu_layers"]),
        "--device",
        str(FIXED_CONFIG["device"]),
        "--split-mode",
        str(FIXED_CONFIG["split_mode"]),
        "--main-gpu",
        "0",
        "--threads",
        str(FIXED_CONFIG["threads"]),
        "--threads-batch",
        str(FIXED_CONFIG["threads"]),
        "--n-predict",
        str(FIXED_CONFIG["output_tokens_max"]),
        "--seed",
        str(FIXED_CONFIG["seed"]),
        "--temp",
        str(sampling["temperature"]),
        "--top-k",
        str(sampling["top_k"]),
        "--top-p",
        str(sampling["top_p"]),
        "--min-p",
        str(sampling["min_p"]),
        "--repeat-penalty",
        str(sampling["repeat_penalty"]),
        "--flash-attn",
        str(FIXED_CONFIG["flash_attention"]),
        "--fit",
        str(FIXED_CONFIG["fit"]),
        "--mmap",
        "--conversation",
        "--single-turn",
        "--simple-io",
        "--no-display-prompt",
        "--no-warmup",
        "--show-timings",
        "--verbose",
    ]


def run_runtime_git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(RUNTIME_DIR), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def project_git_identity() -> dict[str, Any]:
    commit_process = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--verify", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    branch_process = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "symbolic-ref", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    status_process = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "status", "--porcelain", "--untracked-files=all"],
        check=False,
        capture_output=True,
        text=True,
    )
    commit = commit_process.stdout.strip() if commit_process.returncode == 0 else None
    return {
        "commit": commit,
        "state": "committed" if commit is not None else "unborn",
        "branch": branch_process.stdout.strip() if branch_process.returncode == 0 else None,
        "dirty": bool(status_process.stdout.strip()),
    }


def validate_prerequisites(check_version: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    project_git = project_git_identity()
    details: dict[str, Any] = {
        "project_git": project_git,
        "project_git_commit": project_git["commit"],
        "project_git_state": project_git["state"],
        "benchmark_script_sha256": sha256_file(SCRIPT_PATH),
        "runtime_branch": run_runtime_git("branch", "--show-current"),
        "runtime_commit": run_runtime_git("rev-parse", "HEAD"),
        "binary": str(BINARY.relative_to(PROJECT_ROOT)),
        "model": str(MODEL.relative_to(PROJECT_ROOT)),
        "tegrastats": shutil.which("tegrastats"),
    }

    if details["runtime_branch"] != EXPECTED_RUNTIME_BRANCH:
        errors.append(
            f"runtime branch is {details['runtime_branch']!r}, expected {EXPECTED_RUNTIME_BRANCH!r}"
        )
    if details["runtime_commit"] != EXPECTED_RUNTIME_COMMIT:
        errors.append(
            f"runtime commit is {details['runtime_commit']!r}, expected {EXPECTED_RUNTIME_COMMIT!r}"
        )
    if not BINARY.is_file() or not os.access(BINARY, os.X_OK):
        errors.append(f"llama-cli is missing or not executable: {BINARY}")
    if not MODEL.is_file():
        errors.append(f"model is missing: {MODEL}")
    else:
        details["model_size_bytes"] = MODEL.stat().st_size
        details["model_sha256"] = sha256_file(MODEL)
        if details["model_sha256"] != EXPECTED_MODEL_SHA256:
            errors.append("model SHA-256 does not match manifests/model.json")
    if details["tegrastats"] is None:
        errors.append("tegrastats is not available on PATH")
    if project_git["commit"] is None:
        warnings.append(
            "main project has no commit yet; validation is allowed, but a formal benchmark is not"
        )

    if not BUILD_CACHE.is_file():
        errors.append(f"CMake cache is missing: {BUILD_CACHE}")
    else:
        cache_text = BUILD_CACHE.read_text(encoding="utf-8", errors="replace")
        details["cmake_cuda_architectures_87"] = bool(
            re.search(r"^CMAKE_CUDA_ARCHITECTURES:[^=]+=87$", cache_text, re.MULTILINE)
        )
        details["cmake_cuda_nccl_off"] = "GGML_CUDA_NCCL:BOOL=OFF" in cache_text
        if not details["cmake_cuda_architectures_87"]:
            errors.append("CMake cache does not fix CMAKE_CUDA_ARCHITECTURES=87")
        if not details["cmake_cuda_nccl_off"]:
            errors.append("CMake cache does not fix GGML_CUDA_NCCL=OFF")

    if not COMPILE_COMMANDS.is_file():
        errors.append(f"compile_commands.json is missing: {COMPILE_COMMANDS}")
    else:
        commands_text = COMPILE_COMMANDS.read_text(encoding="utf-8", errors="replace")
        details["nvcc_sm_87"] = "arch=compute_87,code=[compute_87,sm_87]" in commands_text
        if not details["nvcc_sm_87"]:
            errors.append("actual nvcc commands do not contain compute_87/sm_87")

    if not BUILD_MANIFEST.is_file():
        errors.append(f"build manifest is missing: {BUILD_MANIFEST}")
    elif BINARY.is_file():
        manifest = json.loads(BUILD_MANIFEST.read_text(encoding="utf-8"))
        expected_binary_sha256 = manifest.get("binary", {}).get("sha256")
        details["binary_sha256"] = sha256_file(BINARY)
        details["build_manifest_binary_sha256"] = expected_binary_sha256
        if details["binary_sha256"] != expected_binary_sha256:
            errors.append("llama-cli SHA-256 does not match manifests/build.json")

    if check_version and BINARY.is_file() and os.access(BINARY, os.X_OK):
        completed = subprocess.run(
            [str(BINARY), "--version"],
            check=False,
            capture_output=True,
            text=True,
            env=command_environment(),
        )
        combined = f"{completed.stdout}\n{completed.stderr}"
        version_lines = [line.strip() for line in combined.splitlines() if "version:" in line]
        details["binary_version"] = version_lines[-1] if version_lines else ""
        details["binary_version_exit_code"] = completed.returncode
        if completed.returncode != 0 or "19cc269" not in combined:
            errors.append("llama-cli --version did not confirm runtime commit 19cc269")

    details["valid"] = not errors
    details["errors"] = errors
    details["warnings"] = warnings
    return details


def parse_runtime_metrics(stderr_text: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "runtime_prompt_eval_ms": None,
        "runtime_prompt_tokens": None,
        "runtime_prompt_tokens_per_second": None,
        "runtime_decode_eval_ms": None,
        "runtime_decode_tokens": None,
        "runtime_decode_tokens_per_second": None,
        "runtime_total_ms": None,
        "gpu_offloaded_layers": None,
        "gpu_total_layers": None,
    }
    for line in stderr_text.splitlines():
        prompt_match = PROMPT_TIMING_RE.search(line)
        if prompt_match:
            metrics["runtime_prompt_eval_ms"] = float(prompt_match.group(1))
            metrics["runtime_prompt_tokens"] = int(prompt_match.group(2))
            metrics["runtime_prompt_tokens_per_second"] = float(prompt_match.group(3))
            continue

        if "prompt eval time" not in line:
            decode_match = DECODE_TIMING_RE.search(line)
            if decode_match:
                metrics["runtime_decode_eval_ms"] = float(decode_match.group(1))
                metrics["runtime_decode_tokens"] = int(decode_match.group(2))
                metrics["runtime_decode_tokens_per_second"] = float(decode_match.group(3))

        total_match = TOTAL_TIMING_RE.search(line)
        if total_match:
            metrics["runtime_total_ms"] = float(total_match.group(1))

        offload_match = GPU_OFFLOAD_RE.search(line)
        if offload_match:
            metrics["gpu_offloaded_layers"] = int(offload_match.group(1))
            metrics["gpu_total_layers"] = int(offload_match.group(2))
    return metrics


def stop_tegrastats(
    process: subprocess.Popen[str] | None,
    stream: Any,
    ended_at: str,
) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    stream.write(f"# ended_at_utc={ended_at}\n")
    stream.flush()
    stream.close()


def run_once(
    phase: str,
    iteration: int,
    benchmark_run_id: str,
    run_directory: Path,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    run_id = f"{benchmark_run_id}-{phase}-{iteration:02d}"
    stdout_path = run_directory / f"{run_id}.stdout.log"
    stderr_path = run_directory / f"{run_id}.stderr.log"
    tegrastats_path = run_directory / f"{run_id}.tegrastats.log"
    started_at = utc_now()
    command = benchmark_command()
    exit_code = 125
    telemetry_error: str | None = None
    process: subprocess.Popen[str] | None = None

    telemetry_stream = tegrastats_path.open("w", encoding="utf-8")
    telemetry_stream.write(f"# run_id={run_id} started_at_utc={started_at}\n")
    telemetry_stream.flush()
    try:
        process = subprocess.Popen(
            [
                str(shutil.which("tegrastats")),
                "--interval",
                str(FIXED_CONFIG["tegrastats_interval_ms"]),
            ],
            stdout=telemetry_stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(0.2)
        if process.poll() is not None:
            telemetry_error = f"tegrastats exited before benchmark with code {process.returncode}"
    except OSError as exc:
        telemetry_error = f"failed to start tegrastats: {exc}"

    started_ns = time.monotonic_ns()
    if telemetry_error is None:
        with stdout_path.open("w", encoding="utf-8") as stdout_stream, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr_stream:
            completed = subprocess.run(
                command,
                check=False,
                stdout=stdout_stream,
                stderr=stderr_stream,
                text=True,
                env=command_environment(),
            )
            exit_code = completed.returncode
    else:
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(f"{telemetry_error}\n", encoding="utf-8")
    wall_time_ms = round((time.monotonic_ns() - started_ns) / 1_000_000, 3)
    ended_at = utc_now()
    stop_tegrastats(process, telemetry_stream, ended_at)

    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    metrics = parse_runtime_metrics(stderr_text)
    full_gpu_offload = (
        metrics["gpu_total_layers"] is not None
        and metrics["gpu_total_layers"] > 0
        and metrics["gpu_offloaded_layers"] == metrics["gpu_total_layers"]
    )
    metrics_present = all(
        metrics[key] is not None
        for key in (
            "runtime_prompt_eval_ms",
            "runtime_prompt_tokens_per_second",
            "runtime_decode_eval_ms",
            "runtime_decode_tokens_per_second",
        )
    )
    success = exit_code == 0 and telemetry_error is None and metrics_present and full_gpu_offload

    record: dict[str, Any] = {
        "schema_version": 1,
        "benchmark_run_id": benchmark_run_id,
        "run_id": run_id,
        "phase": phase,
        "run_semantics": (
            "external_preconditioning_process"
            if phase == "preconditioning"
            else "independent_measured_process"
        ),
        "iteration": iteration,
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "success": success,
        "exit_code": exit_code,
        "wall_time_ms": wall_time_ms,
        "telemetry_error": telemetry_error,
        "project_git_commit": provenance["project_git"]["commit"],
        "project_git_state": provenance["project_git"]["state"],
        "project_git_dirty": provenance["project_git"]["dirty"],
        "benchmark_script_sha256": provenance["benchmark_script_sha256"],
        "runtime_same_process_warmup": False,
        "command": command,
        "artifacts": {
            "stdout_log": str(stdout_path.relative_to(PROJECT_ROOT)),
            "stderr_log": str(stderr_path.relative_to(PROJECT_ROOT)),
            "tegrastats_log": str(tegrastats_path.relative_to(PROJECT_ROOT)),
        },
    }
    record.update(metrics)
    return record


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


CSV_FIELDS = [
    "run_id",
    "phase",
    "run_semantics",
    "iteration",
    "valid_run_index",
    "success",
    "exit_code",
    "project_git_commit",
    "project_git_state",
    "project_git_dirty",
    "benchmark_script_sha256",
    "runtime_same_process_warmup",
    "started_at_utc",
    "ended_at_utc",
    "wall_time_ms",
    "runtime_prompt_eval_ms",
    "runtime_prompt_tokens",
    "runtime_prompt_tokens_per_second",
    "runtime_decode_eval_ms",
    "runtime_decode_tokens",
    "runtime_decode_tokens_per_second",
    "runtime_total_ms",
    "gpu_offloaded_layers",
    "gpu_total_layers",
    "stdout_log",
    "stderr_log",
    "tegrastats_log",
]


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in records:
            row = {field: record.get(field) for field in CSV_FIELDS}
            row.update(record["artifacts"])
            writer.writerow(row)


def metric_summary(records: list[dict[str, Any]], key: str) -> dict[str, float] | None:
    values = [float(record[key]) for record in records if record.get(key) is not None]
    if not values:
        return None
    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, int(round(0.95 * len(ordered) + 0.5)) - 1))
    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 6),
        "median": round(statistics.median(values), 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "p95_nearest_rank": round(ordered[p95_index], 6),
    }


def write_aggregate(
    path: Path,
    benchmark_run_id: str,
    measured_records: list[dict[str, Any]],
    required_valid_runs: int,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    valid_records = [record for record in measured_records if record["success"]]
    aggregate = {
        "schema_version": 1,
        "benchmark_run_id": benchmark_run_id,
        "project_git": provenance["project_git"],
        "benchmark_script_sha256": provenance["benchmark_script_sha256"],
        "required_valid_runs": required_valid_runs,
        "valid_runs": len(valid_records),
        "attempts": len(measured_records),
        "complete": len(valid_records) >= required_valid_runs,
        "metrics": {
            key: metric_summary(valid_records, key)
            for key in (
                "wall_time_ms",
                "runtime_prompt_eval_ms",
                "runtime_prompt_tokens_per_second",
                "runtime_decode_eval_ms",
                "runtime_decode_tokens_per_second",
                "runtime_total_ms",
            )
        },
        "metric_semantics": {
            "wall_time_ms": "End-to-end llama-cli process wall-clock duration; not TTFT or TPOT.",
            "runtime_prompt_tokens_per_second": "Prompt throughput reported by llama-cli.",
            "runtime_decode_tokens_per_second": "Decode throughput reported by llama-cli.",
        },
    }
    path.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return aggregate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="required number of valid measured runs; minimum 5",
    )
    parser.add_argument(
        "--preconditioning-runs",
        type=int,
        default=1,
        help="separate llama-cli runs before measurement; not same-process Runtime warmup",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=8,
        help="maximum measured attempts used to obtain the required valid runs",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "benchmark-results/qwen2.5-3b-q4_k_m",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="verify fixed artifacts and configuration without loading the model",
    )
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="print the fixed llama-cli command and exit after validation",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validation = validate_prerequisites()
    if args.validate_only:
        print(json.dumps(validation, indent=2, sort_keys=True))
        return 0 if validation["valid"] else 2
    if not validation["valid"]:
        print(json.dumps(validation, indent=2, sort_keys=True), file=sys.stderr)
        return 2
    if args.print_command:
        print(json.dumps(benchmark_command()))
        return 0
    if validation["project_git"]["commit"] is None:
        print(
            "main project has no commit; create the stage-one commit before a formal benchmark",
            file=sys.stderr,
        )
        return 2
    if args.runs < 5:
        print("--runs must be at least 5", file=sys.stderr)
        return 2
    if args.preconditioning_runs < 1:
        print("--preconditioning-runs must be at least 1", file=sys.stderr)
        return 2
    if args.max_attempts < args.runs:
        print("--max-attempts must be greater than or equal to --runs", file=sys.stderr)
        return 2

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    benchmark_run_id = f"qwen25-{timestamp}-{os.getpid()}"
    run_directory = args.output_root.resolve() / benchmark_run_id
    run_directory.mkdir(parents=True, exist_ok=False)
    jsonl_path = run_directory / "runs.jsonl"
    config = {
        "schema_version": 1,
        "benchmark_run_id": benchmark_run_id,
        "created_at_utc": utc_now(),
        "fixed_config": FIXED_CONFIG,
        "required_valid_runs": args.runs,
        "preconditioning_runs": args.preconditioning_runs,
        "preconditioning_is_separate_process": True,
        "runtime_same_process_warmup": False,
        "max_attempts": args.max_attempts,
        "command": benchmark_command(),
        "runtime_commit": EXPECTED_RUNTIME_COMMIT,
        "project_git": validation["project_git"],
        "benchmark_script_sha256": validation["benchmark_script_sha256"],
        "model_sha256": EXPECTED_MODEL_SHA256,
        "manifests": [
            "manifests/environment.json",
            "manifests/build.json",
            "manifests/runtime.json",
            "manifests/model.json",
        ],
    }
    (run_directory / "config.json").write_text(
        json.dumps(config, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    preconditioning_records: list[dict[str, Any]] = []
    measured_records: list[dict[str, Any]] = []
    try:
        for iteration in range(1, args.preconditioning_runs + 1):
            record = run_once(
                "preconditioning", iteration, benchmark_run_id, run_directory, validation
            )
            preconditioning_records.append(record)
            append_jsonl(jsonl_path, record)
            if not record["success"]:
                print(
                    f"preconditioning run {iteration} failed; "
                    f"see {record['artifacts']['stderr_log']}",
                    file=sys.stderr,
                )
                write_csv(run_directory / "summary.csv", measured_records)
                write_aggregate(
                    run_directory / "summary.json",
                    benchmark_run_id,
                    measured_records,
                    args.runs,
                    validation,
                )
                return 1

        valid_count = 0
        attempt = 0
        while valid_count < args.runs and attempt < args.max_attempts:
            attempt += 1
            record = run_once(
                "measured", attempt, benchmark_run_id, run_directory, validation
            )
            if record["success"]:
                valid_count += 1
                record["valid_run_index"] = valid_count
            else:
                record["valid_run_index"] = None
            measured_records.append(record)
            append_jsonl(jsonl_path, record)
            print(
                f"measured attempt {attempt}: success={record['success']} "
                f"valid={valid_count}/{args.runs} wall_time_ms={record['wall_time_ms']}",
                flush=True,
            )
    except KeyboardInterrupt:
        print("benchmark interrupted", file=sys.stderr)

    write_csv(run_directory / "summary.csv", measured_records)
    aggregate = write_aggregate(
        run_directory / "summary.json",
        benchmark_run_id,
        measured_records,
        args.runs,
        validation,
    )
    print(json.dumps(aggregate, indent=2, sort_keys=True))
    print(f"artifacts: {run_directory}")
    return 0 if aggregate["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
