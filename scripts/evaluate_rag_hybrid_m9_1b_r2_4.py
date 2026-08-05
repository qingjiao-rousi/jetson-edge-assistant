#!/usr/bin/env python3
import argparse,copy,hashlib,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
from evaluate_rag_hybrid_m9_1b import QUALITY_GATE,quality_gate_result
from rag_hybrid_m9_1b import EmbeddingSpec,provider_from_config
from rag_hybrid_m9_1b_r2 import sha256_file
from rag_hybrid_m9_1b_r2_1 import load_config
from rag_hybrid_m9_1b_r2_4 import ALGORITHM_VERSION,MILESTONE,query_index
MARGINS=(.0001,.0002,.00025,.0003,.0005); VECTORS=(.4,.5,.6); FACTS=(.25,.5,1.)
def items(p):return json.loads(p.read_text())["questions"]
def run(db,p,qs,r,detail):
 a=sum(q["expected_chunk_id"] is not None for q in qs);n=len(qs)-a;x=y=rej=fp=0;m=0;out=[]
 for q in qs:
  z=query_index(db,q["query"],3,p,r);got=[v["chunk_id"] for v in z["results"]];e=q["expected_chunk_id"];rank=got.index(e)+1 if e in got else None;x+=rank==1;y+=rank is not None and rank<=3;m+=1/rank if rank else 0;rej+=e is None and not z["answerable"];fp+=e is None and z["answerable"]
  if detail:out.append({"id":q["id"],"expected_chunk_id":e,"returned_chunk_ids":got,"rank":rank,"answerable":z["answerable"],"admission":z["admission"]})
 return {"sample_count":len(qs),"answerable_count":a,"no_answer_count":n,"recall_at_1":x/a,"recall_at_3":y/a,"mrr":m/a,"no_answer_correct_rejection_rate":rej/n,"false_positive_count":fp,"questions":out}
def grid(base):
 for v in VECTORS:
  for f in FACTS:
   for c in FACTS:
    for m in MARGINS:
     r=copy.deepcopy(base);r["admission"]={"minimum_vector_score":v,"minimum_keyword_coverage":.1,"minimum_margin":m};r["fact_evidence"]={"minimum_coverage":f,"minimum_terms":1};r["concept_lexical"]={"minimum_coverage":c};yield r
def calibrate(c,db,data):
 p=provider_from_config(c);qs=items(data);all=[];passed=[]
 for r in grid(c["retrieval"]):
  met=run(db,p,qs,r,False);g=quality_gate_result(met);z={"retrieval":r,"metrics":met,"quality_gate_result":g};all.append(z);passed+= [z] if g["passed"] else []
 base={"schema_version":1,"milestone":MILESTONE,"phase":"CALIBRATION","algorithm":ALGORITHM_VERSION,"embedding_fingerprint":EmbeddingSpec.from_dict(c["embedding"]).fingerprint,"dataset_sha256":sha256_file(data),"question_ids":[q["id"] for q in qs],"candidate_count":len(all),"candidates":all,"quality_gate_frozen_for_diagnostic":QUALITY_GATE}
 if not passed:return {**base,"status":"CALIBRATION_FAILED"}
 z=max(passed,key=lambda q:(q["metrics"]["mrr"],q["metrics"]["recall_at_1"],-q["retrieval"]["admission"]["minimum_margin"]));fp=hashlib.sha256(json.dumps({"algorithm":ALGORITHM_VERSION,"retrieval":z["retrieval"]},sort_keys=True).encode()).hexdigest();return {**base,"status":"CALIBRATED","retrieval":z["retrieval"],"calibration_metrics":z["metrics"],"quality_gate_result":z["quality_gate_result"],"algorithm_fingerprint":fp}
def diagnostic(c,db,data,frozen):
 f=json.loads(frozen.read_text());
 if f.get("status")!="CALIBRATED":raise ValueError("invalid frozen calibration")
 met=run(db,provider_from_config(c),items(data),f["retrieval"],True);g=quality_gate_result(met);return {"schema_version":1,"milestone":MILESTONE,"phase":"DIAGNOSTIC_DEV","status":"DONE" if g["passed"] else "PARTIAL","algorithm":ALGORITHM_VERSION,"algorithm_fingerprint":f["algorithm_fingerprint"],"retrieval":f["retrieval"],"quality_gate":QUALITY_GATE,"quality_gate_result":g,"quality_metrics":met,"holdout_execution":"PROHIBITED"}
p=argparse.ArgumentParser();p.add_argument("--phase",choices=("calibration","diagnostic"),required=True);p.add_argument("--database",required=True);p.add_argument("--dataset",required=True);p.add_argument("--output",required=True);p.add_argument("--frozen-calibration");a=p.parse_args();c=load_config(ROOT/"configs/rag-hybrid-m9.1b-r2.1.json");r=calibrate(c,ROOT/a.database,ROOT/a.dataset) if a.phase=="calibration" else diagnostic(c,ROOT/a.database,ROOT/a.dataset,ROOT/a.frozen_calibration);(ROOT/a.output).write_text(json.dumps(r,indent=2,ensure_ascii=False)+"\n");print(json.dumps(r,indent=2,ensure_ascii=False))
