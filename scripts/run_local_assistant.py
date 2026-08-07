#!/usr/bin/env python3
"""Start the local Runtime and unified keyboard Assistant as one foreground process."""
from __future__ import annotations

import argparse
import os
import pathlib
import signal
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.assistant.application import AssistantConfigError, AssistantPreflightError, check_rag, check_runtime, load_config


class LauncherError(RuntimeError):
    pass


def relative_path(value: str) -> pathlib.Path:
    path = pathlib.PurePosixPath(value)
    if not isinstance(value, str) or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise LauncherError("launcher paths must be repository-relative")
    return ROOT / path


def check_runtime_assets(config: dict) -> None:
    runtime = config["runtime"]
    executable = relative_path(runtime["executable"])
    if not executable.is_file() or not executable.stat().st_mode & 0o111:
        raise LauncherError(f"Runtime executable is missing or not executable: {runtime['executable']}")
    for name in ("model", "mmproj"):
        spec = runtime[name]
        path = relative_path(spec["path"])
        if not path.is_file():
            raise LauncherError(f"Runtime {name} is missing: {spec['path']}")
        if path.stat().st_size != spec["size_bytes"]:
            raise LauncherError(f"Runtime {name} size does not match config: {spec['path']}")
    check_rag(config)


def check_port_available(host: str, port: int, socket_factory: Callable[..., socket.socket] = socket.socket) -> None:
    probe = socket_factory(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError as error:
        raise LauncherError(f"Runtime port {host}:{port} is already in use; refusing to reuse an existing Runtime") from error
    finally:
        probe.close()


def runtime_command(config: dict) -> list[str]:
    runtime = config["runtime"]
    return [
        str(relative_path(runtime["executable"])), "--port", str(runtime["port"]),
        "--model", str(relative_path(runtime["model"]["path"])), "--model-size", str(runtime["model"]["size_bytes"]),
        "--model-sha256", runtime["model"]["sha256"],
        "--mmproj", str(relative_path(runtime["mmproj"]["path"])), "--mmproj-size", str(runtime["mmproj"]["size_bytes"]),
        "--mmproj-sha256", runtime["mmproj"]["sha256"],
        "--context", str(runtime["context_tokens"]), "--batch", str(runtime["batch_tokens"]),
        "--ubatch", str(runtime["ubatch_tokens"]), "--gpu-layers", str(runtime["gpu_layers"]),
    ]


def stop_process(process: Any, timeout: float = 5.0) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


class LocalAssistantLauncher:
    def __init__(self, config: dict, *, popen: Callable[..., Any] = subprocess.Popen,
                 sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic,
                 ready_check: Callable[[dict], None] = check_runtime,
                 port_check: Callable[[str, int], None] = check_port_available,
                 asset_check: Callable[[dict], None] = check_runtime_assets,
                 config_path: str | pathlib.Path = "configs/assistant.json"):
        self.config, self.popen, self.sleep, self.monotonic = config, popen, sleep, monotonic
        self.ready_check, self.port_check, self.asset_check = ready_check, port_check, asset_check
        self.config_path = str(config_path)
        self.runtime: Any = None
        self.assistant: Any = None
        self.runtime_log_path: pathlib.Path | None = None
        self._keep_runtime_log = False

    def _runtime_log_hint(self) -> str:
        return f"; Runtime log: {self.runtime_log_path}" if self.runtime_log_path else ""

    def _start_runtime(self) -> None:
        descriptor, raw_path = tempfile.mkstemp(prefix="edgeomni-runtime-", suffix=".log")
        self.runtime_log_path = pathlib.Path(raw_path)
        with os.fdopen(descriptor, "wb") as log_file:
            try:
                self.runtime = self.popen(runtime_command(self.config), cwd=str(ROOT),
                                          stdout=log_file, stderr=log_file)
            except OSError:
                self._keep_runtime_log = True
                raise

    def wait_until_ready(self, timeout_seconds: float) -> None:
        deadline = self.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while self.monotonic() < deadline:
            if self.runtime.poll() is not None:
                self._keep_runtime_log = True
                raise LauncherError(f"Runtime exited before /ready (exit {self.runtime.returncode}){self._runtime_log_hint()}")
            try:
                self.ready_check(self.config)
                return
            except AssistantPreflightError as error:
                last_error = error
                self.sleep(0.2)
        detail = f": {last_error}" if last_error else ""
        self._keep_runtime_log = True
        raise LauncherError(f"Runtime did not become ready within {timeout_seconds:g} seconds{detail}{self._runtime_log_hint()}")

    def run(self, speak: bool, ready_timeout: float) -> int:
        runtime = self.config["runtime"]
        self.asset_check(self.config)
        self.port_check(runtime["host"], runtime["port"])
        print(f"launcher: starting Runtime at {runtime['base_url']}", file=sys.stderr, flush=True)
        try:
            self._start_runtime()
        except OSError as error:
            raise LauncherError(f"Could not start Runtime: {error}{self._runtime_log_hint()}") from error
        try:
            self.wait_until_ready(ready_timeout)
            print("launcher: Runtime ready; starting Assistant", file=sys.stderr, flush=True)
            command = [sys.executable, str(ROOT / "scripts" / "run_assistant.py"), "--config", self.config_path]
            if speak:
                command.append("--speak")
            try:
                self.assistant = self.popen(command, cwd=str(ROOT))
            except OSError as error:
                raise LauncherError(f"Could not start unified Assistant: {error}") from error
            return self.assistant.wait()
        finally:
            # Assistant is stopped before Runtime, so no request can outlive its service.
            stop_process(self.assistant)
            stop_process(self.runtime)
            if self.runtime_log_path and not self._keep_runtime_log:
                try:
                    self.runtime_log_path.unlink()
                except OSError:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/assistant.json")
    parser.add_argument("--speak", action="store_true", help="enable optional TTS lazily; ASR is not preflighted")
    parser.add_argument("--ready-timeout", type=float, default=120.0)
    args = parser.parse_args()
    if args.ready_timeout <= 0:
        parser.error("--ready-timeout must be positive")
    def interrupt(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt
    previous_int = signal.signal(signal.SIGINT, interrupt)
    previous_term = signal.signal(signal.SIGTERM, interrupt)
    try:
        launcher = LocalAssistantLauncher(load_config(args.config), config_path=args.config)
        return launcher.run(args.speak, args.ready_timeout)
    except KeyboardInterrupt:
        return 130
    except (AssistantConfigError, AssistantPreflightError, LauncherError, OSError, ValueError) as error:
        print(f"launcher: {error}", file=sys.stderr)
        return 2
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    raise SystemExit(main())
