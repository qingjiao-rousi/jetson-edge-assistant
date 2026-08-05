"""M9.1B-R2.2 concept/fact-family admission over frozen R2 ranking."""
from __future__ import annotations
import copy, hashlib, json, pathlib, sqlite3
import rag_hybrid_m9_1b_r2 as R2
from rag_hybrid_m9_1b import ContractError, EmbeddingProvider

ROOT = R2.ROOT
MILESTONE = "M9.1B-R2.2"
ALGORITHM_VERSION = "concept-fact-family-v1"
LEXICON_VERSION = "industrial-concepts-v1"
CONCEPTS = {
 "maintenance_interval": (("maintenance", "schedule", "inspection", "inspect", "service", "interval", "operating hours", "maintenance schedule"), ("维护", "保养", "检查", "周期", "小时")),
 "pressure": (("pressure", "kpa", "mpa", "outlet"), ("压力",)),
 "temperature": (("temperature", "thermal", "fluid temperature"), ("温度",)),
 "torque": (("torque", "shaft torque"), ("扭矩",)),
 "reset": (("reset", "emergency stop", "restart"), ("复位", "急停")),
 "cavitation": (("cavitation", "vapor", "bubbles", "rattling", "suction"), ("气蚀", "气泡", "吸入")),
 "belt_tracking": (("tracking", "belt", "alignment", "roller"), ("跑偏", "输送带", "对中", "滚筒")),
 "fault_meaning": (("alarm", "fault", "error", "mean", "meaning"), ("故障", "报警", "含义")),
 "oil_specification": (("oil", "lubricant", "viscosity", "grade"), ("润滑", "油品", "粘度")),
 "bearing": (("bearing", "replacement"), ("轴承", "更换")),
 "speed": (("speed", "velocity", "rated speed"), ("速度",)),
}
GENERIC = {"hydraulic", "pump", "maintenance", "check", "what", "which", "does", "when", "how", "required"}

def concept_evidence(query, heading, text, devices, codes):
    q = query.lower(); identifiers = {x.lower() for x in devices | codes}
    matched = []
    for name, (english, chinese) in CONCEPTS.items():
        q_hits = [a for a in english if a in q and a not in identifiers and a not in GENERIC] + [a for a in chinese if a in query]
        # A family needs a relation/attribute, not one generic word.
        if not q_hits and name == "fault_meaning" and any(a in q for a in ("mean", "meaning", "alarm", "fault")): q_hits = ["fault-intent"]
        if not q_hits: continue
        h = heading.lower(); source_hits = [a for a in english if a in h] + [a for a in chinese if a in heading]
        content_hits = [a for a in english if a in text.lower()] + [a for a in chinese if a in text]
        if source_hits or content_hits: matched.append({"family": name, "heading_matches": source_hits, "content_matches": content_hits})
    return {"lexicon_version": LEXICON_VERSION, "requested_families": [x["family"] for x in matched], "matched_families": matched, "coverage": 1.0 if matched else 0.0}

def fingerprint(config):
    payload={"algorithm":ALGORITHM_VERSION,"lexicon":LEXICON_VERSION,"embedding":config["embedding"],"retrieval":config["retrieval"]}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":" )).encode()).hexdigest()

def build_index(config, database: pathlib.Path, provider: EmbeddingProvider, token_counter=None):
    inherited=copy.deepcopy(config); inherited["milestone"]=R2.MILESTONE; inherited["retrieval"].pop("fact_evidence",None)
    result=R2.build_index(inherited,database,provider,token_counter)
    c=sqlite3.connect(database)
    try:
        c.executemany("INSERT INTO index_metadata(key,value) VALUES(?,?)",[("algorithm_version",ALGORITHM_VERSION),("concept_lexicon_version",LEXICON_VERSION),("r2_2_index_fingerprint",fingerprint(config)),("concept_gate_parameters",json.dumps(config["retrieval"],sort_keys=True,separators=(",",":")))])
        if c.execute("PRAGMA integrity_check").fetchone()[0]!="ok": raise ContractError("R2.2 SQLite integrity check failed")
        c.commit()
    finally: c.close()
    return {**result,"milestone":MILESTONE,"algorithm_version":ALGORITHM_VERSION,"r2_2_index_fingerprint":fingerprint(config)}

def query_index(database, query, top_k, provider: EmbeddingProvider, retrieval):
    c=sqlite3.connect(f"file:{database}?mode=ro",uri=True)
    try: meta=dict(c.execute("SELECT key,value FROM index_metadata"))
    finally: c.close()
    if meta.get("algorithm_version")!=ALGORITHM_VERSION: raise ContractError("R2.2 index algorithm version mismatch")
    raw=copy.deepcopy(retrieval); raw.pop("fact_evidence",None); raw["admission"]={"minimum_vector_score":0.0,"minimum_keyword_coverage":0.0,"minimum_margin":0.0}
    response=R2.query_index(database,query,top_k,provider,raw)
    if not response["results"]:
        response["admission"]["reasons"]=list(dict.fromkeys(response["admission"]["reasons"]+["missing_fact_family_evidence"])); return response
    constraints=response["constraints"]; top=response["results"][0]
    evidence=concept_evidence(query,top["heading"],top["text"],set(constraints["devices"]),set(constraints["fault_codes"]))
    base=response["admission"]; reasons=[]
    if evidence["coverage"]<retrieval["fact_evidence"]["minimum_coverage"]: reasons.append("missing_fact_family_evidence")
    for score,key,reason in ((base["vector_score"],"minimum_vector_score","vector_score_below_threshold"),(base["keyword_coverage"],"minimum_keyword_coverage","keyword_coverage_below_threshold"),(base["margin"],"minimum_margin","top1_top2_margin_below_threshold")):
        if score<retrieval["admission"][key]: reasons.append(reason)
    response["admission"]={**base,"passed":not reasons,"reasons":reasons,"fact_evidence":evidence}
    if reasons: response["answerable"]=False; response["results"]=[]; response["citations"]=[]
    return response
