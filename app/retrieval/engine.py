"""R2.5 token/phrase fact-family evidence with core-family alignment."""
from __future__ import annotations
import copy,re
from . import retrieval as R2
MILESTONE="M9.1B-R2.5";ALGORITHM_VERSION="core-fact-family-v1";LEXICON_VERSION="industrial-concepts-v3"
F={"maintenance":(("service interval","maintenance schedule","operating hours","inspection","inspect","service","servicing"),("检查周期","运行小时","张力检查","对中检查","维护","保养")),"temperature":(("fluid temperature","temperature"),("温度",)),"oil":(("hydraulic fluid","lubricant","viscosity","grade","oil"),("液压油","油品","润滑","粘度")),"pressure":(("outlet pressure","pressure","kpa","mpa"),("压力",)),"tracking":(("belt tracking","tracking","alignment","roller"),("跑偏","输送带","对中","滚筒")),"cavitation":(("vapor bubbles","cavitation","suction","rattling"),("气蚀","气泡","吸入")),"reset":(("emergency stop","reset"),("复位","急停")),"torque":(("shaft torque","torque"),("扭矩",)),"fault":(("alarm","fault","error"),("报警","故障")),"specification":(("technical specifications","specification","specified","specify","documented","limits"),("规格","参数","限值"))}
GEN={"hydraulic","pump","maintenance","check","what","when","which","does","required"}
def tokens(s):return re.findall(r"[a-z0-9]+",s.lower())
def has_phrase(text,phrase):
 t=tokens(text);p=tokens(phrase)
 return bool(p) and any(t[i:i+len(p)]==p for i in range(len(t)-len(p)+1))
def english_matches(text,phrases):
 """Return non-overlapping longest phrase matches, preserving word boundaries."""
 source=tokens(text); candidates=sorted(((tokens(x),x) for x in phrases),key=lambda x:(-len(x[0]),x[1]))
 found=[];i=0
 while i<len(source):
  hit=next(((parts,label) for parts,label in candidates if parts and source[i:i+len(parts)]==parts),None)
  if hit:found.append(hit[1]);i+=len(hit[0])
  else:i+=1
 return found
def chinese_matches(text,phrases):
 """CJK has no whitespace boundaries; aliases are explicit domain phrases."""
 return [x for x in sorted(phrases,key=len,reverse=True) if x in text]
def match(text,en,zh):return english_matches(text,en)+chinese_matches(text,zh)
def evidence(query,heading,text,devices,codes):
 req=[];matched=[];idents={x.lower() for x in devices|codes}
 for name,(en,zh) in F.items():
  q=[x for x in match(query,en,zh) if x not in GEN and x.lower() not in idents]
  if not q:continue
  req.append(name);hm=match(heading,en,zh);cm=match(text,en,zh)
  if hm or cm:matched.append({"family":name,"heading_matches":hm,"content_matches":cm})
 return {"lexicon_version":LEXICON_VERSION,"core_families":req,"matched_families":matched,"coverage":len(matched)/len(req) if req else 0.0,"core_aligned":bool(req) and {x["family"] for x in matched}>=set(req)}
def query_index(db,q,k,p,r):
 raw=copy.deepcopy(r);raw.pop("fact_evidence",None);raw.pop("concept_lexical",None);raw["admission"]={"minimum_vector_score":0,"minimum_keyword_coverage":0,"minimum_margin":0}
 z=R2.query_index(db,q,k,p,raw)
 if not z["results"]:z["admission"]["reasons"]=list(dict.fromkeys(z["admission"]["reasons"]+["missing_core_fact_family"]));return z
 top=z["results"][0];e=evidence(q,top["heading"],top["text"],set(z["constraints"]["devices"]),set(z["constraints"]["fault_codes"]));b=z["admission"];re=[]
 if not e["core_aligned"] or e["coverage"]<r["fact_evidence"]["minimum_coverage"]:re.append("missing_core_fact_family")
 if b["vector_score"]<r["admission"]["minimum_vector_score"]:re.append("vector_score_below_threshold")
 if b["margin"]<r["admission"]["minimum_margin"]:re.append("top1_top2_margin_below_threshold")
 z["admission"]={**b,"passed":not re,"reasons":re,"fact_evidence":e};
 if re:z["answerable"]=False;z["results"]=[];z["citations"]=[]
 return z
