#!/usr/bin/env python3
"""Validate and summarize an EdgeOmni benchmark JSONL and tegrastats log."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import statistics
import sys
from typing import Callable


def nearest_rank(values: list[float], percentile: float) -> float:
    return sorted(values)[math.ceil(percentile * len(values)) - 1]


def stats(values: list[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("metric has no samples")
    return {
        "n": len(values),
        "median": round(statistics.median(values), 3),
        "p10": round(nearest_rank(values, 0.10), 3),
        "p90": round(nearest_rank(values, 0.90), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "mean": round(statistics.mean(values), 3),
    }


def load_rows(path: pathlib.Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError("benchmark JSONL must contain JSON objects")
    expected = list(range(1, len(rows) + 1))
    if [row.get("sample_index") for row in rows] != expected:
        raise ValueError("sample_index values are not contiguous from 1")
    return rows


def metric(rows: list[dict], getter: Callable[[dict], float]) -> dict[str, float | int]:
    return stats([float(getter(row)) for row in rows])


def summarize_rows(rows: list[dict]) -> dict:
    workloads = sorted({row.get("workload", "text") for row in rows})
    if len(workloads) != 1:
        raise ValueError("benchmark JSONL mixes workload types")
    workload = workloads[0]
    hashes = sorted({row.get("model_sha256") for row in rows})
    validity = {
        "samples": len(rows),
        "workload": workload,
        "all_http_200": all(row.get("client_http_status") == 200 for row in rows),
        "all_error_null": all(row.get("error") is None for row in rows),
        "model_sha256_values": hashes,
        "prompt_token_values": sorted({row.get("prompt_tokens") for row in rows}),
        "output_token_values": sorted({row.get("output_tokens") for row in rows}),
        "finish_reason_values": sorted({row.get("finish_reason") for row in rows}),
        "unique_output_texts": len({row.get("text") for row in rows}),
    }
    metrics = {
        "ttft_ms": metric(rows, lambda row: row["metrics"]["ttft_ms"]),
        "prefill_ms": metric(rows, lambda row: row["metrics"]["prefill_ms"]),
        "decode_ms": metric(rows, lambda row: row["metrics"]["decode_ms"]),
        "decode_tokens_per_second": metric(rows, lambda row: row["metrics"]["decode_tokens_per_second"]),
        "runtime_total_ms": metric(rows, lambda row: row["metrics"]["total_ms"]),
        "client_total_ms": metric(rows, lambda row: row["client_total_ms"]),
    }
    if workload == "single_image":
        image_hashes = sorted({row.get("image_sha256") for row in rows})
        if len(image_hashes) != 1 or not image_hashes[0]:
            raise ValueError("single-image rows must bind one image SHA-256")
        validity["image_sha256_values"] = image_hashes
        measurement_keys = ("image_preprocess_ms", "vision_encode_ms", "image_embedding_ms")
        status_values = {
            key: sorted({row.get("measurement_status", {}).get(key, "missing") for row in rows})
            for key in measurement_keys
        }
        validity["measurement_status"] = status_values
        unavailable = {}
        for key in measurement_keys:
            if status_values[key] == ["measured"]:
                metrics[key] = metric(rows, lambda row, metric_key=key: row["metrics"][metric_key])
            else:
                unavailable[key] = status_values[key]
        if unavailable:
            validity["unavailable_metrics"] = unavailable
        metrics["image_tokens"] = metric(rows, lambda row: row["image_tokens"])
    return {"schema_version": 1, "validity": validity, "metrics": metrics}


def telemetry(path: pathlib.Path) -> dict[str, dict[str, float | int]]:
    text = path.read_text(encoding="utf-8")
    patterns = {
        "ram_used_mb": r"RAM (\d+)/",
        "gr3d_percent": r"GR3D_FREQ (\d+)%",
        "cpu_temp_c": r"cpu@([0-9.]+)C",
        "gpu_temp_c": r"gpu@([0-9.]+)C",
        "vdd_gpu_soc_mw": r"VDD_GPU_SOC (\d+)mW",
        "vdd_cpu_cv_mw": r"VDD_CPU_CV (\d+)mW",
        "vin_sys_5v0_mw": r"VIN_SYS_5V0 (\d+)mW",
    }
    return {name: stats([float(value) for value in re.findall(pattern, text)]) for name, pattern in patterns.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=pathlib.Path)
    parser.add_argument("--tegrastats", type=pathlib.Path)
    args = parser.parse_args()
    try:
        rows = load_rows(args.jsonl)
        summary = summarize_rows(rows)
        if args.tegrastats:
            summary["telemetry"] = telemetry(args.tegrastats)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"benchmark summary failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
