#!/usr/bin/env python3
"""M8.2 one-service/one-request supervisor for the application API route."""
import base64, hashlib, http.client, json, os, pathlib, signal, socket, subprocess, sys, time, urllib.error, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[2]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(65536),b''):h.update(b)
 return h.hexdigest()
def redact_body(data):
 try:
  parsed=json.loads(data.decode('utf-8','replace'))
  def walk(value):
   if isinstance(value,dict): return {k:('[REDACTED]' if k=='data_base64' else walk(v)) for k,v in value.items()}
   if isinstance(value,list): return [walk(v) for v in value]
   return value
  return json.dumps(walk(parsed),ensure_ascii=True)
 except Exception:return data[:4096].decode('utf-8','replace')
def perform_http_request(url,payload,timeout=900):
 started=time.monotonic(); evidence={'request_stage':'http_post','http_status':None,'reason':None,'headers':{},'response_bytes':0,'response_body_redacted':'','exception_type':None,'exception_message':None,'elapsed_ms':0}
 try:
  req=urllib.request.Request(url,data=payload,headers={'Content-Type':'application/json'},method='POST')
  with urllib.request.urlopen(req,timeout=timeout) as response:
   raw=response.read();evidence.update(http_status=response.status,reason=response.reason,headers=dict(response.headers.items()),response_bytes=len(raw),response_body_redacted=redact_body(raw));return raw.decode('utf-8'),evidence
 except urllib.error.HTTPError as error:
  raw=error.read();evidence.update(http_status=error.code,reason=error.reason,headers=dict(error.headers.items()) if error.headers else {},response_bytes=len(raw),response_body_redacted=redact_body(raw),exception_type=type(error).__name__,exception_message=str(error))
 except urllib.error.URLError as error:
  evidence.update(exception_type='TimeoutError' if isinstance(error.reason,socket.timeout) else type(error).__name__,exception_message=str(error.reason))
 except socket.timeout as error:evidence.update(exception_type=type(error).__name__,exception_message=str(error))
 except http.client.RemoteDisconnected as error:evidence.update(exception_type=type(error).__name__,exception_message=str(error))
 except Exception as error:evidence.update(exception_type=type(error).__name__,exception_message=str(error),request_stage='response_parse')
 finally:evidence['elapsed_ms']=round((time.monotonic()-started)*1000)
 return None,evidence
def classify_failure(evidence):
 if evidence['http_status']==404:return 'route_not_found'
 if evidence['http_status']==413:return 'payload_limit'
 if evidence['http_status'] in (400,409,422,429):return 'request_rejected'
 if evidence['exception_type'] in ('RemoteDisconnected','ConnectionResetError'):return 'connection_closed'
 if evidence['exception_type'] in ('TimeoutError','socket.timeout'):return 'http_timeout'
 return 'internal'
def parse_sse(text):
 events=[]
 if not text:return events
 for block in text.strip().split('\n\n'):
  lines=block.splitlines();event=next((line[7:] for line in lines if line.startswith('event: ')),None);data=next((line[6:] for line in lines if line.startswith('data: ')),None)
  if event is None or data is None:raise ValueError('malformed SSE event')
  events.append({'event':event,'data':json.loads(data)})
 return events
def valid_sse_sequence(events):
 if len(events)<2 or events[0]['event']!='metadata':return False
 terminals={'done','error','cancelled','timeout'}
 terminal_indexes=[i for i,event in enumerate(events) if event['event'] in terminals]
 return terminal_indexes==[len(events)-1] and all(event['event']=='token' for event in events[1:-1])
