#!/usr/bin/env python3
"""Run the OPT-1 matrix using disabled-Runtime calibrated labels."""
from __future__ import annotations
import argparse,json,pathlib,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument("--calibration",type=pathlib.Path,required=True);p.add_argument("--output",default="benchmarks/results/opt1-length");p.add_argument("--tegrastats",default="/usr/bin/tegrastats");a=p.parse_args()
 manifest=json.loads(a.calibration.read_text(encoding="utf-8"))
 if manifest.get("status")!="UNREVIEWED_RAW_RESULT":raise RuntimeError("formal matrix requires clean/locked disabled calibration")
 seen=set()
 for item in manifest.get("items",[]):
  label=item.get("label");prompt=item.get("prompt_file");tokens=item.get("runtime_prompt_tokens")
  if not label or not prompt or not isinstance(tokens,int) or label in seen:raise RuntimeError("invalid or duplicate calibration item")
  seen.add(label)
  for config,mode in (("configs/assistant.json","disabled"),("configs/assistant-prefix-single-hot.json","single-hot")):
   subprocess.run([sys.executable,str(ROOT/"scripts/run_jetson_benchmark.py"),"--config",str(ROOT/config),"--label",f"opt1-{label}-{mode}","--output",a.output,"--repeats","30","--max-new-tokens","128","--prompt-file",prompt,"--tegrastats",a.tegrastats],cwd=ROOT,check=True)
 return 0
if __name__=="__main__":raise SystemExit(main())
