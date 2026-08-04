#!/usr/bin/env python3
"""Query the M9.1B vector or hybrid index with citation and no-hit gates."""
import argparse, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rag_hybrid_m9_1b import ContractError, load_config, provider_from_config, query_index

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/rag-hybrid-m9.1b.json")
    parser.add_argument("--database")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int)
    args = parser.parse_args()
    config = load_config(ROOT / args.config)
    provider = provider_from_config(config)
    database = ROOT / (args.database or config["generated_database"])
    print(json.dumps(query_index(database, args.query, args.top_k or config["retrieval"]["top_k"], provider, config["retrieval"]), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    try:
        main()
    except (ContractError, RuntimeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, ensure_ascii=False))
        raise SystemExit(2)
