#!/usr/bin/env python3
"""Audit raw soak evidence, including formal/exploratory provenance gates."""
from __future__ import annotations
import argparse,json,pathlib,sys
def audit(raw,allow_exploratory=False,minimum_hit_ratio=1.0):
 fails=[];rows=raw.get("requests",[])
 if raw.get("status") not in (("EXPLORATORY_UNREVIEWED",) if allow_exploratory else ("UNREVIEWED_RAW_RESULT",)):fails.append("raw_status")
 if not allow_exploratory and (not raw.get("worktree_clean") or not raw.get("clock_locked")):fails.append("dirty_or_dynamic_clock")
 if raw.get("failure_reason"):fails.append("collection_failure")
 if not raw.get("warmup") or raw["warmup"].get("client_http_status")!=200 or raw["warmup"].get("error") is not None:fails.append("warmup")
 normal=[r for r in rows if r.get("response",{}).get("client_http_status")==200 and r.get("response",{}).get("error") is None]
 if len(normal)!=len(rows):fails.append("request_error")
 hashes={r.get("text_sha256") for r in normal}
 if len(hashes)!=1:fails.append("output_not_deterministic")
 hits=[]
 for r in normal:
  x=r["response"];m=x.get("metrics",{});hit=m.get("cache_hit_tokens");miss=m.get("cache_miss_tokens");
  if not isinstance(hit,int) or not isinstance(miss,int) or hit+miss!=x.get("prompt_tokens"):fails.append("cache_accounting");break
  hits.append(hit)
 if raw.get("mode")=="disabled" and any(hits):fails.append("disabled_nonzero_hit")
 ratio=(sum(x>0 for x in hits)/len(hits)) if hits else 0
 if raw.get("mode")=="single_hot_text" and ratio<minimum_hit_ratio:fails.append("hot_hit_ratio")
 t=raw.get("telemetry",{});return {"status":"PASS" if not fails else "FAIL","fail_reasons":sorted(set(fails)),"requests":len(rows),"errors":len(rows)-len(normal),"error_rate":(len(rows)-len(normal))/len(rows) if rows else 1,"unique_output_hashes":len(hashes),"positive_hit_requests":sum(x>0 for x in hits),"positive_hit_ratio":ratio,"ram_used_mb":t.get("ram_used_mb",{}),"temperature_c":t.get("temperature_c",{}),"unified_ram_is_not_a_kv_leak_proof":True}
def main():
 p=argparse.ArgumentParser();p.add_argument("raw",type=pathlib.Path);p.add_argument("--allow-exploratory",action="store_true");p.add_argument("--minimum-hot-hit-ratio",type=float,default=1.0);a=p.parse_args()
 try:r=audit(json.loads(a.raw.read_text()),a.allow_exploratory,a.minimum_hot_hit_ratio)
 except (OSError,ValueError,TypeError,json.JSONDecodeError) as e:print(f"soak audit failed: {e}",file=sys.stderr);return 1
 print(json.dumps(r,indent=2));return 0 if r["status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())
