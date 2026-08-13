#!/usr/bin/env python3
"""Audit one raw OPT-1 soak JSON; output is never a reviewed report."""
from __future__ import annotations
import argparse, json, pathlib, sys
def main():
 p=argparse.ArgumentParser(); p.add_argument("raw",type=pathlib.Path); p.add_argument("--output",type=pathlib.Path); a=p.parse_args()
 try:
  raw=json.loads(a.raw.read_text()); rows=raw["requests"]
  ok=bool(rows) and all(r["status"]==200 and r["response"].get("error") is None for r in rows)
  hashes={r["text_sha256"] for r in rows}; accounting=all(r["response"].get("metrics",{}).get("cache_hit_tokens",0)+r["response"].get("metrics",{}).get("cache_miss_tokens",0)==r["response"].get("prompt_tokens") for r in rows)
  if raw["mode"]=="disabled": accounting=accounting and all(r["response"].get("metrics",{}).get("cache_hit_tokens",0)==0 for r in rows)
  result={"status":"PASS" if ok and accounting else "FAIL","requests":len(rows),"errors":sum(r["status"]!=200 or r["response"].get("error") is not None for r in rows),"unique_output_hashes":len(hashes),"cache_accounting":accounting,"unified_ram_is_not_a_kv_leak_proof":True}
 except (OSError,KeyError,TypeError,json.JSONDecodeError) as e: print(f"soak audit failed: {e}",file=sys.stderr); return 1
 encoded=json.dumps(result,indent=2)+"\n"; print(encoded,end="")
 if a.output: a.output.write_text(encoded)
 return 0 if result["status"]=="PASS" else 1
if __name__=="__main__": raise SystemExit(main())
