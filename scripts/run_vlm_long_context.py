#!/usr/bin/env python3
"""Calibrate and run the explicit-only M7.4B long-context VLM smoke."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_vlm_long_context_fixture as fixture_generator  # noqa: E402
import run_vlm_context_smoke as context_smoke  # noqa: E402


ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG = ROOT / "configs/vlm-long-context-m7.4b.json"
EXPECTED_KEYS = {"publisher", "start_code", "middle_torque_nm", "reset_seconds"}
REQUIRED_RESULT_PATHS = (
    "fixed_parameters.context",
    "fixed_parameters.batch",
    "fixed_parameters.ubatch",
    "assets.inference_binary.sha256",
    "assets.tokenizer_binary.sha256",
    "assets.main_model.sha256",
    "assets.mmproj.sha256",
    "assets.image.sha256",
    "fixture.sha256",
    "fixture.raw_token_count",
    "git.project.commit",
    "git.project.dirty",
    "git.runtime.commit",
    "git.runtime.dirty",
    "actual_runtime.prompt_tokens",
    "actual_runtime.image_tokens",
    "kv_cache.total_mib",
    "timings_ms.vision_encode",
    "timings_ms.image_embedding_decode",
    "timings_ms.prompt_eval",
    "timings_ms.decode",
    "timings_ms.cli_total",
    "timings_ms.wall_clock",
    "telemetry.sample_count",
    "telemetry.peak_uma_used_mb",
    "telemetry.peak_gr3d_percent",
    "telemetry.peak_temperature_c",
    "telemetry.power_rails_mw",
    "correctness.parsed_answer",
    "process.exit_code",
    "process.inference_run_count",
    "process.retry_count",
    "finish_reason",
    "failure_class",
)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_config(config: dict[str, Any]) -> None:
    fixed = config["fixed_parameters"]
    policy = config["policy"]
    if fixed["context"] != 8192 or policy["contexts_executed"] != [8192]:
        raise ValueError("M7.4B permits only context 8192")
    expected = {
        "batch": 512,
        "ubatch": 512,
        "gpu_layers": 99,
        "flash_attention": "on",
        "temperature": 0,
        "seed": 424242,
        "max_new_tokens": 128,
        "offline": True,
        "warmup": False,
        "chat_mode": False,
        "prompt_source": "--file",
    }
    for key, value in expected.items():
        if fixed.get(key) != value:
            raise ValueError(f"fixed parameter mismatch for {key}: {fixed.get(key)!r}")


def build_tokenizer_command(config: dict[str, Any], fixture_path: Path, root: Path = ROOT) -> list[str]:
    return [
        str(root / config["binaries"]["tokenizer"]["path"]),
        "--model", str(root / config["assets"]["main_model"]["path"]),
        "--file", str(fixture_path),
        "--ids",
        "--show-count",
        "--log-disable",
    ]


def build_inference_command(config: dict[str, Any], fixture_path: Path, root: Path = ROOT) -> list[str]:
    validate_config(config)
    fixed = config["fixed_parameters"]
    assets = config["assets"]
    command = [
        str(root / config["binaries"]["inference"]["path"]),
        "--model", str(root / assets["main_model"]["path"]),
        "--mmproj", str(root / assets["mmproj"]["path"]),
        "--image", str(root / assets["image"]["path"]),
        "--file", str(fixture_path),
        "--ctx-size", str(fixed["context"]),
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
    ]
    forbidden = {"-hf", "-hfr", "--hf-repo", "--model-url", "--mmproj-url", "--prompt"}
    if forbidden.intersection(command) or "/usr/bin/time" in command:
        raise context_smoke.SmokeError("forbidden inference argument", "launcher_preflight_failed")
    return command


def build_launch_command(config: dict[str, Any], inference_command: list[str]) -> list[str]:
    launcher = config["launcher"]
    timeout_path = context_smoke.shutil.which("timeout") or "timeout"
    return [
        timeout_path,
        "--signal=TERM",
        f"--kill-after={launcher['timeout_kill_after_seconds']}s",
        f"{launcher['timeout_seconds']}s",
        *inference_command,
    ]


def parse_tokenizer_count(stdout: str) -> int:
    matches = re.findall(r"Total number of tokens:\s*(\d+)", stdout)
    if len(matches) != 1:
        raise context_smoke.SmokeError(
            f"expected one tokenizer count, found {len(matches)}", "tokenizer_calibration_failed"
        )
    return int(matches[0])


def run_tokenizer(command: list[str], root: Path) -> tuple[int, str, str]:
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    return completed.returncode, completed.stdout, completed.stderr


def calibrate_fixture(
    config: dict[str, Any], run_dir: Path, root: Path = ROOT
) -> dict[str, Any]:
    fixture_config = config["fixture"]
    low = int(fixture_config["filler_blocks_min"])
    high = int(fixture_config["filler_blocks_max"])
    target_min = int(fixture_config["raw_token_target_min"])
    target_max = int(fixture_config["raw_token_target_max"])
    fixture_path = run_dir / "fixture.txt"
    history: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None

    while low <= high:
        blocks = (low + high) // 2
        fixture = fixture_generator.generate_fixture(blocks)
        fixture_path.write_text(fixture, encoding="utf-8")
        command = build_tokenizer_command(config, fixture_path, root)
        exit_code, stdout, stderr = run_tokenizer(command, root)
        attempt = {
            "filler_blocks": blocks,
            "exit_code": exit_code,
            "fixture_size_bytes": fixture_path.stat().st_size,
            "fixture_sha256": context_smoke.sha256_file(fixture_path),
            "raw_token_count": None,
        }
        if exit_code != 0:
            history.append(attempt)
            write_json(run_dir / "tokenizer-calibration.json", {"status": "FAILED", "attempts": history})
            (run_dir / "tokenizer.stdout.log").write_text(stdout, encoding="utf-8")
            (run_dir / "tokenizer.stderr.log").write_text(stderr, encoding="utf-8")
            raise context_smoke.SmokeError(
                f"llama-tokenize exited with {exit_code}", "tokenizer_calibration_failed"
            )
        count = parse_tokenizer_count(stdout)
        attempt["raw_token_count"] = count
        history.append(attempt)
        write_json(run_dir / "tokenizer-calibration.json", {"status": "CALIBRATING", "attempts": history})

        if target_min <= count <= target_max:
            selected = {
                "filler_blocks": blocks,
                "raw_token_count": count,
                "fixture": fixture,
                "command": command,
                "stdout": stdout,
                "stderr": stderr,
            }
            break
        if count < target_min:
            low = blocks + 1
        else:
            high = blocks - 1

    if selected is None:
        raise context_smoke.SmokeError(
            f"no fixture in raw token range {target_min}-{target_max}", "tokenizer_calibration_failed"
        )

    fixture_path.write_text(selected["fixture"], encoding="utf-8")
    (run_dir / "tokenizer-command.txt").write_text(
        shlex.join(selected["command"]) + "\n", encoding="utf-8"
    )
    (run_dir / "tokenizer.stdout.log").write_text(selected["stdout"], encoding="utf-8")
    (run_dir / "tokenizer.stderr.log").write_text(selected["stderr"], encoding="utf-8")
    (run_dir / "tokenizer-count.txt").write_text(
        f"raw_token_count={selected['raw_token_count']}\n", encoding="utf-8"
    )
    fixture_validation = fixture_generator.validate_fixture(selected["fixture"])
    fixture_metadata = {
        "schema_version": 1,
        "synthetic_only": True,
        "contains_real_customer_information": False,
        "filler_blocks": selected["filler_blocks"],
        "path": "fixture.txt",
        "size_bytes": fixture_path.stat().st_size,
        "sha256": context_smoke.sha256_file(fixture_path),
        "raw_token_count": selected["raw_token_count"],
        "raw_token_measurement_status": "DIRECTLY_EMITTED_BY_LLAMA_TOKENIZE",
        "facts": fixture_config["facts"],
        "validation": fixture_validation,
    }
    write_json(run_dir / "fixture-metadata.json", fixture_metadata)
    write_json(run_dir / "tokenizer-calibration.json", {
        "status": "PASSED",
        "target_raw_token_range": [target_min, target_max],
        "selected_filler_blocks": selected["filler_blocks"],
        "selected_raw_token_count": selected["raw_token_count"],
        "tokenizer_run_count": len(history),
        "tokenizer_runs_are_inference_attempts": False,
        "attempts": history,
    })
    return {
        "fixture": fixture_metadata,
        "tokenizer_run_count": len(history),
        "command": selected["command"],
        "history": history,
    }


def run_preflight(config: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    base_config = {
        "runtime": config["runtime"],
        "binary": config["binaries"]["inference"],
        "assets": config["assets"],
    }
    preflight = context_smoke.run_preflight(base_config, root)
    tokenizer = context_smoke.verify_file(
        root, config["binaries"]["tokenizer"], "tokenizer_binary", executable=True
    )
    ldd = subprocess.run(
        [preflight["dependencies"]["ldd"], str(root / tokenizer["path"])],
        capture_output=True,
        text=True,
        check=False,
    )
    if ldd.returncode or "not found" in f"{ldd.stdout}\n{ldd.stderr}".lower():
        raise context_smoke.SmokeError(
            "tokenizer binary has unresolved dynamic dependencies", "launcher_dependency_missing"
        )
    references = {
        role: context_smoke.verify_file(root, expected, role)
        for role, expected in config["readonly_references"].items()
    }
    preflight["assets"]["inference_binary"] = preflight["assets"].pop("binary")
    preflight["assets"]["tokenizer_binary"] = tokenizer
    preflight["readonly_references"] = references
    preflight["tokenizer_ldd_not_found_count"] = 0
    preflight["tokenizer_calls_are_inference_attempts"] = False
    return preflight


def validate_answer(stdout: str, config: dict[str, Any]) -> dict[str, Any]:
    raw = stdout.strip()
    parsed: Any = None
    parse_error: str | None = None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as error:
        parse_error = str(error)

    exact_keys = isinstance(parsed, dict) and set(parsed) == EXPECTED_KEYS
    expected = config["fixture"]
    checks = {
        "valid_json": parse_error is None,
        "json_object": isinstance(parsed, dict),
        "exact_keys": exact_keys,
        "publisher_contains_expected": (
            exact_keys
            and isinstance(parsed["publisher"], str)
            and expected["expected_publisher_substring"] in parsed["publisher"]
        ),
        "start_code_exact": exact_keys and parsed["start_code"] == "A17" and type(parsed["start_code"]) is str,
        "middle_torque_nm_exact": exact_keys and parsed["middle_torque_nm"] == 42 and type(parsed["middle_torque_nm"]) is int,
        "reset_seconds_exact": exact_keys and parsed["reset_seconds"] == 7 and type(parsed["reset_seconds"]) is int,
    }
    return {
        "passed": all(checks.values()),
        "failure_class_if_failed": None if all(checks.values()) else "quality_gate_failed",
        "parse_error": parse_error,
        "parsed_answer": parsed,
        "checks": checks,
        "raw_answer_preserved_in": "stdout.log",
    }


def initial_result(config: dict[str, Any]) -> dict[str, Any]:
    fixed = config["fixed_parameters"]
    return {
        "schema_version": 1,
        "milestone": "M7.4B",
        "status": "PENDING",
        "success_gate_passed": False,
        "fixed_parameters": {
            "context": fixed["context"],
            "batch": fixed["batch"],
            "ubatch": fixed["ubatch"],
        },
        "assets": {
            "inference_binary": {"sha256": None},
            "tokenizer_binary": {"sha256": None},
            "main_model": {"sha256": None},
            "mmproj": {"sha256": None},
            "image": {"sha256": None},
        },
        "fixture": {"sha256": None, "raw_token_count": None},
        "git": {
            "project": {"commit": None, "dirty": None},
            "runtime": {"commit": None, "dirty": None},
        },
        "actual_runtime": {"prompt_tokens": None, "image_tokens": None},
        "kv_cache": {"total_mib": None},
        "timings_ms": {
            "vision_encode": None,
            "image_embedding_decode": None,
            "prompt_eval": None,
            "decode": None,
            "cli_total": None,
            "wall_clock": None,
        },
        "telemetry": {
            "sample_count": 0,
            "peak_uma_used_mb": None,
            "peak_gr3d_percent": None,
            "peak_temperature_c": None,
            "power_rails_mw": {},
        },
        "correctness": {"parsed_answer": None},
        "process": {"exit_code": None, "inference_run_count": 0, "retry_count": 0},
        "finish_reason": None,
        "failure_class": None,
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


def parse_model_load_ms(stderr: str) -> float | None:
    matches = re.findall(r"load time =\s*([0-9.]+) ms", stderr)
    return float(matches[-1]) if matches else None


def stop_telemetry(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def fail_before_inference(
    run_dir: Path,
    result: dict[str, Any],
    failure_class: str,
    detail: str,
    tokenizer_run_count: int = 0,
) -> int:
    result.update({
        "status": "FAILED",
        "failure_class": failure_class,
        "finish_reason": "pre_inference_failure",
        "failure_detail": detail,
    })
    result["process"].update({
        "llama_mtmd_cli_invoked": False,
        "inference_run_count": 0,
        "retry_count": 0,
        "tokenizer_run_count": tokenizer_run_count,
        "tokenizer_runs_are_inference_attempts": False,
    })
    write_json(run_dir / "result.json", result)
    print(json.dumps({
        "status": "FAILED",
        "result_directory": str(run_dir),
        "failure_class": failure_class,
        "inference_run_count": 0,
    }))
    return 2


def execute_run(args: argparse.Namespace, config: dict[str, Any], root: Path = ROOT) -> int:
    validate_config(config)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f%z")
    output_root = Path(args.output_root) if args.output_root else root / config["launcher"]["output_root"]
    run_dir = output_root / timestamp
    run_dir.mkdir(parents=True, exist_ok=False)
    for name in (
        "stdout.log", "stderr.log", "tegrastats.log", "tegrastats.stdout.log",
        "tegrastats.stderr.log", "tokenizer.stdout.log", "tokenizer.stderr.log",
    ):
        (run_dir / name).touch(exist_ok=False)

    result = initial_result(config)
    result["timestamp_directory"] = timestamp
    result["result_directory"] = str(run_dir.relative_to(root)) if run_dir.is_relative_to(root) else str(run_dir)
    write_json(run_dir / "config.snapshot.json", config)

    try:
        preflight = run_preflight(config, root)
    except context_smoke.SmokeError as error:
        write_json(run_dir / "asset-provenance.json", {
            "status": "FAILED", "failure_class": error.failure_class, "detail": str(error)
        })
        return fail_before_inference(run_dir, result, error.failure_class, str(error))

    result["assets"] = preflight["assets"]
    result["git"] = preflight["git"]
    try:
        calibration = calibrate_fixture(config, run_dir, root)
    except context_smoke.SmokeError as error:
        tokenizer_run_count = 0
        calibration_path = run_dir / "tokenizer-calibration.json"
        if calibration_path.is_file():
            tokenizer_run_count = len(read_json(calibration_path).get("attempts", []))
        return fail_before_inference(
            run_dir, result, error.failure_class, str(error), tokenizer_run_count
        )

    result["fixture"] = calibration["fixture"]
    result["tokenizer"] = {
        "command_artifact": "tokenizer-command.txt",
        "stdout_artifact": "tokenizer.stdout.log",
        "stderr_artifact": "tokenizer.stderr.log",
        "raw_token_count": calibration["fixture"]["raw_token_count"],
        "run_count": calibration["tokenizer_run_count"],
        "counts_as_inference_attempt": False,
    }
    provenance = {
        "status": "PASSED",
        "assets": result["assets"],
        "git": preflight["git"],
        "readonly_references": preflight["readonly_references"],
        "fixture": calibration["fixture"],
        "tokenizer": result["tokenizer"],
        "ldd_not_found_count": 0,
        "automatic_download": False,
        "usr_bin_time_used": False,
    }
    write_json(run_dir / "asset-provenance.json", provenance)

    fixture_path = run_dir / "fixture.txt"
    inference_command = build_inference_command(config, fixture_path, root)
    launch_command = build_launch_command(config, inference_command)
    (run_dir / "inference-command.txt").write_text(shlex.join(launch_command) + "\n", encoding="utf-8")
    result["command"] = {
        "argv": launch_command,
        "model_argv": inference_command,
        "prompt_source": "--file",
        "offline": True,
        "warmup": False,
        "timeout_seconds": config["launcher"]["timeout_seconds"],
    }

    telemetry_process: subprocess.Popen[Any] | None = None
    telemetry_stdout = (run_dir / "tegrastats.stdout.log").open("w", encoding="utf-8")
    telemetry_stderr = (run_dir / "tegrastats.stderr.log").open("w", encoding="utf-8")
    try:
        telemetry_process = subprocess.Popen(
            [
                preflight["dependencies"]["tegrastats"],
                "--interval", str(config["launcher"]["telemetry_interval_ms"]),
                "--logfile", str(run_dir / "tegrastats.log"),
            ],
            cwd=root,
            stdout=telemetry_stdout,
            stderr=telemetry_stderr,
            text=True,
        )
        if not context_smoke.wait_for_telemetry(telemetry_process, run_dir / "tegrastats.log"):
            raise context_smoke.SmokeError(
                "tegrastats did not produce a valid sample", "launcher_preflight_failed"
            )
    except (OSError, context_smoke.SmokeError) as error:
        stop_telemetry(telemetry_process)
        telemetry_stdout.close()
        telemetry_stderr.close()
        return fail_before_inference(
            run_dir,
            result,
            getattr(error, "failure_class", "launcher_preflight_failed"),
            str(error),
            calibration["tokenizer_run_count"],
        )

    start_iso = datetime.now().astimezone().isoformat()
    start_ns = context_smoke.read_date_ns(preflight["dependencies"]["date"])
    invocation = {
        "llama_mtmd_cli_invoked": True,
        "inference_run_count": 1,
        "retry_count": 0,
        "tokenizer_run_count": calibration["tokenizer_run_count"],
        "tokenizer_runs_are_inference_attempts": False,
    }
    write_json(run_dir / "invocation-status.json", invocation)
    exit_code: int | None = None
    launch_error: str | None = None
    try:
        with (run_dir / "stdout.log").open("w", encoding="utf-8") as stdout_stream, \
             (run_dir / "stderr.log").open("w", encoding="utf-8") as stderr_stream:
            completed = subprocess.run(
                launch_command,
                cwd=root,
                stdout=stdout_stream,
                stderr=stderr_stream,
                text=True,
                check=False,
            )
            exit_code = completed.returncode
    except OSError as error:
        launch_error = str(error)
    finally:
        end_ns = context_smoke.read_date_ns(preflight["dependencies"]["date"])
        end_iso = datetime.now().astimezone().isoformat()
        stop_telemetry(telemetry_process)
        telemetry_stdout.close()
        telemetry_stderr.close()

    elapsed_ms = (end_ns - start_ns) // 1_000_000
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    parsed = context_smoke.parse_runtime_log(stderr)
    telemetry = context_smoke.parse_telemetry(run_dir / "tegrastats.log")
    correctness = validate_answer(stdout, config)
    effective_exit_code = exit_code if exit_code is not None else 1
    runtime_failure = context_smoke.classify_failure(
        effective_exit_code, stderr, stdout, telemetry["sample_count"] > 0
    )
    prompt_tokens = parsed["tokens"]["prompt_tokens"]
    prompt_range = config["fixture"]["direct_prompt_token_min"] <= (prompt_tokens or -1) <= config["fixture"]["direct_prompt_token_max"]
    image_tokens_direct = (
        parsed["vision"]["image_tokens"] is not None
        and parsed["vision"]["image_tokens_measurement_status"] == "DIRECTLY_PARSED_FROM_CLI_LOG"
    )
    output_summary = context_smoke.summarize_output(stdout)
    success_criteria = {
        "actual_context_matches": parsed["actual_context"] == 8192,
        "actual_batch_matches": parsed["actual_batch"] == 512,
        "actual_ubatch_matches": parsed["actual_ubatch"] == 512,
        "prompt_tokens_6000_to_7000": prompt_range,
        "image_tokens_directly_reported": image_tokens_direct,
        "main_model_loaded": parsed["main_model_loaded"],
        "mmproj_loaded": parsed["mmproj_loaded"],
        "cuda_offload_37_of_37": parsed["offloaded_layers"] == "37/37",
        "image_decoded": parsed["vision"]["image_decode_succeeded"],
        "vision_encoded": parsed["vision"]["vision_encode_succeeded"],
        "embedding_injected": parsed["vision"]["embedding_injection_succeeded"],
        "cuda_path_logged": parsed["cuda_evidence"] and parsed["mmproj_cuda"],
        "output_nonempty": output_summary is not None,
        "output_json_and_facts_correct": correctness["passed"],
        "telemetry_sample_present": telemetry["sample_count"] > 0,
        "no_disqualifying_runtime_error": runtime_failure is None,
    }
    success = exit_code == 0 and all(success_criteria.values())
    failure_class = runtime_failure
    if runtime_failure is None and not prompt_range:
        failure_class = "prompt_token_range_failed"
    elif runtime_failure is None and not image_tokens_direct:
        failure_class = "vision_encode_failed"
    elif runtime_failure is None and not correctness["passed"]:
        failure_class = "quality_gate_failed"
    elif runtime_failure is None and not success:
        failure_class = "internal"

    finish, finish_status = context_smoke.finish_reason(
        effective_exit_code, parsed["tokens"]["output_tokens"], config["fixed_parameters"]["max_new_tokens"]
    )
    timings = {
        "model_load": parse_model_load_ms(stderr),
        **parsed["timings_ms"],
        "wall_clock": elapsed_ms,
        "wall_clock_measurement": "date +%s%N",
    }
    result.update({
        "status": "SUCCESS" if success else "FAILED",
        "success_gate_passed": success,
        "failure_class": None if success else failure_class,
        "failure_detail": None if success else (launch_error or "one or more success gates failed; inspect artifacts"),
        "actual_runtime": {
            "context": parsed["actual_context"],
            "batch": parsed["actual_batch"],
            "ubatch": parsed["actual_ubatch"],
            "prompt_tokens": prompt_tokens,
            "output_tokens": parsed["tokens"]["output_tokens"],
            "image_tokens": parsed["vision"]["image_tokens"],
            "image_grid_x": parsed["vision"]["image_grid_x"],
            "image_grid_y": parsed["vision"]["image_grid_y"],
            "offloaded_layers": parsed["offloaded_layers"],
            "mmproj_tensor_count": parsed["mmproj_tensor_count"],
            "mmproj_cuda": parsed["mmproj_cuda"],
            "flash_attention": "enabled" if parsed["flash_attention"] else None,
        },
        "kv_cache": parsed["kv_cache"],
        "vision": parsed["vision"],
        "tokens": parsed["tokens"],
        "timings_ms": timings,
        "telemetry": telemetry,
        "correctness": correctness,
        "process": {
            "start": start_iso,
            "end": end_iso,
            "start_ns": start_ns,
            "end_ns": end_ns,
            "elapsed_ms": elapsed_ms,
            "exit_code": exit_code,
            "timed_out": exit_code in (124, 137),
            **invocation,
        },
        "finish_reason": finish,
        "finish_reason_measurement_status": finish_status,
        "output": {
            "nonempty": output_summary is not None,
            "size_bytes": stdout_path.stat().st_size,
            "sha256": context_smoke.sha256_file(stdout_path),
            "summary": output_summary,
            "raw_artifact": "stdout.log",
        },
        "success_criteria": success_criteria,
        "artifacts": {
            "fixture": "fixture.txt",
            "fixture_metadata": "fixture-metadata.json",
            "tokenizer_command": "tokenizer-command.txt",
            "tokenizer_stdout": "tokenizer.stdout.log",
            "tokenizer_stderr": "tokenizer.stderr.log",
            "tokenizer_count": "tokenizer-count.txt",
            "tokenizer_calibration": "tokenizer-calibration.json",
            "inference_command": "inference-command.txt",
            "asset_provenance": "asset-provenance.json",
            "stdout": "stdout.log",
            "stderr": "stderr.log",
            "telemetry": "tegrastats.log",
            "correctness": "correctness-check.json",
            "result": "result.json",
        },
        "scope": {
            "single_synthetic_long_manual_run": True,
            "rag": False,
            "actual_multi_turn_session": False,
            "production_manual_quality_evaluation": False,
            "average_performance_or_stability_conclusion": False,
            "m7_4a_performance_percentage_comparison": False,
        },
    })
    write_json(run_dir / "correctness-check.json", correctness)
    missing = missing_required_result_fields(result)
    if missing:
        result["status"] = "FAILED"
        result["success_gate_passed"] = False
        result["failure_class"] = "internal"
        result["failure_detail"] = f"result schema missing fields: {missing}"
    write_json(run_dir / "result.json", result)
    (run_dir / "process-status.txt").write_text(
        f"start={start_iso}\nend={end_iso}\nelapsed_ms={elapsed_ms}\nexit_code={exit_code}\n"
        "llama_mtmd_cli_invoked=true\ninference_run_count=1\nretry_count=0\n"
        f"tokenizer_run_count={calibration['tokenizer_run_count']}\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": result["status"],
        "result_directory": str(run_dir),
        "exit_code": exit_code,
        "failure_class": result["failure_class"],
        "prompt_tokens": prompt_tokens,
        "image_tokens": parsed["vision"]["image_tokens"],
    }))
    return 0 if result["status"] == "SUCCESS" else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--output-root", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = read_json(args.config)
    validate_config(config)
    fixture_placeholder = Path("<timestamped-run-directory>/fixture.txt")
    plan = {
        "mode": "execute" if args.execute else "dry-run",
        "execute_requested": args.execute,
        "model_process_started": False,
        "context": 8192,
        "tokenizer_calibration_required": True,
        "tokenizer_runs_are_inference_attempts": False,
        "inference_command": build_inference_command(config, fixture_placeholder),
        "automatic_download": False,
        "inference_run_count": 0,
        "retry_count": 0,
    }
    if not args.execute:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    return execute_run(args, config)


if __name__ == "__main__":
    raise SystemExit(main())
