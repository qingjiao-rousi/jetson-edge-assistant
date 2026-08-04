#!/usr/bin/env python3
"""Process-group supervisor for a future, explicitly authorized VLM recovery run.

This utility does not construct a model command and does not run one unless --execute
is provided with an already-audited argv JSON file.  It exists so a launcher can retain
the child's real return code and clean up both the model process group and tegrastats.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    os.replace(temporary, path)


def read_argv(path: Path) -> list[str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValueError("command JSON must be a non-empty JSON string array")
    return value


def terminate_process_group(process: subprocess.Popen[Any] | None, grace_seconds: float) -> dict[str, Any]:
    if process is None:
        return {"started": False, "returncode": None, "term_sent": False, "kill_sent": False}
    result = {"started": True, "pid": process.pid, "returncode": process.poll(), "term_sent": False, "kill_sent": False}
    if result["returncode"] is not None:
        return result
    try:
        os.killpg(process.pid, signal.SIGTERM)
        result["term_sent"] = True
    except ProcessLookupError:
        result["returncode"] = process.poll()
        return result
    try:
        result["returncode"] = process.wait(timeout=grace_seconds)
        return result
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
        result["kill_sent"] = True
    except ProcessLookupError:
        pass
    result["returncode"] = process.wait(timeout=grace_seconds)
    return result


def classify_returncode(returncode: int | None) -> str | None:
    if returncode is None:
        return "runner_internal"
    if returncode == 0:
        return None
    if returncode < 0:
        return "process_signal_termination"
    if returncode in (124, 137):
        return "timeout_or_kill"
    return "model_process_nonzero_exit"


def dry_run_plan(model_argv: list[str], telemetry_argv: list[str]) -> dict[str, Any]:
    return {
        "mode": "dry-run",
        "model_process_started": False,
        "model_argv": model_argv,
        "telemetry_argv": telemetry_argv,
        "start_new_session": True,
        "cleanup_strategy": "SIGTERM process group, then SIGKILL after grace period",
        "result_recording": "atomic status before spawn and atomic final result after child wait",
    }


def execute(run_dir: Path, model_argv: list[str], telemetry_argv: list[str], grace_seconds: float) -> int:
    run_dir.mkdir(parents=True, exist_ok=False)
    result_path = run_dir / "result.json"
    model_stdout = (run_dir / "stdout.log").open("w", encoding="utf-8")
    model_stderr = (run_dir / "stderr.log").open("w", encoding="utf-8")
    telemetry_stdout = (run_dir / "tegrastats.stdout.log").open("w", encoding="utf-8")
    telemetry_stderr = (run_dir / "tegrastats.stderr.log").open("w", encoding="utf-8")
    state: dict[str, Any] = {
        "schema_version": 1,
        "status": "STARTING",
        "model_argv": model_argv,
        "telemetry_argv": telemetry_argv,
        "model": {"started": False, "returncode": None},
        "telemetry": {"started": False, "returncode": None},
        "failure_class": None,
        "events": ["result_recorded_before_spawn"],
    }
    interrupted_signal: int | None = None

    def interrupt_handler(signum: int, _frame: Any) -> None:
        nonlocal interrupted_signal
        interrupted_signal = signum
        raise KeyboardInterrupt(f"received signal {signum}")

    previous_handlers = {
        signum: signal.signal(signum, interrupt_handler)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    write_json_atomic(result_path, state)
    model: subprocess.Popen[Any] | None = None
    telemetry: subprocess.Popen[Any] | None = None
    try:
        telemetry = subprocess.Popen(
            telemetry_argv,
            stdout=telemetry_stdout,
            stderr=telemetry_stderr,
            text=True,
            start_new_session=True,
        )
        state["telemetry"] = {"started": True, "pid": telemetry.pid, "returncode": None}
        state["events"].append("telemetry_spawned")
        write_json_atomic(result_path, state)
        model = subprocess.Popen(
            model_argv,
            stdout=model_stdout,
            stderr=model_stderr,
            text=True,
            start_new_session=True,
        )
        state["status"] = "RUNNING"
        state["model"] = {"started": True, "pid": model.pid, "returncode": None}
        state["events"].append("model_spawned")
        write_json_atomic(result_path, state)
        state["model"]["returncode"] = model.wait()
        state["events"].append("model_wait_completed")
        state["failure_class"] = classify_returncode(state["model"]["returncode"])
        state["status"] = "COMPLETED" if state["failure_class"] is None else "FAILED"
    except BaseException as error:
        state["status"] = "INTERRUPTED"
        state["failure_class"] = "runner_interrupted"
        state["exception"] = f"{type(error).__name__}: {error}"
        state["interrupted_signal"] = interrupted_signal
        state["events"].append("runner_exception")
    finally:
        for signum, previous_handler in previous_handlers.items():
            signal.signal(signum, previous_handler)
        state["model_cleanup"] = terminate_process_group(model, grace_seconds)
        state["telemetry_cleanup"] = terminate_process_group(telemetry, grace_seconds)
        if state["model"].get("started"):
            state["model"]["returncode"] = state["model_cleanup"]["returncode"]
        if state["telemetry"].get("started"):
            state["telemetry"]["returncode"] = state["telemetry_cleanup"]["returncode"]
        state["events"].append("process_groups_cleaned")
        write_json_atomic(result_path, state)
        model_stdout.close()
        model_stderr.close()
        telemetry_stdout.close()
        telemetry_stderr.close()
    print(json.dumps({"status": state["status"], "result": str(result_path), "model_exit_code": state["model"].get("returncode")}))
    return 0 if state["status"] == "COMPLETED" else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-command-json", type=Path, required=True)
    parser.add_argument("--telemetry-command-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--grace-seconds", type=float, default=5.0)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.grace_seconds <= 0:
        raise ValueError("grace seconds must be positive")
    model_argv = read_argv(args.model_command_json)
    telemetry_argv = read_argv(args.telemetry_command_json)
    if not args.execute:
        print(json.dumps(dry_run_plan(model_argv, telemetry_argv), ensure_ascii=False, indent=2))
        return 0
    return execute(args.output_dir, model_argv, telemetry_argv, args.grace_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
