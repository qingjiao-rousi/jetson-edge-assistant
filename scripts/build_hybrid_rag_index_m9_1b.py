#!/usr/bin/env python3
"""Build the M9.1B multi-document local-embedding/hybrid index."""
import argparse, json, pathlib, resource, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rag_hybrid_m9_1b import ContractError, build_index, load_config, provider_from_config, tokenizer_counter

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/rag-hybrid-m9.1b.json")
    parser.add_argument("--database")
    parser.add_argument("--manifest")
    args = parser.parse_args()
    config = load_config(ROOT / args.config)
    provider = provider_from_config(config)
    database = ROOT / (args.database or config["generated_database"])
    started = time.perf_counter()
    result = build_index(config, database, provider, token_counter=tokenizer_counter(config))
    result["database_path"] = str(database.relative_to(ROOT))
    result["index_time_ms"] = (time.perf_counter() - started) * 1000.0
    result["process_peak_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    result["embedding_children_peak_rss_mb"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024.0
    if args.manifest:
        pathlib.Path(args.manifest).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))

if __name__ == "__main__":
    try:
        main()
    except (ContractError, RuntimeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, ensure_ascii=False))
        raise SystemExit(2)
