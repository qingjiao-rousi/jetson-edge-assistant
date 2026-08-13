#!/usr/bin/env python3
"""Run a raw Q4 OPT-1 soak; review and interpretation happen separately."""
from __future__ import annotations
import argparse, hashlib, json, pathlib, re, subprocess, sys, time, urllib.request
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_local_assistant import check_runtime_assets, runtime_command, stop_process
from app.assistant.application import check_runtime, load_config
def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=130) as response: return response.status, json.loads(response.read())
    except Exception as error: return 0, {"error": str(error)}
def telemetry_summary(path):
    if not path or not path.is_file(): return {"status": "not_collected"}
    text = path.read_text(encoding="utf-8", errors="replace")
    ram = [int(x) for x in re.findall(r"RAM (\d+)/", text)]
    temps = [float(x) for x in re.findall(r"(?:cpu|gpu)@([0-9.]+)C", text)]
    return {"status": "collected", "samples": len(ram), "ram_used_mb": {"first": ram[0], "last": ram[-1], "peak": max(ram)} if ram else {}, "temperature_c": {"peak": max(temps)} if temps else {}}
def main():
    p=argparse.ArgumentParser(); p.add_argument("--config", required=True); p.add_argument("--prompt-file", required=True, type=pathlib.Path); p.add_argument("--output", required=True, type=pathlib.Path); p.add_argument("--minutes", type=float, default=30); p.add_argument("--interval", type=float, default=0); p.add_argument("--tegrastats")
    a=p.parse_args(); config=load_config(a.config); prompt=a.prompt_file.read_text(encoding="utf-8"); runtime=config["runtime"]
    if runtime["prefix_reuse"] not in ("disabled", "single_hot_text"): print("config must explicitly select disabled or single_hot_text", file=sys.stderr); return 2
    if a.minutes <= 0 or a.minutes > 120: print("minutes must be >0 and <=120", file=sys.stderr); return 2
    output=a.output; output.parent.mkdir(parents=True, exist_ok=True); start=time.monotonic(); rows=[]; telemetry=None
    process=None; log=None; telemetry_process=None; telemetry_file=None
    try:
        check_runtime_assets(config)
        log_path=output.with_suffix(".runtime.log"); log=log_path.open("wb")
        process=subprocess.Popen(runtime_command(config), cwd=ROOT, stdout=log, stderr=log)
        if a.tegrastats:
            telemetry_file=output.with_suffix(".tegrastats.log").open("wb")
            telemetry_process=subprocess.Popen([a.tegrastats, "--interval", "1000"], stdout=telemetry_file, stderr=subprocess.STDOUT)
        ready_deadline=time.monotonic()+180
        while time.monotonic()<ready_deadline:
            try:
                check_runtime(config); break
            except Exception:
                if process.poll() is not None: raise RuntimeError("Runtime exited before /ready")
                time.sleep(.2)
        else: raise RuntimeError("Runtime did not become ready")
        warmup_status, _ = post(runtime["base_url"]+runtime["chat_endpoint"], {"request_id":"soak-warmup","session_id":"benchmark-prefix-session","messages":[{"role":"user","content":prompt}],"max_new_tokens":128,"timeout_ms":120000,"stream":False,"model_sha256":runtime["model"]["sha256"],"sampling":{"seed":424242,"top_k":1,"top_p":1.0,"min_p":0.0,"temperature":0.0}})
        if warmup_status != 200: raise RuntimeError(f"soak warm-up failed: HTTP {warmup_status}")
        deadline=start+a.minutes*60
        while time.monotonic()<deadline:
            status, response=post(runtime["base_url"]+runtime["chat_endpoint"], {"request_id":f"soak-{len(rows)+1}","session_id":"benchmark-prefix-session","messages":[{"role":"user","content":prompt}],"max_new_tokens":128,"timeout_ms":120000,"stream":False,"model_sha256":runtime["model"]["sha256"],"sampling":{"seed":424242,"top_k":1,"top_p":1.0,"min_p":0.0,"temperature":0.0}})
            rows.append({"index":len(rows)+1,"status":status,"response":response,"text_sha256":hashlib.sha256(str(response.get("text","")).encode()).hexdigest()})
            if a.interval: time.sleep(a.interval)
        telemetry_path = output.with_suffix(".tegrastats.log")
        clock = subprocess.run(["/usr/bin/jetson_clocks", "--show"], capture_output=True, text=True, check=False)
        raw={"status":"UNREVIEWED_RAW_RESULT","mode":runtime["prefix_reuse"],"warmup_http_status":warmup_status,"prompt_sha256":hashlib.sha256(prompt.encode()).hexdigest(),"prompt_tokens":rows[0]["response"].get("prompt_tokens") if rows and isinstance(rows[0]["response"],dict) else None,"requests":rows,"telemetry":telemetry_summary(telemetry_path),"clock_telemetry":clock.stdout + clock.stderr,"unified_ram_is_not_a_kv_leak_proof":True}
        output.write_text(json.dumps(raw,indent=2)+"\n")
    finally:
        if telemetry_process is not None: stop_process(telemetry_process)
        if telemetry_file is not None: telemetry_file.close()
        if process is not None: stop_process(process, timeout=20)
        if log is not None: log.close()
    print(output); return 0
if __name__ == "__main__": raise SystemExit(main())
