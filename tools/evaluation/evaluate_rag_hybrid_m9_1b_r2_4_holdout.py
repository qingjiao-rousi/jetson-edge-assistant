#!/usr/bin/env python3
"""One-time external holdout authorization for frozen M9.1B-R2.4."""
import argparse, hashlib, json, os, pathlib, tempfile, sys
ROOT=pathlib.Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/"scripts"))
from evaluate_rag_hybrid_m9_1b import quality_gate_result
from app.retrieval.core import ContractError, provider_from_config
from app.retrieval.retrieval import sha256_file
from app.retrieval.embedding import load_config
from app.retrieval.lexical import query_index
FROZEN=json.loads((ROOT/"archive/experiments/configs/rag/rag-hybrid-m9.1b-r2.4.json").read_text())
def read(path):
 try:return json.loads(path.read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError) as e:raise ContractError(f"invalid JSON: {path}") from e
def write_new(path,payload):
 if path.exists():raise ContractError(f"refusing to overwrite existing output: {path}")
 path.parent.mkdir(parents=True,exist_ok=True);fd,name=tempfile.mkstemp(dir=path.parent,prefix=f".{path.name}.",suffix=".tmp");tmp=pathlib.Path(name)
 try:
  with os.fdopen(fd,"w",encoding="utf-8") as h:json.dump(payload,h,indent=2,ensure_ascii=False);h.write("\n")
  os.link(tmp,path)
 except FileExistsError as e:raise ContractError(f"refusing to overwrite existing output: {path}") from e
 finally:
  if tmp.exists():tmp.unlink()
def ids(artifact):
 return artifact.get("question_ids",[]) if artifact.get("phase")=="CALIBRATION" else [x.get("id") for x in artifact.get("quality_metrics",{}).get("questions",[])]
def verify(cal,diag):
 if cal.get("status")!="CALIBRATED" or cal.get("milestone")!=FROZEN["milestone"] or cal.get("algorithm_fingerprint")!=FROZEN["algorithm_fingerprint"]:raise ContractError("calibration milestone or algorithm fingerprint mismatch")
 if cal.get("embedding_fingerprint")!=FROZEN["embedding_fingerprint"] or cal.get("retrieval")!=FROZEN["retrieval"] or cal.get("quality_gate_frozen_for_diagnostic")!=FROZEN["quality_gate"]:raise ContractError("calibration embedding, retrieval, or quality gate mismatch")
 if diag.get("status")!="DONE" or diag.get("milestone")!=FROZEN["milestone"] or diag.get("algorithm_fingerprint")!=FROZEN["algorithm_fingerprint"] or diag.get("retrieval")!=FROZEN["retrieval"] or diag.get("quality_gate")!=FROZEN["quality_gate"] or not diag.get("quality_gate_result",{}).get("passed"):raise ContractError("diagnostic artifact mismatch or failure")
def private_questions(path):
 q=read(path).get("questions");
 if not isinstance(q,list) or not q:raise ContractError("private holdout requires questions")
 qids=[x.get("id") for x in q]
 if any(not isinstance(x,str) or not x for x in qids) or len(set(qids))!=len(qids):raise ContractError("private holdout IDs must be unique")
 return q
def authorize(cal_path,diag_path,holdout,output):
 cal=read(cal_path);diag=read(diag_path);verify(cal,diag);q=private_questions(holdout);qids={x["id"] for x in q}
 if qids&set(ids(cal)) or qids&set(ids(diag)):raise ContractError("holdout IDs overlap calibration or diagnostic")
 a={"schema_version":1,"milestone":FROZEN["milestone"],"phase":"HOLDOUT_AUTHORIZATION","execution_state":"AUTHORIZED","algorithm_fingerprint":FROZEN["algorithm_fingerprint"],"embedding_fingerprint":FROZEN["embedding_fingerprint"],"retrieval":FROZEN["retrieval"],"quality_gate":FROZEN["quality_gate"],"holdout_sha256":sha256_file(holdout),"holdout_question_count":len(q),"calibration_sha256":sha256_file(cal_path),"diagnostic_sha256":sha256_file(diag_path)};write_new(output,a);return a
