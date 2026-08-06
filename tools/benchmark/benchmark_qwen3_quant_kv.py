#!/usr/bin/env python3
"""DirectBackend-only Qwen3 Q4_K_M/Q8_0 benchmark orchestrator.

The default mode is a read-only preflight/plan.  Model execution requires the
explicit --execute flag; no llama-cli subprocess is ever used.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TYPE_NAMES = {7: "Q8_0", 15: "Q4_K_M", 1: "F16", 32: "BF16"}
TYPES = {"q4_k_m": "Q4_K_M", "q8_0": "Q8_0"}


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def read_gguf_metadata(path: Path) -> dict[str, Any]:
    """Read GGUF header/KV values without loading tensors or initializing llama."""
    import struct

    scalar = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
    wanted = {"general.architecture", "general.file_type", "general.quantization_version", "tokenizer.chat_template", "qwen3.context_length", "qwen3.block_count", "general.basename", "general.finetune"}

    def string(stream):
        size = struct.unpack("<Q", stream.read(8))[0]
        return stream.read(size).decode("utf-8", "replace")

    def value(stream, kind):
        if kind == 8:
            return string(stream)
        if kind == 9:
            subtype = struct.unpack("<I", stream.read(4))[0]
            size = struct.unpack("<Q", stream.read(8))[0]
            if subtype == 8:
                return [string(stream) for _ in range(size)]
            if subtype not in scalar:
                raise ValueError(f"unsupported GGUF array type {subtype}")
            fmt = scalar[subtype]
            raw = stream.read(struct.calcsize("<" + fmt) * size)
            return list(struct.unpack("<" + fmt * size, raw))
        if kind not in scalar:
            raise ValueError(f"unsupported GGUF value type {kind}")
        fmt = scalar[kind]
        return struct.unpack("<" + fmt, stream.read(struct.calcsize("<" + fmt)))[0]

    with path.open("rb") as stream:
        if stream.read(4) != b"GGUF":
            raise ValueError("invalid GGUF magic")
        version, tensor_count, kv_count = struct.unpack("<IQQ", stream.read(20))
        metadata: dict[str, Any] = {}
        for _ in range(kv_count):
            key = string(stream)
            kind = struct.unpack("<I", stream.read(4))[0]
            parsed = value(stream, kind)
            if key in wanted:
                metadata[key] = parsed
    template = metadata.get("tokenizer.chat_template")
    return {
        "gguf_version": version,
        "tensor_count": tensor_count,
        "metadata": metadata,
        "chat_template_present": isinstance(template, str) and bool(template),
        "chat_template_bytes": len(template.encode()) if isinstance(template, str) else 0,
        "chat_template_sha256": hashlib.sha256(template.encode()).hexdigest() if isinstance(template, str) else None,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"required file does not exist: {path}")
    return {"path": str(path.resolve()), "sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def git_identity(path: Path) -> dict[str, Any]:
    """Capture a repository/submodule identity, including a detached HEAD."""
    def query(*argv: str) -> str:
        result = subprocess.run(["git", "-C", str(path), *argv], capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"git {' '.join(argv)} failed")
        return result.stdout.strip()

    try:
        return {
            "path": str(path.resolve()),
            "branch": query("branch", "--show-current") or None,
            "commit": query("rev-parse", "HEAD"),
            "dirty": bool(query("status", "--porcelain")),
        }
    except RuntimeError as error:
        return {"path": str(path.resolve()), "branch": None, "commit": None, "dirty": None, "error": str(error)}


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def compact_model_metadata(validation: dict[str, Any]) -> dict[str, Any]:
    """Retain finite GGUF gate values without embedding template source text."""
    metadata = validation["metadata"]
    values = metadata["metadata"]
    return {
        "gguf_version": metadata["gguf_version"], "tensor_count": metadata["tensor_count"],
        "general.architecture": values.get("general.architecture"),
        "general.file_type": values.get("general.file_type"),
        "general.file_type_name": validation["file_type"],
        "general.quantization_version": values.get("general.quantization_version"),
        "qwen3.context_length": values.get("qwen3.context_length"),
        "qwen3.block_count": values.get("qwen3.block_count"),
        "tokenizer.chat_template_present": metadata["chat_template_present"],
        "tokenizer.chat_template_bytes": metadata["chat_template_bytes"],
        "tokenizer.chat_template_sha256": metadata["chat_template_sha256"],
    }


def build_provenance(config_path: Path, assets_path: Path, baseline_path: Path, runner_path: Path,
                     validations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build the immutable provenance block copied to all output artifacts."""
    provenance = {
        "schema_version": 1,
        "project": git_identity(ROOT),
        "runtime": git_identity(ROOT / "third_party/llama.cpp-omni"),
        "tooling": {"benchmark_script": file_identity(Path(__file__)), "benchmark_runner": file_identity(runner_path)},
        "inputs": {"config": file_identity(config_path), "asset_manifest": file_identity(assets_path), "deployment_baseline_manifest": file_identity(baseline_path)},
        "models": {
            model_id: {"path": validation["path"], "sha256": validation["sha256"], "size_bytes": validation["size_bytes"], "gguf_metadata": compact_model_metadata(validation), "verification": "computed_preflight"}
            for model_id, validation in validations.items()
        },
        "runtime_contract": {
            "kv_cache": {"k": "f16", "v": "f16", "only_supported_benchmark_path": True, "runtime_kv_override_supported": False},
            "runtime_first_token_ms_is_service_ttft": False,
        },
    }
    provenance["provenance_sha256"] = canonical_json_sha256(provenance)
    return provenance


