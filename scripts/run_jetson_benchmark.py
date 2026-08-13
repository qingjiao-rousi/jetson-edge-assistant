#!/usr/bin/env python3
"""Run a persistent EdgeOmni Runtime text or fixed single-image baseline."""

from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import os
import pathlib
import platform
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import re
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.assistant.application import check_runtime, load_config
from run_local_assistant import check_port_available, check_runtime_assets, runtime_command, stop_process


DEFAULT_PROMPT = "Summarize the safe first inspection steps for an industrial equipment alarm."
DEFAULT_IMAGE_PROMPT = "Describe the visible panel state and list only directly observable abnormalities."
DIAGNOSIS_ENDPOINT = "/v1/diagnose/image"


def git_source_state() -> tuple[str, bool, int, str]:
    commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=all"],
        text=True,
    )
    entries = len(status.splitlines())
    return commit, not status, entries, hashlib.sha256(status.encode("utf-8")).hexdigest()


def jetson_clock_status(output: str) -> tuple[bool, str]:
    cpu_ranges = [
        (int(low), int(high))
        for low, high in re.findall(r"cpu\d+:.*?MinFreq=(\d+) MaxFreq=(\d+)", output)
    ]
    gpu = re.search(r"GPU MinFreq=(\d+) MaxFreq=(\d+)", output)
    emc = re.search(r"EMC .*?FreqOverride=(\d+)", output)
    if not cpu_ranges or gpu is None or emc is None:
        return False, "jetson_clocks output did not contain CPU/GPU/EMC lock fields"
    cpu_locked = all(low == high for low, high in cpu_ranges)
    gpu_locked = gpu.group(1) == gpu.group(2)
    emc_locked = emc.group(1) == "1"
    if cpu_locked and gpu_locked and emc_locked:
        return True, "CPU/GPU clocks fixed and EMC override enabled"
    return False, f"dynamic clocks detected (cpu_locked={cpu_locked}, gpu_locked={gpu_locked}, emc_locked={emc_locked})"


def read_jetson_clock_status() -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            ["sudo", "-n", "/usr/bin/jetson_clocks", "--show"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"could not execute jetson_clocks: {error}", ""
    output = result.stdout + result.stderr
    if result.returncode != 0:
        return False, "cannot inspect clocks non-interactively; run 'sudo -v' first", output
    locked, detail = jetson_clock_status(output)
    return locked, detail, output


def load_benchmark_image(value: str) -> tuple[str, bytes, str, str]:
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError("--image must be an existing file inside the repository")
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith((b"RIFF",)) and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ValueError("--image must be a PNG, JPEG, or WebP file")
    relative = path.relative_to(ROOT).as_posix()
    return relative, data, mime, hashlib.sha256(data).hexdigest()


def runtime_request(config: dict[str, Any], request_id: str, prompt: str, max_new_tokens: int,
                    image: tuple[str, bytes, str, str] | None = None) -> dict[str, Any]:
    if image is not None:
        image_path, image_bytes, image_mime, _image_sha256 = image
        return {
            "request_id": request_id,
            "prompt": prompt,
            "stream": False,
            "images": [{
                "id": image_path,
                "mime": image_mime,
                "data_base64": base64.b64encode(image_bytes).decode("ascii"),
            }],
        }
    runtime = config["runtime"]
    return {
        "request_id": request_id,
        # A single deterministic session lets the OPT-1 experiment exercise
        # the Runtime's one-hot text KV policy. Image workloads intentionally
        # use the separate diagnosis contract and do not carry this key.
        "session_id": "benchmark-prefix-session",
        "messages": [{"role": "user", "content": prompt}],
        "max_new_tokens": max_new_tokens,
        "timeout_ms": 120000,
        "stream": False,
        "model_sha256": runtime["model"]["sha256"],
        "sampling": {"seed": 424242, "top_k": 1, "top_p": 1.0, "min_p": 0.0, "temperature": 0.0},
    }


def post_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=130) as response:
            payload = json.loads(response.read().decode("utf-8"))
            status = response.status
    except urllib.error.HTTPError as error:
        payload = json.loads(error.read().decode("utf-8"))
        status = error.code
    if not isinstance(payload, dict):
        raise RuntimeError("Runtime returned a non-object JSON response")
    payload["client_http_status"] = status
    payload["client_total_ms"] = round((time.monotonic() - started) * 1000, 3)
    return payload