def metrics(db,p,q,r):
 ans=sum(x["expected_chunk_id"] is not None for x in q);no=len(q)-ans;a1=a3=rej=fp=0;mrr=0;rows=[]
 for x in q:
  z=query_index(db,x["query"],3,p,r);got=[v["chunk_id"] for v in z["results"]];e=x["expected_chunk_id"];rank=got.index(e)+1 if e in got else None;a1+=rank==1;a3+=rank is not None and rank<=3;mrr+=1/rank if rank else 0;rej+=e is None and not z["answerable"];fp+=e is None and z["answerable"];rows.append({"id":x["id"],"expected_chunk_id":e,"returned_chunk_ids":got,"rank":rank,"answerable":z["answerable"],"admission":z["admission"]})
 return {"sample_count":len(q),"answerable_count":ans,"no_answer_count":no,"recall_at_1":a1/ans,"recall_at_3":a3/ans,"mrr":mrr/ans,"no_answer_correct_rejection_rate":rej/no,"false_positive_count":fp,"questions":rows}
def holdout(db,holdout,auth_path,output):
 if output.exists():raise ContractError(f"refusing to overwrite existing output: {output}")
 a=read(auth_path)
 if a.get("execution_state")!="AUTHORIZED":raise ContractError("authorization has already been consumed")
 if any(a.get(k)!=FROZEN[k] for k in ("milestone","algorithm_fingerprint","embedding_fingerprint","retrieval","quality_gate")):raise ContractError("authorization frozen contract mismatch")
 if sha256_file(holdout)!=a.get("holdout_sha256"):raise ContractError("holdout SHA-256 mismatch")
 q=private_questions(holdout)
 if len(q)!=a.get("holdout_question_count"):raise ContractError("holdout question count mismatch")
 consumed=dict(a,execution_state="CONSUMED");tmp=auth_path.with_name(f".{auth_path.name}.consume.tmp");tmp.write_text(json.dumps(consumed,indent=2)+"\n");os.replace(tmp,auth_path)
 c=load_config(ROOT/"configs/embedding.json");met=metrics(db,provider_from_config(c),q,FROZEN["retrieval"]);gate=quality_gate_result(met);r={"schema_version":1,"milestone":FROZEN["milestone"],"phase":"HOLDOUT","status":"DONE" if gate["passed"] else "PARTIAL","algorithm_fingerprint":FROZEN["algorithm_fingerprint"],"holdout_sha256":a["holdout_sha256"],"holdout_question_count":len(q),"authorization_sha256":sha256_file(auth_path),"retrieval":FROZEN["retrieval"],"quality_gate":FROZEN["quality_gate"],"quality_gate_result":gate,"quality_metrics":met};write_new(output,r);return r
def main():
 p=argparse.ArgumentParser();p.add_argument("--phase",choices=("authorize-holdout","holdout"),required=True);p.add_argument("--calibration");p.add_argument("--diagnostic");p.add_argument("--database");p.add_argument("--holdout",required=True);p.add_argument("--authorization");p.add_argument("--output",required=True);a=p.parse_args()
 if a.phase=="authorize-holdout":
  if not a.calibration or not a.diagnostic:raise ContractError("authorize-holdout requires --calibration and --diagnostic")
  r=authorize(pathlib.Path(a.calibration),pathlib.Path(a.diagnostic),pathlib.Path(a.holdout),pathlib.Path(a.output))
 else:
  if not a.database or not a.authorization:raise ContractError("holdout requires --database and --authorization")
  r=holdout(ROOT/a.database,pathlib.Path(a.holdout),pathlib.Path(a.authorization),pathlib.Path(a.output))
 print(json.dumps(r,indent=2,ensure_ascii=False))
if __name__=="__main__":main()
