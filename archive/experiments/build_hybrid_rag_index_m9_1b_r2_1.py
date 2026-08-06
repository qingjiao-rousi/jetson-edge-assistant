#!/usr/bin/env python3
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rag_hybrid_m9_1b import ContractError, provider_from_config
from rag_hybrid_m9_1b_r2_1 import build_index, load_config

parser = argparse.ArgumentParser()
parser.add_argument("--config", default="configs/rag-hybrid-m9.1b-r2.1.json")
parser.add_argument("--database")
parser.add_argument("--manifest")
args = parser.parse_args()
try:
    config = load_config(ROOT / args.config)
    result = build_index(config, ROOT / (args.database or config["generated_database"]), provider_from_config(config))
    if args.manifest:
        (ROOT / args.manifest).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
except (ContractError, RuntimeError) as error:
    print(json.dumps({"status": "BLOCKED", "error": str(error)}, ensure_ascii=False)); raise SystemExit(2)
