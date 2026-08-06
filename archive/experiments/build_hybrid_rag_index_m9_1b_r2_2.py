#!/usr/bin/env python3
import argparse,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"scripts"))
from rag_hybrid_m9_1b import provider_from_config
from rag_hybrid_m9_1b_r2_1 import load_config
from rag_hybrid_m9_1b_r2_2 import build_index
p=argparse.ArgumentParser(); p.add_argument("--config",default="configs/rag-hybrid-m9.1b-r2.1.json"); p.add_argument("--database",default="generated/rag-m9.1b-r2.2/hybrid.sqlite3"); p.add_argument("--manifest",required=True); a=p.parse_args()
c=load_config(ROOT/a.config); r=build_index(c,ROOT/a.database,provider_from_config(c)); (ROOT/a.manifest).write_text(json.dumps(r,indent=2,ensure_ascii=False)+"\n",encoding="utf-8"); print(json.dumps(r,indent=2,ensure_ascii=False))
