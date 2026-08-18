#!/usr/bin/env python3
"""Validate real MtmdBackend single-hot Prefix Reuse correctness on Jetson.

This is a correctness runner, not a benchmark collector. It starts isolated
disabled and single_hot_text Runtime processes and emits one JSON report.
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_jetson_benchmark import load_benchmark_image
from run_local_assistant import check_port_available, check_runtime_assets, runtime_command, stop_process
from app.assistant.application import check_runtime, load_config


class ValidationError(RuntimeError):
    pass


def post(base_url: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        base_url + path, data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=130) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def get(base_url: str, path: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(base_url + path, method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def chat(config: dict[str, Any], request_id: str, prompt: str, session_id: str, timeout_ms: int = 120000) -> tuple[int, dict[str, Any]]:
    runtime = config["runtime"]
    return post(runtime["base_url"], runtime["chat_endpoint"], {
        "request_id": request_id, "session_id": session_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_new_tokens": 128, "timeout_ms": timeout_ms, "stream": False,
        "model_sha256": runtime["model"]["sha256"],
        "sampling": {"seed": 424242, "top_k": 1, "top_p": 1.0, "min_p": 0.0, "temperature": 0.0},
    })


def diagnose(config: dict[str, Any], request_id: str, prompt: str, image: tuple[str, bytes, str, str]) -> tuple[int, dict[str, Any]]:
    path, data, mime, _ = image
    return post(config["runtime"]["base_url"], "/v1/diagnose/image", {
        "request_id": request_id, "prompt": prompt, "stream": False,
        "images": [{"id": path, "mime": mime, "data_base64": base64.b64encode(data).decode("ascii")}],
    })


class RuntimeProcess:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.process: subprocess.Popen[bytes] | None = None
        self.log_path: pathlib.Path | None = None
        self.log_file: Any = None

    def _stop(self) -> None:
        stop_process(self.process)
        self.process = None
        if self.log_file is not None:
            self.log_file.close()
            self.log_file = None

    def __enter__(self) -> "RuntimeProcess":
        runtime = self.config["runtime"]
        check_port_available(runtime["host"], runtime["port"])
        descriptor, raw_path = tempfile.mkstemp(prefix="edgeomni-prefix-validation-", suffix=".log")
        self.log_path = pathlib.Path(raw_path)
        self.log_file = open(descriptor, "wb", closefd=True)
        self.process = subprocess.Popen(runtime_command(self.config), cwd=ROOT, stdout=self.log_file, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                returncode = self.process.returncode
                self.log_file.flush()
                detail = self.log_path.read_text(encoding="utf-8", errors="replace")[-1000:]
                self._stop()
                raise ValidationError(f"Runtime exited before /ready ({returncode}): {detail}")
            try:
                check_runtime(self.config)
                return self
            except Exception:
                time.sleep(0.2)
        log_path = self.log_path
        self._stop()
        raise ValidationError(f"Runtime did not become ready within 180 seconds; inspect {log_path}")

    def __exit__(self, *_: object) -> None:
        self._stop()


def require(condition: bool, name: str, detail: str = "") -> dict[str, Any]:
    return {"name": name, "passed": condition, "detail": detail}


def metrics(response: dict[str, Any]) -> dict[str, Any]:
    value = response.get("metrics")
    return value if isinstance(value, dict) else {}


def classify_prefix_reuse(response: dict[str, Any], batch_tokens: int) -> dict[str, Any]:
    """Classify single-hot cache telemetry against the configured batch boundary.

    The Runtime can safely retain only complete cold-prefill batches.  Therefore
    an otherwise-correct prompt shorter than ``batch_tokens`` is expected to
    have no reusable prefix rather than being treated as a reuse failure.
    """
    telemetry = metrics(response)
    prompt_tokens = response.get("prompt_tokens")
    hit_tokens = telemetry.get("cache_hit_tokens")
    miss_tokens = telemetry.get("cache_miss_tokens")
    result: dict[str, Any] = {
        "batch_tokens": batch_tokens,
        "prompt_tokens": prompt_tokens,
        "cache_hit_tokens": hit_tokens,
        "cache_miss_tokens": miss_tokens,
        "classification": "FAIL",
        "reason": "",
    }
    if not isinstance(batch_tokens, int) or isinstance(batch_tokens, bool) or batch_tokens <= 0:
        result["reason"] = "invalid batch_tokens"
        return result
    numeric_values = (prompt_tokens, hit_tokens, miss_tokens)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in numeric_values):
        result["reason"] = "prompt/cache telemetry must be integer tokens"
        return result
    if prompt_tokens < 0 or hit_tokens < 0 or miss_tokens < 0:
        result["reason"] = "prompt/cache telemetry must be non-negative"
        return result
    if hit_tokens > prompt_tokens:
        result["reason"] = "cache_hit_tokens exceeds prompt_tokens"
        return result
    if hit_tokens + miss_tokens != prompt_tokens:
        result["reason"] = "cache_hit_tokens + cache_miss_tokens != prompt_tokens"
        return result
    if prompt_tokens < batch_tokens:
        if hit_tokens == 0 and miss_tokens == prompt_tokens:
            result["classification"] = "PASS_EXPECTED_NO_REUSE"
        else:
            result["reason"] = "prompt below batch boundary must have zero hit and full miss"
        return result
    if hit_tokens > 0:
        result["classification"] = "PASS_REUSE"
    else:
        result["reason"] = "prompt at or above batch boundary must have a positive cache hit"
    return result


def run_disabled(config: dict[str, Any], prompt: str, label: str) -> dict[str, Any]:
    with RuntimeProcess(config):
        status, response = chat(config, f"cold-{label}-{uuid.uuid4().hex}", prompt, "cold-session")
    if status != 200 or response.get("error") is not None:
        raise ValidationError(f"disabled cold {label} failed: HTTP {status} {response}")
    return response


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disabled-config", default="configs/assistant.json")
    parser.add_argument("--hot-config", default="configs/assistant-prefix-single-hot.json")
    parser.add_argument("--prompt-file", required=True, help="repository-relative or absolute UTF-8 text prompt")
    parser.add_argument("--branch-prompt-file", required=True, help="same-prefix branch prompt")
    parser.add_argument("--image", default="tests/fixtures/vlm-service/synthetic-alarm-panel.png")
    parser.add_argument("--output", help="optional JSON result path inside the repository")
    args = parser.parse_args()

    prompt_path = pathlib.Path(args.prompt_file).resolve()
    branch_path = pathlib.Path(args.branch_prompt_file).resolve()
    if not prompt_path.is_file() or not branch_path.is_file():
        parser.error("--prompt-file and --branch-prompt-file must exist")
    prompt, branch = prompt_path.read_text(encoding="utf-8"), branch_path.read_text(encoding="utf-8")
    if not prompt or not branch or prompt == branch:
        parser.error("prompts must be non-empty and different")
    image = load_benchmark_image(args.image)
    disabled, hot = load_config(args.disabled_config), load_config(args.hot_config)
    if disabled["runtime"]["prefix_reuse"] != "disabled" or hot["runtime"]["prefix_reuse"] != "single_hot_text":
        parser.error("configs must explicitly use disabled and single_hot_text")
    disabled_batch = disabled["runtime"].get("batch_tokens")
    hot_batch = hot["runtime"].get("batch_tokens")
    if (not isinstance(disabled_batch, int) or isinstance(disabled_batch, bool) or disabled_batch <= 0 or
            not isinstance(hot_batch, int) or isinstance(hot_batch, bool) or hot_batch <= 0):
        parser.error("configs must define a positive integer runtime.batch_tokens")
    if disabled_batch != hot_batch:
        parser.error("disabled and single_hot_text configs must use the same runtime.batch_tokens")
    batch_tokens = hot_batch
    for config in (disabled, hot): check_runtime_assets(config)

    cold_exact = run_disabled(disabled, prompt, "exact")
    cold_branch = run_disabled(disabled, branch, "branch")
    checks: list[dict[str, Any]] = []
    with RuntimeProcess(hot):
        status, warm = chat(hot, f"warm-{uuid.uuid4().hex}", prompt, "alpha")
        checks.append(require(status == 200 and warm.get("error") is None, "warm_text"))
        status, exact = chat(hot, f"exact-{uuid.uuid4().hex}", prompt, "alpha")
        exact_reuse = classify_prefix_reuse(exact, batch_tokens)
        checks += [
            require(status == 200 and exact.get("error") is None and exact.get("text") == cold_exact.get("text"), "exact_output_matches_cold"),
            require(exact_reuse["classification"] != "FAIL", "exact_prefix_reuse_classification", json.dumps(exact_reuse, sort_keys=True)),
        ]
        status, branch_hot = chat(hot, f"branch-{uuid.uuid4().hex}", branch, "alpha")
        branch_reuse = classify_prefix_reuse(branch_hot, batch_tokens)
        checks += [
            require(status == 200 and branch_hot.get("error") is None and branch_hot.get("text") == cold_branch.get("text"), "branch_output_matches_cold"),
            require(branch_reuse["classification"] != "FAIL", "branch_prefix_reuse_classification", json.dumps(branch_reuse, sort_keys=True)),
        ]
        status, switched = chat(hot, f"switch-{uuid.uuid4().hex}", prompt, "beta")
        switched_metrics = metrics(switched)
        checks.append(require(status == 200 and switched_metrics.get("cache_hit_tokens") == 0 and switched_metrics.get("cache_invalidation_reason") == "session_id_changed", "session_switch_invalidates", str(switched_metrics)))
        status, image_response = diagnose(hot, f"image-{uuid.uuid4().hex}", "Describe only directly observable abnormalities.", image)
        checks.append(require(status == 200 and image_response.get("error") is None, "image_request_succeeds"))
        status, after_image = chat(hot, f"after-image-{uuid.uuid4().hex}", prompt, "alpha")
        checks.append(require(status == 200 and metrics(after_image).get("cache_hit_tokens") == 0, "image_invalidates_text_kv", str(metrics(after_image))))
        status, timeout = chat(hot, f"timeout-{uuid.uuid4().hex}", prompt, "alpha", timeout_ms=1)
        checks.append(require(status == 408 and timeout.get("error", {}).get("code") == "timeout", "timeout_is_reported"))
        status, after_timeout = chat(hot, f"after-timeout-{uuid.uuid4().hex}", prompt, "alpha")
        checks.append(require(status == 200 and metrics(after_timeout).get("cache_hit_tokens") == 0, "timeout_invalidates_text_kv", str(metrics(after_timeout))))
        cancel_id = f"cancel-{uuid.uuid4().hex}"
        cancelled: list[tuple[int, dict[str, Any]]] = []
        worker = threading.Thread(target=lambda: cancelled.append(chat(hot, cancel_id, prompt, "alpha")))
        worker.start()
        active = False
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                _, state = get(hot["runtime"]["base_url"], "/metrics")
                if state.get("active") == 1:
                    active = True
                    break
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            time.sleep(0.02)
        if active:
            cancel_status, cancel_response = post(hot["runtime"]["base_url"], f"/v1/cancel/{cancel_id}", {})
            worker.join(timeout=130)
            checks.append(require(cancel_status == 200 and cancel_response.get("cancelled") is True and cancelled and cancelled[0][0] == 499,
                                  "cancel_is_reported", str(cancelled[0] if cancelled else None)))
        else:
            worker.join(timeout=130)
            checks.append(require(False, "cancel_is_reported", "request never became active"))
        status, after_cancel = chat(hot, f"after-cancel-{uuid.uuid4().hex}", prompt, "alpha")
        checks.append(require(status == 200 and metrics(after_cancel).get("cache_hit_tokens") == 0, "cancel_invalidates_text_kv", str(metrics(after_cancel))))
        status, reset = post(hot["runtime"]["base_url"], "/v1/context/reset", {})
        checks.append(require(status == 200 and reset.get("reset") is True, "context_reset_succeeds"))
        status, after_reset = chat(hot, f"after-reset-{uuid.uuid4().hex}", prompt, "alpha")
        checks.append(require(status == 200 and metrics(after_reset).get("cache_hit_tokens") == 0, "reset_invalidates_text_kv", str(metrics(after_reset))))

    report = {"schema_version": 2, "status": "PASS" if all(item["passed"] for item in checks) else "FAIL",
              "disabled_config": args.disabled_config, "hot_config": args.hot_config,
              "prompt_sha256": __import__("hashlib").sha256(prompt.encode()).hexdigest(),
              "branch_prompt_sha256": __import__("hashlib").sha256(branch.encode()).hexdigest(),
              "prefix_reuse": {"batch_tokens": batch_tokens, "exact": exact_reuse, "branch": branch_reuse},
              "checks": checks}
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = pathlib.Path(args.output).resolve()
        if not output.is_relative_to(ROOT): parser.error("--output must stay inside the repository")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
