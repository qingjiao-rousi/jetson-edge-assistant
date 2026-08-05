#!/usr/bin/env python3
"""M9.1B-R2.3 calibration-only margin-grid correction over R2.2 retrieval."""
import argparse, copy, hashlib, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_rag_hybrid_m9_1b import QUALITY_GATE, quality_gate_result
from rag_hybrid_m9_1b import EmbeddingSpec, provider_from_config
from rag_hybrid_m9_1b_r2 import sha256_file
from rag_hybrid_m9_1b_r2_1 import load_config
from rag_hybrid_m9_1b_r2_2 import ALGORITHM_VERSION as R22_ALGORITHM, query_index

MILESTONE = "M9.1B-R2.3"
ALGORITHM_VERSION = "concept-fact-family-v1-margin-grid-r2.3"
MARGINS = (0.0001, 0.0002, 0.00025, 0.0003, 0.0005, 0.001, 0.005)


def load_questions(path): return json.loads(path.read_text(encoding="utf-8"))["questions"]


def run_set(database, provider, items, retrieval, details=True):
    answerable = sum(item["expected_chunk_id"] is not None for item in items); no_answer = len(items) - answerable
    hit1 = hit3 = rejected = false_positive = 0; mrr = 0.0; records = []
    for item in items:
        response = query_index(database, item["query"], 3, provider, retrieval)
        returned = [row["chunk_id"] for row in response["results"]]; expected = item["expected_chunk_id"]
        rank = returned.index(expected) + 1 if expected in returned else None
        hit1 += rank == 1; hit3 += rank is not None and rank <= 3; mrr += 1.0 / rank if rank else 0.0
        rejected += expected is None and not response["answerable"]; false_positive += expected is None and response["answerable"]
        if details: records.append({"id": item["id"], "expected_chunk_id": expected, "returned_chunk_ids": returned, "rank": rank, "answerable": response["answerable"], "admission": response["admission"]})
    return {"sample_count": len(items), "answerable_count": answerable, "no_answer_count": no_answer, "recall_at_1": hit1 / max(1, answerable), "recall_at_3": hit3 / max(1, answerable), "mrr": mrr / max(1, answerable), "no_answer_correct_rejection_rate": rejected / max(1, no_answer), "false_positive_count": false_positive, "questions": records}


def candidates(base):
    for vector in (0.4, 0.5, 0.6):
        for fact in (0.25, 0.5, 1.0):
            for margin in MARGINS:
                retrieval = copy.deepcopy(base)
                retrieval["admission"] = {"minimum_vector_score": vector, "minimum_keyword_coverage": 0.1, "minimum_margin": margin}
                retrieval["fact_evidence"] = {"minimum_coverage": fact, "minimum_terms": 1}
                yield retrieval


def algorithm_fingerprint(config, retrieval):
    payload = {"algorithm": ALGORITHM_VERSION, "base_algorithm": R22_ALGORITHM, "embedding": config["embedding"], "retrieval": retrieval, "margins": MARGINS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def calibrate(config, database, dataset):
    provider = provider_from_config(config); items = load_questions(dataset); results = []; passing = []
    for retrieval in candidates(config["retrieval"]):
        metrics = run_set(database, provider, items, retrieval, False); gate = quality_gate_result(metrics)
        candidate = {"retrieval": retrieval, "metrics": metrics, "quality_gate_result": gate}
        results.append(candidate)
        if gate["passed"]: passing.append(candidate)
    artifact = {"schema_version": 1, "milestone": MILESTONE, "phase": "CALIBRATION", "algorithm": ALGORITHM_VERSION, "base_algorithm": R22_ALGORITHM, "embedding_fingerprint": EmbeddingSpec.from_dict(config["embedding"]).fingerprint, "dataset_sha256": sha256_file(dataset), "question_ids": [item["id"] for item in items], "margin_grid": list(MARGINS), "candidate_count": len(results), "candidates": results, "quality_gate_frozen_for_diagnostic": QUALITY_GATE}
    if not passing: return {**artifact, "status": "CALIBRATION_FAILED", "reason": "no_margin_grid_candidate_satisfies_complete_quality_gate"}
    chosen = max(passing, key=lambda item: (item["metrics"]["mrr"], item["metrics"]["recall_at_1"], -item["metrics"]["false_positive_count"], -item["retrieval"]["admission"]["minimum_margin"]))
    return {**artifact, "status": "CALIBRATED", "retrieval": chosen["retrieval"], "calibration_metrics": chosen["metrics"], "quality_gate_result": chosen["quality_gate_result"], "algorithm_fingerprint": algorithm_fingerprint(config, chosen["retrieval"])}


def diagnostic(config, database, dataset, frozen_path):
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if frozen.get("status") != "CALIBRATED" or frozen.get("algorithm") != ALGORITHM_VERSION: raise ValueError("invalid frozen R2.3 calibration")
    metrics = run_set(database, provider_from_config(config), load_questions(dataset), frozen["retrieval"], True); gate = quality_gate_result(metrics)
    return {"schema_version": 1, "milestone": MILESTONE, "phase": "DIAGNOSTIC_DEV", "status": "DONE" if gate["passed"] else "PARTIAL", "algorithm": ALGORITHM_VERSION, "algorithm_fingerprint": frozen["algorithm_fingerprint"], "dataset_sha256": sha256_file(dataset), "retrieval": frozen["retrieval"], "quality_gate": QUALITY_GATE, "quality_gate_result": gate, "quality_metrics": metrics, "holdout_execution": "PROHIBITED"}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--phase", choices=("calibration", "diagnostic"), required=True); parser.add_argument("--database", required=True); parser.add_argument("--dataset", required=True); parser.add_argument("--output", required=True); parser.add_argument("--frozen-calibration")
    args = parser.parse_args(); config = load_config(ROOT / "configs/rag-hybrid-m9.1b-r2.1.json")
    result = calibrate(config, ROOT / args.database, ROOT / args.dataset) if args.phase == "calibration" else diagnostic(config, ROOT / args.database, ROOT / args.dataset, ROOT / args.frozen_calibration) if args.frozen_calibration else (_ for _ in ()).throw(ValueError("diagnostic requires --frozen-calibration"))
    (ROOT / args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"); print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__": main()