def preflight(model_id: str, config: dict[str, Any], assets: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    expected_name = TYPES[model_id]
    asset = next((item for item in assets["assets"] if item["id"] == model_id), None)
    if not asset or asset.get("status") != "READY" or asset.get("benchmark_admission") != "allowed":
        raise RuntimeError(f"asset {model_id} is not READY in manifests/qwen3-quant-kv-assets.json")
    path = ROOT / asset["path"]
    if not path.is_file():
        raise RuntimeError(f"model path does not exist: {path}")
    actual_sha = sha256_file(path)
    if actual_sha != asset["sha256"]:
        raise RuntimeError(f"sha256 mismatch: expected {asset['sha256']}, got {actual_sha}")
    if path.stat().st_size != asset["size_bytes"]:
        raise RuntimeError("model size mismatch against asset manifest")
    metadata = read_gguf_metadata(path)
    values = metadata["metadata"]
    if values.get("general.architecture") != "qwen3":
        raise RuntimeError("GGUF architecture is not qwen3")
    if TYPE_NAMES.get(values.get("general.file_type")) != expected_name:
        raise RuntimeError(f"GGUF file type is not {expected_name}")
    if values.get("general.quantization_version") != 2:
        raise RuntimeError("unsupported quantization_version")
    template_sha = config["model_lineage"]["chat_template_sha256"]
    if metadata["chat_template_sha256"] != template_sha:
        raise RuntimeError("chat template fingerprint mismatch")
    if not metadata["chat_template_present"]:
        raise RuntimeError("tokenizer.chat_template is missing")
    if baseline["model"]["architecture"] != "qwen3" or baseline["model"]["reasoning"] != "off":
        raise RuntimeError("deployment baseline is not the frozen Qwen3 reasoning-off baseline")
    if asset["provenance"]["source_revision"] != baseline["model"]["source_revision"]:
        raise RuntimeError("asset revision differs from deployment baseline")
    return {"id": model_id, "path": str(path), "sha256": actual_sha, "file_type": expected_name, "size_bytes": path.stat().st_size, "metadata": metadata}


def workload(workload_id: str, config: dict[str, Any]) -> tuple[str, int]:
    item = next(item for item in config["workloads"] if item["id"] == workload_id)
    if workload_id == "S":
        prompt = "Provide a concise device status report. Include temperature, power mode, GPU availability, memory state, and one actionable recommendation. Use plain text and do not reason aloud."
    elif workload_id == "G":
        prompt = "Provide a detailed but deterministic diagnostic report for this device. Cover operating state, thermal risk, memory pressure, GPU utilization, power mode, likely cause, verification steps, and remediation steps. Use numbered sections and do not reason aloud."
    else:
        line = "timestamp=2026-07-27 subsystem=gpu state=nominal temperature=55C memory=stable power=MODE_30W recommendation=continue-monitoring; "
        # Keep the long workload below the fixed 4096-token context after
        # adding the ChatML prompt wrapper and its 32-token response budget.
        # The original 150 repetitions exceeded that budget on the real Qwen3
        # tokenizer.  This frozen count targets the protocol's 2.0k-2.06k
        # prompt-token range; the actual count is retained in every run record.
        prompt = "Analyze the following fixed device log and summarize anomalies and actions. Do not reason aloud.\n" + line * item["log_repeat_count"]
    return prompt, item["max_new_tokens"]


def telemetry_peaks(path: Path) -> dict[str, int | None]:
    patterns = {"peak_ram_mb": r"\bRAM\s+(\d+)/", "peak_gr3d_percent": r"\bGR3D_FREQ\s+(\d+)%", "peak_gpu_temp_c": r"\bGPU@([0-9]+(?:\.[0-9]+)?)C", "peak_tj_temp_c": r"\bTJ@([0-9]+(?:\.[0-9]+)?)C", "peak_vdd_gpu_soc_mw": r"\bVDD_GPU_SOC\s+(\d+)mW"}
    values: dict[str, list[int]] = {key: [] for key in patterns}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            for key, pattern in patterns.items():
                # Jetson releases differ in sensor-key capitalization
                # (for example, gpu@/tj@ versus GPU@/TJ@).  Sensor names are
                # case-insensitive here; numeric values and units remain exact.
                match = re.search(pattern, line, flags=re.IGNORECASE)
                if match:
                    values[key].append(round(float(match.group(1))))
    return {key: max(items) if items else None for key, items in values.items()}


def run_one(args: argparse.Namespace, validation: dict[str, Any], provenance: dict[str, Any], prompt_id: str, phase: str, attempt: int, output_dir: Path) -> dict[str, Any]:
    prompt, max_new_tokens = workload(prompt_id, args.config)
    run_dir = output_dir / phase / prompt_id / f"attempt-{attempt:02d}"
    run_dir.mkdir(parents=True, exist_ok=False)
    command = [args.runner, "--model", validation["path"], "--sha256", validation["sha256"], "--prompt", prompt, "--max-new-tokens", str(max_new_tokens), "--context", str(args.config["fixed_runtime"]["context_tokens"]), "--batch", str(args.config["fixed_runtime"]["batch_tokens"]), "--ubatch", str(args.config["fixed_runtime"]["ubatch_tokens"]), "--gpu-layers", str(args.config["fixed_runtime"]["gpu_layers"]), "--seed", str(args.config["sampling"]["seed"]), "--top-k", str(args.config["sampling"]["top_k"]), "--top-p", str(args.config["sampling"]["top_p"]), "--min-p", str(args.config["sampling"]["min_p"]), "--temperature", str(args.config["sampling"]["temperature"]), "--request-id", f"{args.model}-{prompt_id}-{phase}-{attempt:02d}"]
    (run_dir / "command.json").write_text(json.dumps({"argv": command}, indent=2) + "\n", encoding="utf-8")
    telemetry_path = run_dir / "tegrastats.log"
    telemetry = None
    if args.tegrastats and shutil.which("tegrastats"):
        telemetry = subprocess.Popen([shutil.which("tegrastats"), "--interval", str(args.config["telemetry"]["interval_ms"])], stdout=telemetry_path.open("w"), stderr=subprocess.STDOUT, text=True)
    started = time.monotonic_ns()
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    ended = time.monotonic_ns()
    if telemetry is not None:
        telemetry.terminate()
        try:
            telemetry.wait(timeout=5)
        except subprocess.TimeoutExpired:
            telemetry.kill(); telemetry.wait(timeout=5)
    (run_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
    (run_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    record: dict[str, Any] = {"phase": phase, "prompt_id": prompt_id, "attempt": attempt, "model_id": args.model, "model_path": validation["path"], "model_sha256": validation["sha256"], "started_monotonic_ns": started, "ended_monotonic_ns": ended, "exit_code": completed.returncode, "telemetry_path": str(telemetry_path) if telemetry_path.exists() else None, "telemetry": telemetry_peaks(telemetry_path), "service_ttft_ms": None, "runtime_first_token_ms_is_not_service_ttft": True, "kv_cache": {"k": args.kv_k, "v": args.kv_v}, "power_mode_expected": {"name": args.config["fixed_runtime"]["nvpmodel_expected"], "id": args.config["fixed_runtime"]["nvpmodel_expected_id"]}, "provenance": provenance, "provenance_sha256": provenance["provenance_sha256"]}
    try:
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        record.update(result)
        if isinstance(result.get("metrics"), dict):
            record.update(result["metrics"])
    except (json.JSONDecodeError, IndexError):
        record.update({"code": "runner_output_invalid", "error_message": "runner did not emit JSON"})
    item = next(item for item in args.config["workloads"] if item["id"] == prompt_id)
    token_min, token_max = item["prompt_tokens_target"]
    record["prompt_tokens_target"] = {"min": token_min, "max": token_max}
    record["prompt_tokens_in_target"] = isinstance(record.get("prompt_tokens"), int) and token_min <= record["prompt_tokens"] <= token_max
    record["valid"] = completed.returncode == 0 and record.get("code") == "ok" and record.get("finish_reason") in args.config["valid_run"]["finish_reasons"] and bool(record.get("text")) and record["prompt_tokens_in_target"] and (not args.tegrastats or telemetry_path.exists())
    if not record["valid"]:
        combined_error = (completed.stderr + " " + str(record.get("error_message", ""))).lower()
        if args.tegrastats and not telemetry_path.exists(): record["failure_class"] = "telemetry_missing"
        elif record.get("code") == "context_limit" or "exceeds context" in combined_error: record["failure_class"] = "context_limit"
        elif "out of memory" in combined_error or "oom" in combined_error or "allocation" in combined_error: record["failure_class"] = "oom_or_allocation_failed"
        elif "hash" in combined_error: record["failure_class"] = "model_hash_mismatch"
        elif "cuda" in combined_error: record["failure_class"] = "cuda_error"
        elif record.get("finish_reason") == "timeout" or record.get("code") == "timeout": record["failure_class"] = "timeout"
        elif record.get("finish_reason") == "cancelled" or record.get("code") == "cancelled": record["failure_class"] = "cancelled"
        elif not record["prompt_tokens_in_target"]: record["failure_class"] = "workload_token_target_mismatch"
        elif record.get("finish_reason") == "length": record["failure_class"] = "incomplete_output"
        else: record["failure_class"] = "internal"
    (run_dir / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def write_outputs(output_dir: Path, records: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    provenance = plan["provenance"]
    for record in records:
        record.setdefault("provenance", provenance)
        record.setdefault("provenance_sha256", provenance["provenance_sha256"])
    with (output_dir / "records.jsonl").open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    fields = ["phase", "prompt_id", "attempt", "model_id", "valid", "exit_code", "finish_reason", "prompt_tokens", "prompt_tokens_in_target", "output_tokens", "model_ready_ms", "prefill_ms", "decode_ms", "first_token_ms", "total_ms", "decode_tokens_per_second", "failure_class", "provenance_sha256", "project_branch", "project_commit", "project_dirty", "runtime_branch", "runtime_commit", "runtime_dirty", "benchmark_script_sha256", "benchmark_runner_sha256", "config_sha256", "asset_manifest_sha256", "deployment_baseline_manifest_sha256", "q4_k_m_model_sha256", "q4_k_m_model_size_bytes", "q4_k_m_gguf_metadata", "q8_0_model_sha256", "q8_0_model_size_bytes", "q8_0_gguf_metadata"]

    def csv_record(record: dict[str, Any]) -> dict[str, Any]:
        row = {key: record.get(key) for key in fields}
        row.update({
            "provenance_sha256": provenance["provenance_sha256"],
            "project_branch": provenance["project"]["branch"], "project_commit": provenance["project"]["commit"], "project_dirty": provenance["project"]["dirty"],
            "runtime_branch": provenance["runtime"]["branch"], "runtime_commit": provenance["runtime"]["commit"], "runtime_dirty": provenance["runtime"]["dirty"],
            "benchmark_script_sha256": provenance["tooling"]["benchmark_script"]["sha256"], "benchmark_runner_sha256": provenance["tooling"]["benchmark_runner"]["sha256"],
            "config_sha256": provenance["inputs"]["config"]["sha256"], "asset_manifest_sha256": provenance["inputs"]["asset_manifest"]["sha256"], "deployment_baseline_manifest_sha256": provenance["inputs"]["deployment_baseline_manifest"]["sha256"],
        })
        for model_id in TYPES:
            model = provenance["models"][model_id]
            row[f"{model_id}_model_sha256"] = model["sha256"]
            row[f"{model_id}_model_size_bytes"] = model["size_bytes"]
            row[f"{model_id}_gguf_metadata"] = json.dumps(model["gguf_metadata"], ensure_ascii=False, sort_keys=True)
        return row

    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(csv_record(record) for record in records)
    valid = [record for record in records if record.get("valid") and record.get("phase") == "measured"]
    required = plan["required_valid_measured"]
    by_workload: dict[str, dict[str, Any]] = {}
    for prompt_id in plan["workloads"]:
        measured = [record for record in records if record.get("phase") == "measured" and record.get("prompt_id") == prompt_id]
        valid_count = sum(1 for record in measured if record.get("valid"))
        failures: dict[str, int] = {}
        for record in measured:
            if not record.get("valid"):
                failure = record.get("failure_class", "internal")
                failures[failure] = failures.get(failure, 0) + 1
        by_workload[prompt_id] = {
            "attempted": len(measured),
            "valid_measured": valid_count,
            "required_valid_measured": required,
            "complete": valid_count >= required,
            "failure_classes": failures,
        }
    summary = {"plan": plan, "provenance": provenance, "provenance_sha256": provenance["provenance_sha256"], "attempted": len(records), "valid_measured": len(valid), "failed": sum(1 for record in records if not record.get("valid")), "by_workload": by_workload, "complete": all(item["complete"] for item in by_workload.values()), "metrics": {}}
    for key in ("model_ready_ms", "prompt_tokens", "output_tokens", "prefill_ms", "decode_ms", "first_token_ms", "total_ms", "decode_tokens_per_second"):
        values = [float(record[key]) for record in valid if isinstance(record.get(key), (int, float))]
        summary["metrics"][key] = {"count": len(values), "mean": statistics.mean(values), "median": statistics.median(values)} if values else None
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=sorted(TYPES), required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "tools/benchmark/configs/qwen3-quant-kv-benchmark-v1.json")
    parser.add_argument("--assets-manifest", type=Path, default=ROOT / "manifests/qwen3-quant-kv-assets.json")
    parser.add_argument("--baseline", type=Path, default=ROOT / "manifests/deployment-baseline-v1.json")
    parser.add_argument("--runner", default=str(ROOT / "build-runtime/runtime/edgeomni_qwen3_benchmark_runner"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--runs", type=int, default=None)
    parser.add_argument("--preconditioning-runs", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=None, help="maximum attempts per workload phase; failed attempts are retained")
    parser.add_argument("--execute", action="store_true", help="run DirectBackend requests; without this flag only preflight/plan is written")
    parser.add_argument("--tegrastats", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--kv-k", choices=("f16", "q8_0", "q4_0"), default="f16")
    parser.add_argument("--kv-v", choices=("f16", "q8_0", "q4_0"), default="f16")
    args = parser.parse_args()
    if args.kv_k != "f16" or args.kv_v != "f16":
        parser.error("current DirectBackend exposes no KV type override; only f16/f16 is executable in M6.3")
    config_path, assets_path, baseline_path = args.config, args.assets_manifest, args.baseline
    args.config = read_json(config_path); assets = read_json(assets_path); baseline = read_json(baseline_path)
    # Rehash and parse both comparison artifacts on every invocation.  This
    # makes a Q4-only or Q8-only run independently sufficient for final pairing.
    validations = {model_id: preflight(model_id, args.config, assets, baseline) for model_id in TYPES}
    validation = validations[args.model]
    provenance = build_provenance(config_path, assets_path, baseline_path, Path(args.runner), validations)
    output_dir = args.output_dir or ROOT / "benchmark-results" / "qwen3-quant-kv" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=False)
    runs = args.runs if args.runs is not None else args.config["repetitions"]["valid_measured"]
    preconditioning = args.preconditioning_runs if args.preconditioning_runs is not None else args.config["repetitions"]["preconditioning"]
    max_attempts = args.max_attempts if args.max_attempts is not None else max(runs + 3, preconditioning + 1)
    if runs < 5 or preconditioning < 1:
        raise SystemExit("--runs must be at least 5 and --preconditioning-runs must be positive")
    if max_attempts < max(runs, preconditioning):
        raise SystemExit("--max-attempts must be at least the requested runs and preconditioning count")
    power_observed = None
    if args.execute and shutil.which("nvpmodel"):
        power_observed = subprocess.run([shutil.which("nvpmodel"), "-q"], capture_output=True, text=True, check=False).stdout.strip()
    plan = {"model": {key: value for key, value in validation.items() if key != "metadata"}, "workloads": [item["id"] for item in args.config["workloads"]], "preconditioning_runs": preconditioning, "required_valid_measured": runs, "max_attempts_per_phase": max_attempts, "execute": args.execute, "runtime_first_token_ms_is_not_service_ttft": True, "kv_cache": {"k": args.kv_k, "v": args.kv_v, "note": "Only F16/F16 is executable: DirectBackend exposes no KV type override."}, "power_mode_expected": {"name": args.config["fixed_runtime"]["nvpmodel_expected"], "id": args.config["fixed_runtime"]["nvpmodel_expected_id"]}, "power_mode_observed": power_observed, "provenance": provenance, "provenance_sha256": provenance["provenance_sha256"]}
    (output_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.execute:
        write_outputs(output_dir, [], plan)
        print(json.dumps({"status": "PREFLIGHT_READY", "output_dir": str(output_dir), "model": validation["file_type"]}))
        return 0
    records = []
    for prompt_id in [item["id"] for item in args.config["workloads"]]:
        # Jetson UMA allocation can fail intermittently. Keep every failed
        # attempt, but retry until the required valid count or the explicit
        # cap is reached so one transient allocation failure cannot invalidate
        # an otherwise usable workload cell.
        for phase, target in (("preconditioning", preconditioning), ("measured", runs)):
            valid_count = 0
            attempt = 0
            while valid_count < target and attempt < max_attempts:
                attempt += 1
                record = run_one(args, validation, provenance, prompt_id, phase, attempt, output_dir)
                records.append(record)
                if record.get("valid"):
                    valid_count += 1
    summary = write_outputs(output_dir, records, plan)
    if not summary["complete"]:
        print("fewer than required valid measured runs; see records.jsonl", file=sys.stderr)
        return 2
    print(json.dumps({"status": "COMPLETE", "output_dir": str(output_dir), "valid_measured": runs * 3}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"preflight/error: {error}", file=sys.stderr)
        raise SystemExit(1)
