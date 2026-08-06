#!/usr/bin/env python3
"""Calibrate and execute the single-attempt M7.4C 16384 VLM validation."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_vlm_long_context_fixture_m7_4c as fixture_generator  # noqa: E402
import run_vlm_context_smoke as context_smoke  # noqa: E402
import run_vlm_long_context as m7_4b  # noqa: E402


ROOT = SCRIPT_DIR.parents[1]
DEFAULT_CONFIG = ROOT / "evidence/milestones/configs/vlm/vlm-long-context-m7.4c.json"
EXPECTED_KEYS = {"publisher", "start_code", "middle_torque_nm", "reset_seconds"}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_config(config: dict[str, Any]) -> None:
    fixed = config["fixed_parameters"]
    if config["milestone"] != "M7.4C" or config["policy"]["contexts_executed"] != [16384]:
        raise ValueError("M7.4C permits only context 16384")
    expected = {
        "context": 16384,
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
    fixture = config["fixture"]
    if not fixture["raw_token_target_min"] <= fixture["raw_token_target_max"]:
        raise ValueError("invalid raw token calibration range")
    if not fixture["direct_prompt_token_min"] <= fixture["direct_prompt_token_max"] < fixed["context"]:
        raise ValueError("invalid direct prompt token gate")


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
        "--mmproj-offload", "--perf", "--offline", "--verbose",
        "--log-timestamps", "--log-colors", "off", "--no-warmup",
    ]
    forbidden = {"-hf", "-hfr", "--hf-repo", "--model-url", "--mmproj-url", "--prompt"}
    if forbidden.intersection(command) or "/usr/bin/time" in command:
        raise context_smoke.SmokeError("forbidden inference argument", "launcher_preflight_failed")
    return command


def build_launch_command(config: dict[str, Any], inference_command: list[str]) -> list[str]:
    timeout_path = context_smoke.shutil.which("timeout") or "timeout"
    launcher = config["launcher"]
    return [
        timeout_path,
        "--signal=TERM",
        f"--kill-after={launcher['timeout_kill_after_seconds']}s",
        f"{launcher['timeout_seconds']}s",
        *inference_command,
    ]


def calibrate_fixture(config: dict[str, Any], run_dir: Path, root: Path = ROOT) -> dict[str, Any]:
    """Reuse the audited tokenizer calibration mechanics with the C fixture module."""
    original_generator = m7_4b.fixture_generator
    m7_4b.fixture_generator = fixture_generator
    try:
        return m7_4b.calibrate_fixture(config, run_dir, root)
    finally:
        m7_4b.fixture_generator = original_generator


def validate_answer(stdout: str, config: dict[str, Any]) -> dict[str, Any]:
    raw = stdout.strip()
    try:
        parsed: Any = json.loads(raw)
        parse_error = None
    except (json.JSONDecodeError, TypeError) as error:
        parsed, parse_error = None, str(error)
    exact_keys = isinstance(parsed, dict) and set(parsed) == EXPECTED_KEYS
    checks = {
        "valid_json": parse_error is None,
        "json_object": isinstance(parsed, dict),
        "exact_keys": exact_keys,
        "publisher_contains_expected": exact_keys and isinstance(parsed["publisher"], str)
        and config["fixture"]["expected_publisher_substring"] in parsed["publisher"],
        "start_code_exact": exact_keys and type(parsed["start_code"]) is str and parsed["start_code"] == "A17",
        "middle_torque_nm_exact": exact_keys and type(parsed["middle_torque_nm"]) is int
        and parsed["middle_torque_nm"] == 42,
        "reset_seconds_exact": exact_keys and type(parsed["reset_seconds"]) is int
        and parsed["reset_seconds"] == 7,
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
        "milestone": "M7.4C",
        "status": "PENDING",
        "success_gate_passed": False,
        "fixed_parameters": {key: fixed[key] for key in ("context", "batch", "ubatch")},
        "assets": {role: {"sha256": None} for role in ("inference_binary", "tokenizer_binary", "main_model", "mmproj", "image")},
        "fixture": {"sha256": None, "raw_token_count": None},
        "git": {"project": {"commit": None, "dirty": None}, "runtime": {"commit": None, "dirty": None}},
        "actual_runtime": {"prompt_tokens": None, "image_tokens": None},
        "kv_cache": {"total_mib": None},
        "timings_ms": {key: None for key in ("vision_encode", "image_embedding_decode", "prompt_eval", "decode", "cli_total", "wall_clock")},
        "telemetry": {"sample_count": 0, "peak_uma_used_mb": None, "peak_gr3d_percent": None, "peak_temperature_c": None, "power_rails_mw": {}},
        "correctness": {"parsed_answer": None},
        "process": {"exit_code": None, "inference_run_count": 0, "retry_count": 0},
        "finish_reason": None,
        "failure_class": None,
    }


def fail_before_inference(run_dir: Path, result: dict[str, Any], failure_class: str, detail: str, tokenizer_runs: int = 0) -> int:
    result.update({"status": "FAILED", "failure_class": failure_class, "finish_reason": "pre_inference_failure", "failure_detail": detail})
    result["process"].update({"llama_mtmd_cli_invoked": False, "inference_run_count": 0, "retry_count": 0, "tokenizer_run_count": tokenizer_runs, "tokenizer_runs_are_inference_attempts": False})
    write_json(run_dir / "result.json", result)
    print(json.dumps({"status": "FAILED", "result_directory": str(run_dir), "failure_class": failure_class, "inference_run_count": 0}))
    return 2


def execute_run(args: argparse.Namespace, config: dict[str, Any], root: Path = ROOT) -> int:
    validate_config(config)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f%z")
    output_root = Path(args.output_root) if args.output_root else root / config["launcher"]["output_root"]
    run_dir = output_root / timestamp
    run_dir.mkdir(parents=True, exist_ok=False)
    for name in ("stdout.log", "stderr.log", "tegrastats.log", "tegrastats.stdout.log", "tegrastats.stderr.log", "tokenizer.stdout.log", "tokenizer.stderr.log"):
        (run_dir / name).touch(exist_ok=False)
    result = initial_result(config)
    result.update({"timestamp_directory": timestamp, "result_directory": str(run_dir.relative_to(root))})
    write_json(run_dir / "config.snapshot.json", config)

    try:
        preflight = m7_4b.run_preflight(config, root)
    except context_smoke.SmokeError as error:
        write_json(run_dir / "asset-provenance.json", {"status": "FAILED", "failure_class": error.failure_class, "detail": str(error)})
        return fail_before_inference(run_dir, result, error.failure_class, str(error))
    result["assets"], result["git"] = preflight["assets"], preflight["git"]
    try:
        calibration = calibrate_fixture(config, run_dir, root)
    except context_smoke.SmokeError as error:
        calibration_path = run_dir / "tokenizer-calibration.json"
        runs = len(read_json(calibration_path).get("attempts", [])) if calibration_path.is_file() else 0
        return fail_before_inference(run_dir, result, error.failure_class, str(error), runs)

    result["fixture"] = calibration["fixture"]
    result["tokenizer"] = {"command_artifact": "tokenizer-command.txt", "raw_token_count": calibration["fixture"]["raw_token_count"], "run_count": calibration["tokenizer_run_count"], "counts_as_inference_attempt": False}
    write_json(run_dir / "asset-provenance.json", {"status": "PASSED", "assets": result["assets"], "git": result["git"], "readonly_references": preflight["readonly_references"], "fixture": result["fixture"], "tokenizer": result["tokenizer"], "automatic_download": False, "usr_bin_time_used": False})

    inference = build_inference_command(config, run_dir / "fixture.txt", root)
    launch = build_launch_command(config, inference)
    (run_dir / "inference-command.txt").write_text(shlex.join(launch) + "\n", encoding="utf-8")
    telemetry_process: subprocess.Popen[Any] | None = None
    telemetry_stdout = (run_dir / "tegrastats.stdout.log").open("w", encoding="utf-8")
    telemetry_stderr = (run_dir / "tegrastats.stderr.log").open("w", encoding="utf-8")
    try:
        telemetry_process = subprocess.Popen([preflight["dependencies"]["tegrastats"], "--interval", str(config["launcher"]["telemetry_interval_ms"]), "--logfile", str(run_dir / "tegrastats.log")], cwd=root, stdout=telemetry_stdout, stderr=telemetry_stderr, text=True)
        if not context_smoke.wait_for_telemetry(telemetry_process, run_dir / "tegrastats.log"):
            raise context_smoke.SmokeError("tegrastats did not produce a valid sample", "launcher_preflight_failed")
    except (OSError, context_smoke.SmokeError) as error:
        m7_4b.stop_telemetry(telemetry_process)
        telemetry_stdout.close(); telemetry_stderr.close()
        return fail_before_inference(run_dir, result, getattr(error, "failure_class", "launcher_preflight_failed"), str(error), calibration["tokenizer_run_count"])

    start_iso = datetime.now().astimezone().isoformat()
    start_ns = context_smoke.read_date_ns(preflight["dependencies"]["date"])
    invocation = {"llama_mtmd_cli_invoked": True, "inference_run_count": 1, "retry_count": 0, "tokenizer_run_count": calibration["tokenizer_run_count"], "tokenizer_runs_are_inference_attempts": False}
    write_json(run_dir / "invocation-status.json", invocation)
    exit_code: int | None = None
    launch_error: str | None = None
    try:
        with (run_dir / "stdout.log").open("w", encoding="utf-8") as stdout_stream, (run_dir / "stderr.log").open("w", encoding="utf-8") as stderr_stream:
            exit_code = subprocess.run(launch, cwd=root, stdout=stdout_stream, stderr=stderr_stream, text=True, check=False).returncode
    except OSError as error:
        launch_error = str(error)
    finally:
        end_ns = context_smoke.read_date_ns(preflight["dependencies"]["date"])
        end_iso = datetime.now().astimezone().isoformat()
        m7_4b.stop_telemetry(telemetry_process)
        telemetry_stdout.close(); telemetry_stderr.close()

    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8", errors="replace")
    stderr = (run_dir / "stderr.log").read_text(encoding="utf-8", errors="replace")
    parsed, telemetry, correctness = context_smoke.parse_runtime_log(stderr), context_smoke.parse_telemetry(run_dir / "tegrastats.log"), validate_answer(stdout, config)
    elapsed_ms = (end_ns - start_ns) // 1_000_000
    runtime_failure = context_smoke.classify_failure(exit_code if exit_code is not None else 1, stderr, stdout, telemetry["sample_count"] > 0)
    prompt_tokens = parsed["tokens"]["prompt_tokens"]
    prompt_gate = config["fixture"]["direct_prompt_token_min"] <= (prompt_tokens or -1) <= config["fixture"]["direct_prompt_token_max"]
    image_tokens_direct = parsed["vision"]["image_tokens"] is not None and parsed["vision"]["image_tokens_measurement_status"] == "DIRECTLY_PARSED_FROM_CLI_LOG"
    output_summary = context_smoke.summarize_output(stdout)
    criteria = {
        "actual_context_matches": parsed["actual_context"] == 16384,
        "actual_batch_matches": parsed["actual_batch"] == 512,
        "actual_ubatch_matches": parsed["actual_ubatch"] == 512,
        "prompt_tokens_13000_to_14500": prompt_gate,
        "image_tokens_directly_reported": image_tokens_direct,
        "main_model_loaded": parsed["main_model_loaded"], "mmproj_loaded": parsed["mmproj_loaded"],
        "cuda_offload_37_of_37": parsed["offloaded_layers"] == "37/37",
        "image_decoded": parsed["vision"]["image_decode_succeeded"], "vision_encoded": parsed["vision"]["vision_encode_succeeded"],
        "embedding_injected": parsed["vision"]["embedding_injection_succeeded"], "cuda_path_logged": parsed["cuda_evidence"] and parsed["mmproj_cuda"],
        "output_nonempty": output_summary is not None, "output_json_and_facts_correct": correctness["passed"],
        "telemetry_sample_present": telemetry["sample_count"] > 0, "no_disqualifying_runtime_error": runtime_failure is None,
    }
    success = exit_code == 0 and all(criteria.values())
    failure_class = runtime_failure or ("prompt_token_range_failed" if not prompt_gate else "vision_encode_failed" if not image_tokens_direct else "quality_gate_failed" if not correctness["passed"] else "internal")
    finish, finish_status = context_smoke.finish_reason(exit_code if exit_code is not None else 1, parsed["tokens"]["output_tokens"], config["fixed_parameters"]["max_new_tokens"])
    result.update({
        "status": "SUCCESS" if success else "FAILED", "success_gate_passed": success, "failure_class": None if success else failure_class, "failure_detail": None if success else (launch_error or "one or more success gates failed; inspect artifacts"),
        "actual_runtime": {"context": parsed["actual_context"], "batch": parsed["actual_batch"], "ubatch": parsed["actual_ubatch"], "prompt_tokens": prompt_tokens, "output_tokens": parsed["tokens"]["output_tokens"], "image_tokens": parsed["vision"]["image_tokens"], "image_grid_x": parsed["vision"]["image_grid_x"], "image_grid_y": parsed["vision"]["image_grid_y"], "offloaded_layers": parsed["offloaded_layers"], "mmproj_tensor_count": parsed["mmproj_tensor_count"], "mmproj_cuda": parsed["mmproj_cuda"], "flash_attention": "enabled" if parsed["flash_attention"] else None},
        "kv_cache": parsed["kv_cache"], "vision": parsed["vision"], "tokens": parsed["tokens"],
        "timings_ms": {"model_load": m7_4b.parse_model_load_ms(stderr), **parsed["timings_ms"], "wall_clock": elapsed_ms, "wall_clock_measurement": "date +%s%N"},
        "telemetry": telemetry, "correctness": correctness,
        "process": {"start": start_iso, "end": end_iso, "start_ns": start_ns, "end_ns": end_ns, "elapsed_ms": elapsed_ms, "exit_code": exit_code, "timed_out": exit_code in (124, 137), **invocation},
        "finish_reason": finish, "finish_reason_measurement_status": finish_status,
        "output": {"nonempty": output_summary is not None, "size_bytes": (run_dir / "stdout.log").stat().st_size, "sha256": context_smoke.sha256_file(run_dir / "stdout.log"), "summary": output_summary, "raw_artifact": "stdout.log"},
        "success_criteria": criteria,
        "artifacts": {"fixture": "fixture.txt", "fixture_metadata": "fixture-metadata.json", "tokenizer_calibration": "tokenizer-calibration.json", "inference_command": "inference-command.txt", "asset_provenance": "asset-provenance.json", "stdout": "stdout.log", "stderr": "stderr.log", "telemetry": "tegrastats.log", "correctness": "correctness-check.json", "result": "result.json"},
        "scope": {"single_synthetic_long_manual_run": True, "rag": False, "actual_multi_turn_session": False, "production_manual_quality_evaluation": False, "average_performance_or_stability_conclusion": False, "context_32768_executed": False},
    })
    write_json(run_dir / "correctness-check.json", correctness)
    write_json(run_dir / "result.json", result)
    (run_dir / "process-status.txt").write_text(f"start={start_iso}\nend={end_iso}\nelapsed_ms={elapsed_ms}\nexit_code={exit_code}\nllama_mtmd_cli_invoked=true\ninference_run_count=1\nretry_count=0\ntokenizer_run_count={calibration['tokenizer_run_count']}\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "result_directory": str(run_dir), "exit_code": exit_code, "failure_class": result["failure_class"], "prompt_tokens": prompt_tokens, "image_tokens": parsed["vision"]["image_tokens"]}))
    return 0 if success else 1


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
    plan = {"mode": "execute" if args.execute else "dry-run", "execute_requested": args.execute, "model_process_started": False, "context": 16384, "tokenizer_calibration_required": True, "tokenizer_runs_are_inference_attempts": False, "inference_command": build_inference_command(config, Path("<timestamped-run-directory>/fixture.txt")), "automatic_download": False, "inference_run_count": 0, "retry_count": 0}
    if not args.execute:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    return execute_run(args, config)


if __name__ == "__main__":
    raise SystemExit(main())
