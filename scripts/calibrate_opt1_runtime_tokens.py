#!/usr/bin/env python3
"""Measure actual Qwen2.5-VL HTTP chat prompt_tokens with disabled Runtime."""
from __future__ import annotations
import argparse,datetime,hashlib,json,pathlib,subprocess,sys,time,uuid
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/"scripts")]
from app.assistant.application import check_runtime,load_config
from run_jetson_benchmark import git_source_state,read_jetson_clock_status,runtime_request,post_json,wait_ready
from run_local_assistant import check_port_available,check_runtime_assets,runtime_command,stop_process
def main():
 p=argparse.ArgumentParser();p.add_argument("--prompt-dir",type=pathlib.Path,required=True);p.add_argument("--user-prompt-manifest",type=pathlib.Path);p.add_argument("--output",type=pathlib.Path,required=True);p.add_argument("--config",default="configs/assistant.json");p.add_argument("--allow-dynamic-clocks",action="store_true");p.add_argument("--allow-dirty-worktree",action="store_true");a=p.parse_args()
 config=load_config(a.config);runtime=config["runtime"];commit,clean,entries,status_hash=git_source_state();locked,clock_detail,clock_output=read_jetson_clock_status()
 if not clean and not a.allow_dirty_worktree:raise RuntimeError("clean worktree required; use --allow-dirty-worktree only for exploratory calibration")
 if not locked and not a.allow_dynamic_clocks:raise RuntimeError(f"fixed clocks required: {clock_detail}")
 check_runtime_assets(config);check_port_available(runtime["host"],runtime["port"])
 user_tokens={}
 if a.user_prompt_manifest:
  for item in json.loads(a.user_prompt_manifest.read_text(encoding="utf-8")): user_tokens[pathlib.Path(item["path"]).resolve()]=item.get("user_prompt_tokens")
 prompts=sorted(a.prompt_dir.glob("*.txt"));
 if not prompts:raise RuntimeError("no UTF-8 prompt files found")
 exploratory=not clean or not locked;process=None;log=None;items=[]
 try:
  log=a.output.with_suffix(".runtime.log").open("wb");process=subprocess.Popen(runtime_command(config),cwd=ROOT,stdout=log,stderr=log);wait_ready(config,process,180)
  for path in prompts:
   prompt=path.read_text(encoding="utf-8");response=post_json(runtime["base_url"]+runtime["chat_endpoint"],runtime_request(config,f"calibrate-{uuid.uuid4().hex}",prompt,1))
   if response.get("client_http_status")!=200 or response.get("error") is not None:raise RuntimeError(f"calibration failed for {path}: {response}")
   items.append({"source_label":path.stem,"label":f"runtime-p{response['prompt_tokens']}","prompt_file":str(path),"prompt_sha256":hashlib.sha256(prompt.encode()).hexdigest(),"user_prompt_tokens":user_tokens.get(path.resolve()),"runtime_prompt_tokens":response["prompt_tokens"]})
 finally:
  stop_process(process)
  if log:log.close()
 result={"status":"EXPLORATORY_UNREVIEWED" if exploratory else "UNREVIEWED_RAW_RESULT","timestamp_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"commit":commit,"worktree_clean":clean,"git_status_entries":entries,"git_status_sha256":status_hash,"clocks_locked":locked,"clock_detail":clock_detail,"clock_output":clock_output,"config_sha256":hashlib.sha256(pathlib.Path(a.config).read_bytes()).hexdigest(),"items":items}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8");print(json.dumps(result,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