def wait_ready(config: dict[str, Any], process: subprocess.Popen[bytes], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Runtime exited before /ready (exit {process.returncode})")
        try:
            check_runtime(config)
            return
        except Exception as error:  # Preserve the final readiness diagnostic.
            last_error = error
            time.sleep(0.2)
    raise RuntimeError(f"Runtime did not become ready: {last_error}")


def environment_lines(config: dict[str, Any], label: str, prompt: str, repeats: int,
                      clocks_locked: bool, clock_detail: str, git_commit: str,
                      worktree_clean: bool, git_status_entries: int,
                      git_status_sha256: str,
                      image: tuple[str, bytes, str, str] | None = None,
                      max_new_tokens: int = 128) -> list[str]:
    runtime = config["runtime"]
    lines = [
        "status=UNREVIEWED_RAW_RESULT",
        f"timestamp_utc={datetime.datetime.now(datetime.timezone.utc).isoformat()}",
        f"git_commit={git_commit}",
        f"git_worktree_clean={str(worktree_clean).lower()}",
        f"git_status_entries={git_status_entries}",
        f"git_status_sha256={git_status_sha256}",
        f"label={label}",
        f"model_path={runtime['model']['path']}",
        f"model_sha256={runtime['model']['sha256']}",
        f"mmproj_path={runtime['mmproj']['path']}",
        f"mmproj_sha256={runtime['mmproj']['sha256']}",
        f"prompt_sha256={hashlib.sha256(prompt.encode('utf-8')).hexdigest()}",
        f"workload={'single_image' if image is not None else 'text'}",
        f"endpoint={DIAGNOSIS_ENDPOINT if image is not None else runtime['chat_endpoint']}",
        f"max_new_tokens={max_new_tokens}",
        f"repeats={repeats}",
        f"clocks_locked={str(clocks_locked).lower()}",
        f"clock_status={clock_detail}",
        f"platform={platform.platform()}",
        f"machine={platform.machine()}",
    ]
    if image is not None:
        image_path, image_bytes, image_mime, image_sha256 = image
        lines.extend([
            f"image_path={image_path}",
            f"image_mime={image_mime}",
            f"image_bytes={len(image_bytes)}",
            f"image_sha256={image_sha256}",
        ])
    tegra_release = pathlib.Path("/etc/nv_tegra_release")
    if tegra_release.is_file():
        lines.append(f"nv_tegra_release={tegra_release.read_text(encoding='utf-8').splitlines()[0]}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/assistant.json", help="complete Q4/Q8 assistant asset contract")
    parser.add_argument("--label", help="filesystem-safe result label, for example q4-k-m")
    parser.add_argument("--output", default="benchmarks/results")
    parser.add_argument("--repeats", type=int, default=15)
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file", help="UTF-8 text prompt file; binds long synthetic inputs without shell interpolation")
    parser.add_argument("--image", help="repository-relative PNG, JPEG, or WebP fixture for a single-image run")
    parser.add_argument("--tegrastats", help="optional tegrastats executable path")
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--allow-dynamic-clocks", action="store_true", help="mark an exploratory run instead of requiring fixed clocks")
    parser.add_argument("--allow-dirty-worktree", action="store_true", help="allow an exploratory run from uncommitted source")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print("dry-run: HTTP VLM benchmark contract parsed; no Runtime started and no output written")
        return 0
    if not args.label or not args.label.replace("-", "").replace("_", "").isalnum():
        parser.error("--label is required and may contain letters, digits, '-' and '_'")
    if args.repeats < 1 or args.max_new_tokens < 1 or args.ready_timeout <= 0:
        parser.error("repeats, max-new-tokens, and ready-timeout must be positive")
    try:
        image = load_benchmark_image(args.image) if args.image else None
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if image is not None and args.max_new_tokens != 128:
        parser.error("the /v1/diagnose/image contract fixes max-new-tokens at 128")
    if args.prompt and args.prompt_file:
        parser.error("--prompt and --prompt-file are mutually exclusive")
    prompt_file = pathlib.Path(args.prompt_file).resolve() if args.prompt_file else None
    if prompt_file is not None:
        if not prompt_file.is_file():
            parser.error("--prompt-file must be an existing file")
        try:
            prompt = prompt_file.read_text(encoding="utf-8")
        except OSError as error:
            parser.error(f"could not read --prompt-file: {error}")
        if not prompt:
            parser.error("--prompt-file must not be empty")
    else:
        prompt = args.prompt or (DEFAULT_IMAGE_PROMPT if image is not None else DEFAULT_PROMPT)

    git_commit, worktree_clean, git_status_entries, git_status_sha256 = git_source_state()
    if not worktree_clean and not args.allow_dirty_worktree:
        raise RuntimeError(
            f"a clean Git worktree is required for a reproducible benchmark ({git_status_entries} status entries); "
            "commit or stash the intended source first. Use --allow-dirty-worktree only for exploratory data."
        )

    config = load_config(args.config)
    check_runtime_assets(config)
    runtime = config["runtime"]
    check_port_available(runtime["host"], runtime["port"])
    clocks_locked, clock_detail, clock_output = read_jetson_clock_status()
    if not clocks_locked and not args.allow_dynamic_clocks:
        raise RuntimeError(
            f"fixed Jetson clocks are required: {clock_detail}. Run 'sudo jetson_clocks', "
            "then 'sudo -v', then retry. Use --allow-dynamic-clocks only for exploratory data."
        )

    output_dir = (ROOT / args.output).resolve()
    if not output_dir.is_relative_to(ROOT):
        parser.error("--output must stay inside the repository")
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%SZ}-{args.label}"
    jsonl_path = output_dir / f"{run_id}.jsonl"
    environment_path = output_dir / f"{run_id}-environment.txt"
    runtime_log_path = output_dir / f"{run_id}-runtime.log"
    tegrastats_path = output_dir / f"{run_id}-tegrastats.log"
    environment_path.write_text(
        "\n".join(environment_lines(
            config, args.label, prompt, args.repeats, clocks_locked, clock_detail,
            git_commit, worktree_clean, git_status_entries, git_status_sha256,
            image, args.max_new_tokens,
        ))
        + "\njetson_clocks_show_begin\n" + clock_output + "jetson_clocks_show_end\n",
        encoding="utf-8",
    )
    if prompt_file is not None:
        with environment_path.open("a", encoding="utf-8") as environment:
            environment.write(f"prompt_file={prompt_file}\n")
            environment.write(f"prompt_bytes={len(prompt.encode('utf-8'))}\n")

    runtime_process: subprocess.Popen[bytes] | None = None
    tegrastats_process: subprocess.Popen[bytes] | None = None
    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        with runtime_log_path.open("wb") as runtime_log:
            runtime_process = subprocess.Popen(runtime_command(config), cwd=ROOT, stdout=runtime_log, stderr=runtime_log)
        wait_ready(config, runtime_process, args.ready_timeout)
        if args.tegrastats:
            with tegrastats_path.open("wb") as telemetry:
                tegrastats_process = subprocess.Popen([args.tegrastats, "--interval", "1000"], stdout=telemetry, stderr=subprocess.STDOUT)
        endpoint = runtime["base_url"].rstrip("/") + (DIAGNOSIS_ENDPOINT if image is not None else runtime["chat_endpoint"])
        warmup = runtime_request(config, f"warmup-{uuid.uuid4().hex}", prompt, args.max_new_tokens, image)
        warmup_response = post_json(endpoint, warmup)
        if warmup_response.get("client_http_status") != 200:
            raise RuntimeError(f"warm-up failed: {warmup_response}")
        with jsonl_path.open("w", encoding="utf-8") as output:
            for index in range(1, args.repeats + 1):
                print(f"benchmark: sample {index}/{args.repeats}", file=sys.stderr, flush=True)
                body = runtime_request(config, f"measure-{index}-{uuid.uuid4().hex}", prompt, args.max_new_tokens, image)
                result = post_json(endpoint, body)
                result["sample_index"] = index
                result["workload"] = "single_image" if image is not None else "text"
                if image is not None:
                    result["image_sha256"] = image[3]
                output.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
                output.flush()
                if result.get("client_http_status") != 200:
                    raise RuntimeError(f"sample {index} failed; raw result retained")
    finally:
        stop_process(tegrastats_process)
        stop_process(runtime_process)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)

    print(f"raw benchmark complete: {jsonl_path}")
    print("status remains UNREVIEWED until protocol fields are copied into a reviewed result table")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
