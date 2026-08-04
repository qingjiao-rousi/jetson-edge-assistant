#!/usr/bin/env python3
"""M7.4C-R: one host-CUDA recovery attempt for the frozen 16384 fixture."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_vlm_context_smoke as smoke  # noqa: E402
import run_vlm_long_context_m7_4c as m7_4c  # noqa: E402
import run_vlm_recovery as recovery  # noqa: E402


ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG = ROOT / "configs/vlm-long-context-m7.4c-r.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_config(config: dict[str, Any]) -> None:
    fixed = config["fixed_parameters"]
    expected = {"context": 16384, "batch": 512, "ubatch": 512, "gpu_layers": 99, "flash_attention": "on", "temperature": 0, "seed": 424242, "max_new_tokens": 128, "offline": True, "warmup": False, "chat_mode": False, "prompt_source": "--file"}
    if config["milestone"] != "M7.4C-R" or config["attempt_ordinal"] != 2 or config["previous_inference_attempt_count"] != 1 or config["retry_count"] != 1:
        raise ValueError("M7.4C-R attempt accounting is not frozen")
    if config["policy"]["model_starts_allowed"] != 1 or config["policy"]["third_attempt_allowed"] or config["policy"]["context_32768_executed"]:
        raise ValueError("M7.4C-R execution policy is invalid")
    for key, value in expected.items():
        if fixed.get(key) != value:
            raise ValueError(f"fixed parameter mismatch for {key}: {fixed.get(key)!r}")


def verify_file(root: Path, expected: dict[str, Any], role: str, executable: bool = False) -> dict[str, Any]:
    return smoke.verify_file(root, expected, role, executable=executable)


def host_cuda_preflight(config: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    binary = root / config["binary"]["path"]
    completed = subprocess.run([str(binary), "--list-devices"], cwd=root, capture_output=True, text=True, check=False)
    output = completed.stdout + completed.stderr
    passed = completed.returncode == 0 and "CUDA0: Orin" in output
    return {"command": [str(binary), "--list-devices"], "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "cuda0_orin_detected": passed}


def preflight(config: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    validate_config(config)
    dependencies = {name: shutil.which(name) for name in ("timeout", "tegrastats", "date")}
    if any(path is None for path in dependencies.values()):
        raise smoke.SmokeError("required launcher dependency missing", "launcher_dependency_missing")
    assets = {"binary": verify_file(root, config["binary"], "binary", executable=True)}
    assets.update({role: verify_file(root, expected, role) for role, expected in config["assets"].items()})
    fixture = verify_file(root, config["fixture"], "fixture")
    references = {role: verify_file(root, expected, role) for role, expected in config["readonly_references"].items()}
    runtime = smoke.git_identity(root / config["runtime"]["path"])
    if runtime["commit"] != config["runtime"]["commit"] or runtime["dirty"]:
        raise smoke.SmokeError("runtime identity is not frozen", "launcher_preflight_failed")
    cuda = host_cuda_preflight(config, root)
    if not cuda["cuda0_orin_detected"]:
        raise smoke.SmokeError("host CUDA preflight did not identify CUDA0: Orin", "cuda_preflight_failed")
    return {"assets": assets, "fixture": fixture, "readonly_references": references, "runtime": runtime, "project": smoke.git_identity(root), "dependencies": dependencies, "cuda_preflight": cuda}


def build_model_command(config: dict[str, Any], root: Path = ROOT) -> list[str]:
    fixed, assets, launcher = config["fixed_parameters"], config["assets"], config["launcher"]
    inference = [
        str(root / config["binary"]["path"]), "--model", str(root / assets["main_model"]["path"]),
        "--mmproj", str(root / assets["mmproj"]["path"]), "--image", str(root / assets["image"]["path"]),
        "--file", str(root / config["fixture"]["path"]), "--ctx-size", str(fixed["context"]),
        "--batch-size", str(fixed["batch"]), "--ubatch-size", str(fixed["ubatch"]), "--gpu-layers", str(fixed["gpu_layers"]),
        "--flash-attn", str(fixed["flash_attention"]), "--temperature", str(fixed["temperature"]), "--seed", str(fixed["seed"]),
        "--predict", str(fixed["max_new_tokens"]), "--mmproj-offload", "--perf", "--offline", "--verbose", "--log-timestamps", "--log-colors", "off", "--no-warmup",
    ]
    forbidden = {"--prompt", "-hf", "-hfr", "--hf-repo", "--model-url", "--mmproj-url"}
    if forbidden.intersection(inference) or "/usr/bin/time" in inference:
        raise smoke.SmokeError("forbidden inference argument", "launcher_preflight_failed")
    return [str(shutil.which("timeout") or "timeout"), "--signal=TERM", f"--kill-after={launcher['timeout_kill_after_seconds']}s", f"{launcher['timeout_seconds']}s", *inference]


def evaluate(run_dir: Path, config: dict[str, Any], prepared: dict[str, Any]) -> dict[str, Any]:
    supervisor = read_json(run_dir / "result.json")
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8", errors="replace")
    stderr = (run_dir / "stderr.log").read_text(encoding="utf-8", errors="replace")
    parsed = smoke.parse_runtime_log(stderr)
    telemetry = smoke.parse_telemetry(run_dir / "tegrastats.log")
    correctness = m7_4c.validate_answer(stdout, config)
    prompt_tokens = parsed["tokens"]["prompt_tokens"]
    prompt_gate = config["fixture"]["direct_prompt_token_min"] <= (prompt_tokens or -1) <= config["fixture"]["direct_prompt_token_max"]
    image_direct = parsed["vision"]["image_tokens"] is not None and parsed["vision"]["image_tokens_measurement_status"] == "DIRECTLY_PARSED_FROM_CLI_LOG"
    output = smoke.summarize_output(stdout)
    child_exit = supervisor["model"]["returncode"]
    runtime_failure = smoke.classify_failure(child_exit if child_exit is not None else 1, stderr, stdout, telemetry["sample_count"] > 0)
    cleanup_ok = supervisor.get("model_cleanup", {}).get("returncode") is not None and supervisor.get("telemetry_cleanup", {}).get("returncode") is not None
    criteria = {
        "host_cuda_preflight": prepared["cuda_preflight"]["cuda0_orin_detected"], "child_exit_code_zero": child_exit == 0,
        "process_groups_cleaned": cleanup_ok, "actual_context_16384": parsed["actual_context"] == 16384,
        "actual_batch_512": parsed["actual_batch"] == 512, "actual_ubatch_512": parsed["actual_ubatch"] == 512,
        "cuda_offload_37_of_37": parsed["offloaded_layers"] == "37/37", "mmproj_cuda": parsed["mmproj_cuda"],
        "kv_cache_16384": parsed["kv_cache"]["cells"] == 16384, "image_tokens_directly_reported": image_direct,
        "vision_and_embedding": all(parsed["vision"][key] for key in ("image_decode_succeeded", "vision_encode_succeeded", "embedding_injection_succeeded")),
        "prompt_tokens_13000_to_14500": prompt_gate, "output_json_and_facts_correct": correctness["passed"],
        "telemetry_sample_present": telemetry["sample_count"] > 0, "no_disqualifying_runtime_error": runtime_failure is None,
    }
    success = all(criteria.values())
    failure = runtime_failure or ("quality_gate_failed" if not correctness["passed"] else "prompt_token_range_failed" if not prompt_gate else "recovery_gate_failed")
    return {
        "schema_version": 1, "milestone": "M7.4C-R", "status": "SUCCESS" if success else "FAILED", "success_gate_passed": success,
        "attempt_ordinal": 2, "previous_inference_attempt_count": 1, "retry_count": 1, "child_exit_code": child_exit,
        "failure_class": None if success else failure, "supervisor_result": "result.json", "process_groups": {"model_cleanup": supervisor.get("model_cleanup"), "telemetry_cleanup": supervisor.get("telemetry_cleanup"), "tegrastats_stopped": cleanup_ok},
        "preflight": prepared, "actual_runtime": {"context": parsed["actual_context"], "batch": parsed["actual_batch"], "ubatch": parsed["actual_ubatch"], "prompt_tokens": prompt_tokens, "output_tokens": parsed["tokens"]["output_tokens"], "image_tokens": parsed["vision"]["image_tokens"], "offloaded_layers": parsed["offloaded_layers"], "mmproj_cuda": parsed["mmproj_cuda"]},
        "kv_cache": parsed["kv_cache"], "vision": parsed["vision"], "timings_ms": parsed["timings_ms"], "telemetry": telemetry, "correctness": correctness,
        "output": {"nonempty": output is not None, "sha256": smoke.sha256_file(run_dir / "stdout.log"), "size_bytes": (run_dir / "stdout.log").stat().st_size}, "success_criteria": criteria,
        "scope": {"single_recovery_smoke": True, "rag": False, "actual_multi_turn_session": False, "performance_or_stability_conclusion": False, "context_32768_executed": False},
    }


def execute(config: dict[str, Any], root: Path = ROOT) -> int:
    prepared = preflight(config, root)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f%z")
    run_dir = root / config["launcher"]["output_root"] / timestamp
    model_command = build_model_command(config, root)
    telemetry_command = [prepared["dependencies"]["tegrastats"], "--interval", str(config["launcher"]["tegrastats_interval_ms"]), "--logfile", str(run_dir / "tegrastats.log")]
    recovery_exit = recovery.execute(run_dir, model_command, telemetry_command, config["launcher"]["cleanup_grace_seconds"])
    write_json(run_dir / "config.snapshot.json", config)
    write_json(run_dir / "preflight.json", prepared)
    write_json(run_dir / "model-command.json", model_command)
    write_json(run_dir / "telemetry-command.json", telemetry_command)
    (run_dir / "model-command.txt").write_text(shlex.join(model_command) + "\n", encoding="utf-8")
    evaluation = evaluate(run_dir, config, prepared)
    evaluation["recovery_runner_exit_code"] = recovery_exit
    write_json(run_dir / "evaluation-result.json", evaluation)
    print(json.dumps({"status": evaluation["status"], "result_directory": str(run_dir), "child_exit_code": evaluation["child_exit_code"], "failure_class": evaluation["failure_class"]}))
    return 0 if evaluation["status"] == "SUCCESS" else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = read_json(args.config)
    validate_config(config)
    plan = {"mode": "execute" if args.execute else "dry-run", "execute_requested": args.execute, "attempt_ordinal": 2, "previous_inference_attempt_count": 1, "retry_count": 1, "model_starts_allowed": 1, "host_cuda_preflight_required": True, "fixture": config["fixture"]["path"], "model_process_started": False, "context_32768_executed": False}
    if not args.execute:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    return execute(config)


if __name__ == "__main__":
    raise SystemExit(main())
