#!/usr/bin/env python3
"""Build the M9.1B-R2 constrained hybrid index."""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rag_hybrid_m9_1b import ContractError, provider_from_config
from rag_hybrid_m9_1b_r2 import build_index, load_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="archive/experiments/configs/rag/rag-hybrid-m9.1b-r2.json")
    parser.add_argument("--database")
    parser.add_argument("--manifest")
    args = parser.parse_args()
    config = load_config(ROOT / args.config)
    result = build_index(config, ROOT / (args.database or config["generated_database"]), provider_from_config(config))
    if args.manifest:
        pathlib.Path(args.manifest).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ContractError, RuntimeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, ensure_ascii=False))
        raise SystemExit(2)
