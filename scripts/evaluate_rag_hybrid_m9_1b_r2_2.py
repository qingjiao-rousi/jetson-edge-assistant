#!/usr/bin/env python3
import argparse,copy,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"scripts"))
from evaluate_rag_hybrid_m9_1b import QUALITY_GATE,quality_gate_result
from rag_hybrid_m9_1b import EmbeddingSpec,provider_from_config
from rag_hybrid_m9_1b_r2 import sha256_file
from rag_hybrid_m9_1b_r2_1 import load_config
from rag_hybrid_m9_1b_r2_2 import ALGORITHM_VERSION,MILESTONE,query_index
def load(path): return json.loads(path.read_text(encoding="utf-8"))["questions"]
def run(database,provider,items,retrieval,details=True):
    ans=sum(x["expected_chunk_id"] is not None for x in items); no=len(items)-ans; a1=a3=fp=reject=0; mrr=0.; rows=[]
    for x in items:
        r=query_index(database,x["query"],3,provider,retrieval); out=[z["chunk_id"] for z in r["results"]]; e=x["expected_chunk_id"]; rank=out.index(e)+1 if e in out else None
        a1+=rank==1; a3+=rank is not None and rank<=3; mrr+=1/rank if rank else 0; reject+=e is None and not r["answerable"]; fp+=e is None and r["answerable"]
        if details: rows.append({"id":x["id"],"expected_chunk_id":e,"returned_chunk_ids":out,"rank":rank,"answerable":r["answerable"],"admission":r["admission"]})
    return {"sample_count":len(items),"answerable_count":ans,"no_answer_count":no,"recall_at_1":a1/max(1,ans),"recall_at_3":a3/max(1,ans),"mrr":mrr/max(1,ans),"no_answer_correct_rejection_rate":reject/max(1,no),"false_positive_count":fp,"questions":rows}
def candidates(base):
    for v in (.4,.5,.6):
      for f in (.25,.5,1.):
       for m in (.0005,.001):
        r=copy.deepcopy(base); r["admission"]={"minimum_vector_score":v,"minimum_keyword_coverage":.1,"minimum_margin":m}; r["fact_evidence"]={"minimum_coverage":f,"minimum_terms":1}; yield r
def calibrate(c,dataset,database):
    p=provider_from_config(c); items=load(dataset); passed=[]
    for r in candidates(c["retrieval"]):
      metrics=run(database,p,items,r,False); gate=quality_gate_result(metrics)
      if gate["passed"]: passed.append((metrics["mrr"],metrics["recall_at_1"],-metrics["false_positive_count"],r,metrics,gate))
    core={"schema_version":1,"milestone":MILESTONE,"phase":"CALIBRATION","algorithm":ALGORITHM_VERSION,"embedding_fingerprint":EmbeddingSpec.from_dict(c["embedding"]).fingerprint,"question_ids":[x["id"] for x in items],"dataset_sha256":sha256_file(dataset),"candidate_count":18,"quality_gate_frozen_for_diagnostic":QUALITY_GATE}
    if not passed:return {**core,"status":"CALIBRATION_FAILED","reason":"no_candidate_satisfies_complete_quality_gate"}
    z=max(passed,key=lambda x:x[:3]); return {**core,"status":"CALIBRATED","retrieval":z[3],"calibration_metrics":z[4],"quality_gate_result":z[5]}
def diagnostic(c,dataset,database,frozen):
    f=json.loads(frozen.read_text());
    if f.get("status")!="CALIBRATED" or f.get("algorithm")!=ALGORITHM_VERSION: raise ValueError("invalid frozen R2.2 calibration")
    metrics=run(database,provider_from_config(c),load(dataset),f["retrieval"],True); gate=quality_gate_result(metrics)
    return {"schema_version":1,"milestone":MILESTONE,"phase":"DIAGNOSTIC_DEV","status":"DONE" if gate["passed"] else "PARTIAL","dataset_sha256":sha256_file(dataset),"quality_gate":QUALITY_GATE,"quality_gate_result":gate,"quality_metrics":metrics,"holdout_execution":"PROHIBITED"}
p=argparse.ArgumentParser();p.add_argument("--phase",choices=("calibration","diagnostic"),required=True);p.add_argument("--database",required=True);p.add_argument("--dataset",required=True);p.add_argument("--output",required=True);p.add_argument("--frozen-calibration");a=p.parse_args(); c=load_config(ROOT/"configs/rag-hybrid-m9.1b-r2.1.json"); r=calibrate(c,ROOT/a.dataset,ROOT/a.database) if a.phase=="calibration" else diagnostic(c,ROOT/a.dataset,ROOT/a.database,ROOT/a.frozen_calibration); (ROOT/a.output).write_text(json.dumps(r,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");print(json.dumps(r,indent=2,ensure_ascii=False))
