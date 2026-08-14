#!/usr/bin/env python3
"""Classify audited OPT-1 pairs under the batch-boundary reuse policy."""
from __future__ import annotations
import argparse, hashlib, json, pathlib, re, statistics, sys

def rows(path):
    data=[json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(data)!=30 or [r.get("sample_index") for r in data]!=list(range(1,31)):
        raise ValueError(f"{path}: expected 30 contiguous measured rows; warm-up is excluded")
    return data
def environment(path):
    value={}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key,item=line.split("=",1);value[key]=item
    return value
def batch_from_artifacts(jsonl):
    stem=jsonl.with_suffix("");env_path=stem.with_name(stem.name+"-environment.txt");log_path=stem.with_name(stem.name+"-runtime.log")
    if not env_path.is_file(): raise ValueError(f"missing environment artifact: {env_path}")
    env=environment(env_path)
    if "batch_tokens" in env: return int(env["batch_tokens"]),"environment.batch_tokens",env_path,log_path
    if not log_path.is_file(): raise ValueError(f"environment has no batch_tokens and runtime log is missing: {log_path}")
    matches=re.findall(r"llama_context: n_batch\s+=\s+(\d+)",log_path.read_text(encoding="utf-8",errors="replace"))
    if len(set(matches))!=1: raise ValueError(f"could not determine one n_batch from runtime log: {log_path}")
    return int(matches[0]),"runtime_log.llama_context.n_batch",env_path,log_path
def stats(data,key):
    values=[float(r["metrics"][key]) for r in data]
    return {"n":len(values),"median":statistics.median(values),"mean":statistics.mean(values),"min":min(values),"max":max(values)}
def details(row):
    m=row.get("metrics",{});return {"http":row.get("client_http_status"),"error":row.get("error"),"prompt_tokens":row.get("prompt_tokens"),"output_tokens":row.get("output_tokens"),"finish_reason":row.get("finish_reason"),"hit":m.get("cache_hit_tokens"),"miss":m.get("cache_miss_tokens")}
def audit(disabled,hot):
    d,h=rows(disabled),rows(hot)
    db,ds,de,dl=batch_from_artifacts(disabled);hb,hs,he,hl=batch_from_artifacts(hot)
    if db!=hb: raise ValueError(f"batch mismatch: disabled={db}, single-hot={hb}")
    failures=[];hits=[];prompts=[]
    for index,(left,right) in enumerate(zip(d,h),1):
        fail=lambda rule: failures.append({"index":index,"rule":rule,"disabled":details(left),"single_hot":details(right)})
        if left.get("client_http_status")!=200 or left.get("error") is not None or right.get("client_http_status")!=200 or right.get("error") is not None: fail("http_or_error")
        if left.get("text")!=right.get("text"): fail("text_mismatch")
        for key in ("prompt_tokens","output_tokens","finish_reason"):
            if left.get(key)!=right.get(key): fail(f"{key}_mismatch")
        if left.get("metrics",{}).get("cache_hit_tokens")!=0: fail("disabled_nonzero_hit")
        hit=right.get("metrics",{}).get("cache_hit_tokens");miss=right.get("metrics",{}).get("cache_miss_tokens");prompt=right.get("prompt_tokens");hits.append(hit);prompts.append(prompt)
        if not isinstance(hit,int) or not isinstance(miss,int) or not isinstance(prompt,int) or hit+miss!=prompt: fail("hot_cache_accounting");continue
        if not 0<=hit<=prompt: fail("hot_hit_out_of_bounds");continue
        if prompt>=db and hit<=0: fail("eligible_prompt_has_no_reuse")
        if prompt<db and (hit!=0 or miss!=prompt): fail("below_batch_unexpected_cache_state")
    runtime_tokens=prompts[0] if len(set(prompts))==1 else None
    if runtime_tokens is None: failures.append({"index":"all","rule":"runtime_prompt_tokens_not_constant"})
    if failures: classification="FAIL"
    elif runtime_tokens<db: classification="PASS_EXPECTED_NO_REUSE"
    else: classification="PASS_REUSE"
    return {"classification":classification,"warmup_included":False,"runtime_prompt_tokens":runtime_tokens,"batch_tokens":db,"batch_evidence":{"disabled":{"source":ds,"environment":str(de),"runtime_log":str(dl)},"single_hot":{"source":hs,"environment":str(he),"runtime_log":str(hl)}},"hit_statistics":{"positive_requests":sum(isinstance(x,int) and x>0 for x in hits),"zero_hit_requests":sum(x==0 for x in hits),"unique_hit_tokens":sorted(set(hits))},"failures":failures,"artifacts":{"disabled_jsonl_sha256":hashlib.sha256(disabled.read_bytes()).hexdigest(),"single_hot_jsonl_sha256":hashlib.sha256(hot.read_bytes()).hexdigest()},"metrics":{mode:{key:stats(rs,key) for key in ("prefill_ms","ttft_ms","total_ms","decode_tokens_per_second")} for mode,rs in (("disabled",d),("single_hot",h))}}
def matrix(pairs):
    results=[audit(disabled,hot) for disabled,hot in pairs]
    if any(r["classification"]=="FAIL" for r in results): status="FAIL"
    elif any(r["classification"]=="PASS_EXPECTED_NO_REUSE" for r in results): status="PASS_WITH_BATCH_BOUNDARY_LIMITATION"
    else: status="PASS_REUSE_ALL_ELIGIBLE_LENGTHS"
    eligible=[r for r in results if r["runtime_prompt_tokens"] is not None and r["runtime_prompt_tokens"]>=r["batch_tokens"]]
    return {"status":status,"eligible_lengths_status":"PASS_REUSE_ALL_ELIGIBLE_LENGTHS" if eligible and all(r["classification"]=="PASS_REUSE" for r in eligible) else "FAIL","pairs":results,"reviewed_correctness_coverage":status!="FAIL","reuse_latency_eligible_runtime_prompt_tokens":[r["runtime_prompt_tokens"] for r in results if r["classification"]=="PASS_REUSE"],"excluded_from_reuse_latency_statistics":[r["runtime_prompt_tokens"] for r in results if r["classification"]=="PASS_EXPECTED_NO_REUSE"]}
def main():
    p=argparse.ArgumentParser();p.add_argument("pairs",nargs="+",type=pathlib.Path,metavar="JSONL");p.add_argument("--output",type=pathlib.Path);a=p.parse_args()
    if len(a.pairs)%2:p.error("provide disabled/single-hot JSONL paths in pairs")
    try:result=matrix(list(zip(a.pairs[::2],a.pairs[1::2])))
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as error:print(f"matrix audit failed: {error}",file=sys.stderr);return 1
    encoded=json.dumps(result,indent=2)+"\n";print(encoded,end="")
    if a.output and result["status"]!="FAIL":a.output.write_text(encoded,encoding="utf-8")
    return 0 if result["status"]!="FAIL" else 1
if __name__=="__main__":raise SystemExit(main())
