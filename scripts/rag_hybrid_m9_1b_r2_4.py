"""R2.4 concept-aware lexical admission over the unchanged R2 index."""
from __future__ import annotations
import copy
import rag_hybrid_m9_1b_r2 as R2
from rag_hybrid_m9_1b import ContractError

MILESTONE="M9.1B-R2.4"; ALGORITHM_VERSION="concept-lexical-evidence-v1"; LEXICON_VERSION="industrial-concepts-v2"
FAMILIES={
 "maintenance":(("service","servicing","interval","schedule","inspection","inspect","operating hours"),("维护","保养","周期","检查","张力","对中","小时")),
 "pressure":(("pressure","outlet","kpa","mpa"),("压力",)), "temperature":(("temperature","fluid"),("温度",)),
 "reset":(("reset","emergency stop"),("复位","急停")), "cavitation":(("cavitation","vapor","bubbles","suction","rattling"),("气蚀","气泡","吸入")),
 "tracking":(("tracking","belt","alignment","roller"),("跑偏","输送带","对中","滚筒")), "torque":(("torque","shaft"),("扭矩",)),
 "fault_meaning":(("alarm","fault","error","meaning"),("报警","故障","含义")), "oil":(("oil","lubricant","viscosity","grade"),("油品","润滑","粘度")),
}
GENERIC={"hydraulic","pump","maintenance","check","required","what","when","which","does"}
def evidence(query,heading,text,devices,codes):
 q=query.lower(); h=heading.lower(); body=text.lower(); requested=[]; matched=[]
 for name,(en,zh) in FAMILIES.items():
  q_en=[x for x in en if x in q and x not in GENERIC and x.lower() not in {z.lower() for z in devices|codes}];q_zh=[x for x in zh if x in query]
  # Maintenance requires a relation phrase/two domain terms; bare maintenance/check is not evidence.
  if name=="maintenance" and len(q_en)+len(q_zh)<2: continue
  if not q_en and not q_zh: continue
  requested.append(name);hm=[x for x in en if x in h]+[x for x in zh if x in heading];cm=[x for x in en if x in body]+[x for x in zh if x in text]
  if hm or cm: matched.append({"family":name,"heading_matches":hm,"content_matches":cm})
 return {"lexicon_version":LEXICON_VERSION,"requested_families":requested,"matched_families":matched,"coverage":len(matched)/len(requested) if requested else 0.0}
def query_index(database,query,top_k,provider,retrieval):
 raw=copy.deepcopy(retrieval);raw.pop("concept_lexical",None);raw.pop("fact_evidence",None);raw["admission"]={"minimum_vector_score":0.,"minimum_keyword_coverage":0.,"minimum_margin":0.}
 response=R2.query_index(database,query,top_k,provider,raw)
 if not response["results"]:
  response["admission"]["reasons"]=list(dict.fromkeys(response["admission"]["reasons"]+["missing_concept_lexical_evidence"]));return response
 top=response["results"][0];constraints=response["constraints"];ev=evidence(query,top["heading"],top["text"],set(constraints["devices"]),set(constraints["fault_codes"]))
 base=response["admission"];reasons=[]
 if ev["coverage"]<retrieval["fact_evidence"]["minimum_coverage"]:reasons.append("missing_fact_family_evidence")
 if ev["coverage"]<retrieval["concept_lexical"]["minimum_coverage"]:reasons.append("missing_concept_lexical_evidence")
 if base["vector_score"]<retrieval["admission"]["minimum_vector_score"]:reasons.append("vector_score_below_threshold")
 if base["margin"]<retrieval["admission"]["minimum_margin"]:reasons.append("top1_top2_margin_below_threshold")
 response["admission"]={**base,"passed":not reasons,"reasons":reasons,"fact_evidence":ev,"concept_lexical_evidence":ev}
 if reasons:response["answerable"]=False;response["results"]=[];response["citations"]=[]
 return response
