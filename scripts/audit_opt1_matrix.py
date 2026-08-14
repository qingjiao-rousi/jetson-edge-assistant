#!/usr/bin/env python3
"""Audit one 30-request disabled/single-hot pair; never creates a reviewed report."""
from __future__ import annotations
import argparse, hashlib, json, pathlib, statistics, sys

def rows(path):
    data=[json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(data)!=30 or [r.get("sample_index") for r in data]!=list(range(1,31)):
        raise ValueError(f"{path}: expected exactly 30 contiguous measured rows (warm-up is excluded)")
    return data
def stats(rows,key):
    v=[float(r["metrics"][key]) for r in rows]
    return {"n":len(v),"median":statistics.median(v),"mean":statistics.mean(v),"min":min(v),"max":max(v)}
def audit(disabled,hot):
    d,h=rows(disabled),rows(hot); failures=[]
    for i,(left,right) in enumerate(zip(d,h),1):
        def fail(rule): failures.append({"index":i,"rule":rule,"disabled":{"http":left.get("client_http_status"),"error":left.get("error"),"prompt_tokens":left.get("prompt_tokens"),"output_tokens":left.get("output_tokens"),"finish_reason":left.get("finish_reason"),"hit":left.get("metrics",{}).get("cache_hit_tokens")},"single_hot":{"http":right.get("client_http_status"),"error":right.get("error"),"prompt_tokens":right.get("prompt_tokens"),"output_tokens":right.get("output_tokens"),"finish_reason":right.get("finish_reason"),"hit":right.get("metrics",{}).get("cache_hit_tokens"),"miss":right.get("metrics",{}).get("cache_miss_tokens")}})
        if left.get("client_http_status")!=200 or left.get("error") is not None or right.get("client_http_status")!=200 or right.get("error") is not None: fail("http_or_error")
        if left.get("text")!=right.get("text"): fail("text_mismatch")
        for key in ("prompt_tokens","output_tokens","finish_reason"):
            if left.get(key)!=right.get(key): fail(f"{key}_mismatch")
        if left.get("metrics",{}).get("cache_hit_tokens")!=0: fail("disabled_nonzero_hit")
        hit=right.get("metrics",{}).get("cache_hit_tokens"); miss=right.get("metrics",{}).get("cache_miss_tokens"); prompt=right.get("prompt_tokens")
        if not isinstance(hit,int) or not isinstance(miss,int) or hit+miss!=prompt: fail("hot_cache_accounting")
        elif not 0<=hit<=prompt: fail("hot_hit_out_of_bounds")
        elif hit<=0: fail("hot_measurement_has_no_hit")
    return {"status":"PASS" if not failures else "FAIL","warmup_included":False,"failures":failures,"artifacts":{"disabled":hashlib.sha256(disabled.read_bytes()).hexdigest(),"single_hot":hashlib.sha256(hot.read_bytes()).hexdigest()},"metrics":{mode:{key:stats(rs,key) for key in ("prefill_ms","ttft_ms","total_ms","decode_tokens_per_second")} for mode,rs in (("disabled",d),("single_hot",h))}}
def main():
    p=argparse.ArgumentParser();p.add_argument("disabled",type=pathlib.Path);p.add_argument("single_hot",type=pathlib.Path);p.add_argument("--output",type=pathlib.Path);a=p.parse_args()
    try:r=audit(a.disabled,a.single_hot)
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as e:print(f"matrix audit failed: {e}",file=sys.stderr);return 1
    print(json.dumps(r,indent=2));
    if r["status"]!="PASS": return 1
    if a.output:a.output.write_text(json.dumps(r,indent=2)+"\n",encoding="utf-8")
    return 0
if __name__=="__main__":raise SystemExit(main())
