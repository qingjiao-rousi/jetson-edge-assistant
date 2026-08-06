#!/usr/bin/env python3
"""M7.5C-R one-process, three-request supervisor; no request or service retries."""
import base64, hashlib, json, os, pathlib, signal, subprocess, sys, time, urllib.request
ROOT = pathlib.Path(__file__).resolve().parents[2]
HASHES={"models/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf":"d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12","models/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf":"980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904"}
def digest(p):
 h=hashlib.sha256();
 with p.open('rb') as f:
  for b in iter(lambda:f.read(65536),b''):h.update(b)
 return h.hexdigest()
def get(url, body=None):
 req=urllib.request.Request(url, data=body, headers={"Content-Type":"application/json"}, method="POST" if body else "GET")
 with urllib.request.urlopen(req, timeout=900) as r:return r.status,r.read().decode()
def main():
 if len(sys.argv)!=3: print('usage: runner HOST_BINARY OUTPUT');return 2
 host=pathlib.Path(sys.argv[1]).resolve(); out=pathlib.Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=False); port=18085
 assets={};
 for rel, expected in HASHES.items():
  p=ROOT/rel; assets[rel]={"size_bytes":p.stat().st_size,"sha256":digest(p),"expected_sha256":expected,"ok":digest(p)==expected}
 fixtures=[("new-york-times",ROOT/'third_party/llama.cpp-omni/tools/mtmd/test-1.jpeg','image/jpeg','Describe the image and identify the newspaper publisher. Answer in concise English.',True),('synthetic-alarm',ROOT/'tests/fixtures/vlm-service/synthetic-alarm-panel.png','image/png','Describe the synthetic alarm panel in concise English.',False),('synthetic-device',ROOT/'tests/fixtures/vlm-service/synthetic-device-panel.png','image/png','Describe the synthetic device panel in concise English.',False)]
 for _,p,_,_,_ in fixtures: assets[str(p.relative_to(ROOT))]={"size_bytes":p.stat().st_size,"sha256":digest(p)}
 (out/'asset-verification.json').write_text(json.dumps(assets,indent=2)+'\n')
 (out/'command.txt').write_text(f'{host} {port}\n'); (out/'service-config.json').write_text((ROOT/'evidence/milestones/configs/vlm/vlm-service-image-suite-m7.5c.json').read_text())
 (out/'launcher-preflight.json').write_text(json.dumps({"true_exit_code":subprocess.run(['/bin/true']).returncode,"host_exists":host.is_file()},indent=2)+'\n')
 stdout=(out/'service-stdout.log').open('w'); stderr=(out/'service-stderr.log').open('w'); tele=(out/'tegrastats.log').open('w')
 tegra=subprocess.Popen(['/usr/bin/tegrastats','--interval','250'],stdout=tele,stderr=subprocess.STDOUT,start_new_session=True)
 proc=subprocess.Popen([str(host),str(port)],cwd=ROOT,stdout=stdout,stderr=stderr,start_new_session=True)
 started=False
 for _ in range(120):
  if proc.poll() is not None:break
  try:
   if json.loads(get(f'http://127.0.0.1:{port}/ready')[1]).get('ready'):started=True;break
  except Exception: time.sleep(.25)
 results=[]; failure=None
 if started:
  for idx,(rid,path,mime,prompt,gate) in enumerate(fixtures,1):
   raw=path.read_bytes(); body={"request_id":rid,"messages":[{"role":"user","content":prompt}],"max_new_tokens":128,"stream":True,"images":[{"id":path.name,"mime":mime,"data_base64":base64.b64encode(raw).decode()}]}
   (out/f'request-{idx}.json').write_text(json.dumps({"request_id":rid,"stream":True,"image":{"id":path.name,"mime":mime,"size_bytes":len(raw),"sha256":digest(path)}},indent=2)+'\n')
   try:
    status,text=get(f'http://127.0.0.1:{port}/v1/generate',json.dumps(body).encode()); events=[]
    for block in text.strip().split('\n\n'):
     lines=block.splitlines(); event=next((x[7:] for x in lines if x.startswith('event: ')),None); data=next((x[6:] for x in lines if x.startswith('data: ')),None)
     if event: events.append({"event":event,"data":json.loads(data) if data else None})
    (out/f'sse-events-{idx}.json').write_text(json.dumps(events,indent=2)+'\n'); terminal=events[-1] if events else {}; response=terminal.get('data',{}); order=bool(events and events[0]['event']=='metadata' and terminal.get('event')=='done' and all(e['event']=='token' for e in events[1:-1])); summary={"http_status":status,"sse_order_ok":order,"event_count":len(events),"response":response}; (out/f'response-summary-{idx}.json').write_text(json.dumps(summary,indent=2)+'\n')
    ok=status==200 and order and response.get('text') and (not gate or 'The New York Times' in response.get('text','')); results.append({"request_id":rid,"ok":bool(ok),"summary":summary})
    if not ok: failure='quality_gate_failed' if gate else 'sse_protocol_failed';break
   except Exception as e: results.append({"request_id":rid,"ok":False,"error":str(e)});failure='internal';break
 else: failure='service_start_failed'
 os.killpg(proc.pid,signal.SIGTERM)
 try: exit_code=proc.wait(30)
 except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL);exit_code=proc.wait()
 os.killpg(tegra.pid,signal.SIGTERM);tegra.wait(10);stdout.close();stderr.close();tele.close()
 result={"status":"SUCCESS" if not failure and len(results)==3 else "FAILED","failure_class":failure,"service_process_start_count":1,"request_count":len(results),"inference_run_count":len(results),"retry_count":0,"child_exit_code":exit_code,"requests":results,"assets":assets}
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');(out/'process-status.txt').write_text(f'service_exit_code={exit_code}\ntegra_stopped={tegra.poll() is not None}\n');return 0 if result['status']=='SUCCESS' else 1
if __name__=='__main__':sys.exit(main())
