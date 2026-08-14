#!/usr/bin/env python3
"""Collect raw OPT-1 soak evidence; it never declares a reviewed result."""
from __future__ import annotations
import argparse,datetime,hashlib,json,pathlib,re,subprocess,sys,time,uuid
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/"scripts")]
from app.assistant.application import check_runtime,load_config
from run_jetson_benchmark import git_source_state,read_jetson_clock_status,runtime_request,post_json,wait_ready
from run_local_assistant import check_port_available,check_runtime_assets,runtime_command,stop_process
def telemetry(path):
 text=path.read_text(encoding="utf-8",errors="replace") if path.is_file() else "";ram=[int(x) for x in re.findall(r"RAM (\d+)/",text)];temp=[float(x) for x in re.findall(r"(?:cpu|gpu)@([0-9.]+)C",text)]
 return {"samples":len(ram),"ram_used_mb":{"first":ram[0],"last":ram[-1],"peak":max(ram)} if ram else {},"temperature_c":{"peak":max(temp)} if temp else {},"unified_ram_is_not_a_kv_leak_proof":True}
def main():
 p=argparse.ArgumentParser();p.add_argument("--config",required=True);p.add_argument("--prompt-file",type=pathlib.Path,required=True);p.add_argument("--output",type=pathlib.Path,required=True);p.add_argument("--minutes",type=float,default=30);p.add_argument("--interval",type=float,default=0);p.add_argument("--tegrastats",default="/usr/bin/tegrastats");p.add_argument("--allow-dynamic-clocks",action="store_true");p.add_argument("--allow-dirty-worktree",action="store_true");a=p.parse_args()
 if a.minutes<=0 or a.minutes>120:raise ValueError("minutes must be >0 and <=120")
 config=load_config(a.config);runtime=config["runtime"];prompt=a.prompt_file.read_text(encoding="utf-8")
 if runtime["prefix_reuse"] not in ("disabled","single_hot_text"):raise ValueError("config must explicitly use disabled or single_hot_text")
 commit,clean,entries,status_hash=git_source_state();locked,clock_detail,clock_output=read_jetson_clock_status();exploratory=not clean or not locked
 if not clean and not a.allow_dirty_worktree:raise RuntimeError("clean worktree required; use --allow-dirty-worktree only for exploratory raw")
 if not locked and not a.allow_dynamic_clocks:raise RuntimeError(f"fixed clocks required: {clock_detail}")
 check_runtime_assets(config);check_port_available(runtime["host"],runtime["port"])
 a.output.parent.mkdir(parents=True,exist_ok=True);log_path=a.output.with_suffix(".runtime.log");tegra_path=a.output.with_suffix(".tegrastats.log");rows=[];reason=None;warmup=None;start=None;end=None;process=None;tegrastats=None;log=None
 try:
  log=log_path.open("wb");process=subprocess.Popen(runtime_command(config),cwd=ROOT,stdout=log,stderr=log);wait_ready(config,process,180)
  tf=tegra_path.open("wb");tegrastats=subprocess.Popen([a.tegrastats,"--interval","1000"],stdout=tf,stderr=subprocess.STDOUT)
  warmup=post_json(runtime["base_url"]+runtime["chat_endpoint"],runtime_request(config,"soak-warmup",prompt,1))
  if warmup.get("client_http_status")!=200 or warmup.get("error") is not None:raise RuntimeError(f"warm-up failed: {warmup}")
  start=time.monotonic();start_utc=datetime.datetime.now(datetime.timezone.utc).isoformat();deadline=start+a.minutes*60
  while time.monotonic()<deadline:
   response=post_json(runtime["base_url"]+runtime["chat_endpoint"],runtime_request(config,f"soak-{uuid.uuid4().hex}",prompt,128));rows.append({"index":len(rows)+1,"response":response,"text_sha256":hashlib.sha256(response.get("text","").encode()).hexdigest()})
   if a.interval:time.sleep(a.interval)
 except Exception as error:reason=str(error)
 finally:
  end=time.monotonic();end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat();stop_process(tegrastats)
  if 'tf' in locals():tf.close()
  if process:stop_process(process)
  if log:log.close()
  raw={"status":"INCOMPLETE" if reason else ("EXPLORATORY_UNREVIEWED" if exploratory else "UNREVIEWED_RAW_RESULT"),"failure_reason":reason,"mode":runtime["prefix_reuse"],"commit":commit,"worktree_clean":clean,"git_status_entries":entries,"git_status_sha256":status_hash,"model_sha256":runtime["model"]["sha256"],"mmproj_sha256":runtime["mmproj"]["sha256"],"config_sha256":hashlib.sha256(pathlib.Path(a.config).read_bytes()).hexdigest(),"prompt_sha256":hashlib.sha256(prompt.encode()).hexdigest(),"clock_locked":locked,"clock_detail":clock_detail,"clock_output":clock_output,"started_utc":start_utc if start else None,"ended_utc":end_utc,"measured_duration_seconds":round(end-start,3) if start else 0,"warmup":warmup,"requests":rows,"telemetry":telemetry(tegra_path)}
  a.output.write_text(json.dumps(raw,indent=2)+"\n",encoding="utf-8")
 print(a.output);return 1 if reason else 0
if __name__=="__main__":raise SystemExit(main())
