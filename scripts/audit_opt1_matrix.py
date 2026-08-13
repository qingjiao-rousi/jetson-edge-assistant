#!/usr/bin/env python3
"""Audit paired OPT-1 raw JSONL; never writes a reviewed report."""
from __future__ import annotations
import argparse, hashlib, json, pathlib, statistics, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]

def rows(path):
    data = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(data) != 30 or [r.get("sample_index") for r in data] != list(range(1, 31)):
        raise ValueError(f"{path}: expected exactly 30 contiguous measured rows")
    return data
def metric(rs, key):
    vals = [float(r["metrics"][key]) for r in rs]
    return {"n": len(vals), "median": statistics.median(vals), "min": min(vals), "max": max(vals), "mean": statistics.mean(vals)}
def audit(disabled, hot):
    d, h = rows(disabled), rows(hot)
    checks = []
    checks.append((all(r.get("client_http_status") == 200 and r.get("error") is None for r in d+h), "http_and_error"))
    checks.append((len({r.get("text") for r in d}) == 1 and len({r.get("text") for r in h}) == 1 and d[0].get("text") == h[0].get("text"), "cross_mode_output"))
    for name, rs in (("disabled", d), ("hot", h)):
        checks.append((len({r.get("prompt_tokens") for r in rs}) == 1 and len({r.get("output_tokens") for r in rs}) == 1 and len({r.get("finish_reason") for r in rs}) == 1, f"{name}_shape"))
    checks.append((all(r["metrics"].get("cache_hit_tokens", 0) == 0 for r in d), "disabled_zero_hit"))
    checks.append((all(r["metrics"].get("cache_hit_tokens", 0) + r["metrics"].get("cache_miss_tokens", 0) == r.get("prompt_tokens") for r in h), "hot_accounting"))
    prompt_tokens = d[0].get("prompt_tokens")
    hit = h[0]["metrics"].get("cache_hit_tokens", 0)
    checks.append((0 <= hit <= prompt_tokens, "hit_within_prompt"))
    result = {"status": "PASS" if all(ok for ok, _ in checks) else "FAIL", "checks": [{"name": n, "passed": ok} for ok, n in checks],
              "artifacts": {"disabled": hashlib.sha256(disabled.read_bytes()).hexdigest(), "single_hot": hashlib.sha256(hot.read_bytes()).hexdigest()},
              "prompt_tokens": prompt_tokens, "output_tokens": d[0].get("output_tokens"), "finish_reason": d[0].get("finish_reason"),
              "cache": {"disabled": {"hit": 0, "miss": prompt_tokens, "ratio": 0.0}, "single_hot": {"hit": hit, "miss": h[0]["metrics"].get("cache_miss_tokens"), "ratio": hit / prompt_tokens}},
              "metrics": {mode: {key: metric(rs, key) for key in ("prefill_ms", "ttft_ms", "total_ms", "decode_tokens_per_second")} for mode, rs in (("disabled", d), ("single_hot", h))}}
    return result
def main():
    p = argparse.ArgumentParser(); p.add_argument("disabled", type=pathlib.Path); p.add_argument("single_hot", type=pathlib.Path); p.add_argument("--output", type=pathlib.Path)
    a = p.parse_args()
    try: result = audit(a.disabled, a.single_hot)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as e: print(f"matrix audit failed: {e}", file=sys.stderr); return 1
    encoded = json.dumps(result, indent=2) + "\n"; print(encoded, end="")
    if a.output:
        if result["status"] != "PASS": print("reviewed report suppressed because audit failed", file=sys.stderr); return 1
        a.output.parent.mkdir(parents=True, exist_ok=True); a.output.write_text(encoded, encoding="utf-8")
    return 0 if result["status"] == "PASS" else 1
if __name__ == "__main__": raise SystemExit(main())