def main():
 if len(sys.argv)!=3:return 2
 host=pathlib.Path(sys.argv[1]).resolve();out=pathlib.Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=False);port=18086
 model=ROOT/'models/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf';mm=ROOT/'models/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf';img=ROOT/'third_party/llama.cpp-omni/tools/mtmd/test-1.jpeg'
 expected={str(model.relative_to(ROOT)):'d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12',str(mm.relative_to(ROOT)):'980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904',str(img.relative_to(ROOT)):'2dff664c0c8aaea18aff8cbe7e868845b775e90cdd7a0bac98df709b131deaa3'}
 assets={str(x.relative_to(ROOT)):{'size_bytes':x.stat().st_size,'sha256':sha(x),'expected_sha256':expected[str(x.relative_to(ROOT))],'ok':sha(x)==expected[str(x.relative_to(ROOT))]} for x in (model,mm,img)};(out/'asset-verification.json').write_text(json.dumps(assets,indent=2)+'\n');(out/'command.txt').write_text(f'{host} {port}\n')
 preflight={'host_binary':str(host),'host_executable':host.is_file() and os.access(host,os.X_OK),'tegrastats_available':pathlib.Path('/usr/bin/tegrastats').is_file(),'assets_ok':all(value['ok'] for value in assets.values())}
 (out/'launcher-preflight.json').write_text(json.dumps(preflight,indent=2)+'\n')
 stdout=(out/'service-stdout.log').open('w');stderr=(out/'service-stderr.log').open('w');tele=(out/'tegrastats.log').open('w');t=subprocess.Popen(['/usr/bin/tegrastats','--interval','250'],stdout=tele,stderr=subprocess.STDOUT,start_new_session=True);p=subprocess.Popen([str(host),str(port)],cwd=ROOT,stdout=stdout,stderr=stderr,start_new_session=True)
 ready=False
 for _ in range(120):
  try:
   with urllib.request.urlopen(f'http://127.0.0.1:{port}/ready',timeout=1) as r: ready=json.loads(r.read()).get('ready')
   if ready:break
  except Exception:time.sleep(.25)
 raw=img.read_bytes();body={'request_id':'m8.2r-new-york-times','prompt':'Describe the image and identify the newspaper publisher. Answer in concise English.','stream':True,'images':[{'id':'test-1.jpeg','mime':'image/jpeg','data_base64':base64.b64encode(raw).decode()}]};(out/'request-summary.json').write_text(json.dumps({'request_id':body['request_id'],'prompt':body['prompt'],'stream':True,'base64_length':len(body['images'][0]['data_base64']),'image':assets[str(img.relative_to(ROOT))]},indent=2)+'\n')
 failure=None;events=[]
 try:
  text,http_evidence=perform_http_request(f'http://127.0.0.1:{port}/v1/diagnose/image',json.dumps(body).encode())
  (out/'http-response.json').write_text(json.dumps(http_evidence,indent=2)+'\n')
  if text is None:raise RuntimeError(classify_failure(http_evidence))
  status=http_evidence['http_status']
  events=parse_sse(text)
  terminal=events[-1]['data'] if events else {};ok=ready and status==200 and valid_sse_sequence(events) and events[-1]['event']=='done' and 'The New York Times' in terminal.get('text','')
  if not ok:failure='quality_gate_failed'
 except Exception as e:
  status=None;terminal={};failure=str(e) if str(e) in {'route_not_found','request_rejected','payload_limit','connection_closed','http_timeout'} else 'sse_protocol_failed' if text else 'internal'
  if 'http_evidence' in locals() and text:
   http_evidence.update(exception_type=type(e).__name__,exception_message=str(e),request_stage='sse_parse')
   (out/'http-response.json').write_text(json.dumps(http_evidence,indent=2)+'\n')
 (out/'sse-events.json').write_text(json.dumps(events,indent=2)+'\n');os.killpg(p.pid,signal.SIGTERM)
 try:code=p.wait(30)
 except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);code=p.wait()
 os.killpg(t.pid,signal.SIGTERM);t.wait(10);stdout.close();stderr.close();tele.close()
 backend_generate_invoked=any(event['event'] in {'token','done','error','cancelled','timeout'} for event in events)
 inference_count=1 if backend_generate_invoked else 0
 result={'status':'SUCCESS' if not failure else 'FAILED','failure_class':failure,'service_process_start_count':1,'application_request_attempt_count':1,'cumulative_application_request_attempt_count':2,'backend_generate_invoked':backend_generate_invoked,'request_count':1,'inference_run_count':inference_count,'cumulative_inference_run_count':inference_count,'retry_count':0,'child_exit_code':code,'sse_order':[x['event'] for x in events],'response':terminal,'assets':assets};(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');(out/'process-status.txt').write_text(f'service_exit_code={code}\ntegra_stopped={t.poll() is not None}\n');return 0 if not failure else 1
if __name__=='__main__':sys.exit(main())
