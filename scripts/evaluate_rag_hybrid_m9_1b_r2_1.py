#!/usr/bin/env python3
"""Calibration and diagnostic for R2.1; holdout is intentionally unsupported."""
import argparse
import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_rag_hybrid_m9_1b import QUALITY_GATE, quality_gate_result
from rag_hybrid_m9_1b import ContractError, EmbeddingSpec, provider_from_config
from rag_hybrid_m9_1b_r2 import sha256_file
from rag_hybrid_m9_1b_r2_1 import MILESTONE, load_config, query_index


def questions(path): return json.loads(path.read_text(encoding="utf-8"))["questions"]


def run_set(database, provider, items, retrieval, details=True):
    answerable = sum(item["expected_chunk_id"] is not None for item in items); rejected = false_positive = hit1 = hit3 = 0; mrr = 0.0; output = []
    for item in items:
        response = query_index(database, item["query"], 3, provider, retrieval)
        returned = [row["chunk_id"] for row in response["results"]]; expected = item["expected_chunk_id"]
        rank = returned.index(expected) + 1 if expected in returned else None
        hit1 += rank == 1; hit3 += rank is not None and rank <= 3; mrr += 1.0 / rank if rank else 0.0
        rejected += expected is None and not response["answerable"]; false_positive += expected is None and response["answerable"]
        if details: output.append({"id": item["id"], "expected_chunk_id": expected, "returned_chunk_ids": returned, "answerable": response["answerable"], "rank": rank, "admission": response["admission"]})
    no_answer = len(items) - answerable
    return {"sample_count": len(items), "answerable_count": answerable, "no_answer_count": no_answer, "recall_at_1": hit1 / max(1, answerable), "recall_at_3": hit3 / max(1, answerable), "mrr": mrr / max(1, answerable), "no_answer_correct_rejection_rate": rejected / max(1, no_answer), "false_positive_count": false_positive, "questions": output}


def candidates(base):
    for vector in (0.4, 0.5, 0.6):
        for coverage in (0.1, 0.25, 0.4):
            for margin in (0.0005, 0.001, 0.005):
                for fact in (0.1, 0.25, 0.4):
                    value = copy.deepcopy(base)
                    value["admission"] = {"minimum_vector_score": vector, "minimum_keyword_coverage": coverage, "minimum_margin": margin}
                    value["fact_evidence"] = {"minimum_coverage": fact, "minimum_terms": 1}
                    yield value


def calibrate(config, database, dataset):
    provider = provider_from_config(config); items = questions(dataset); passing = []
    for retrieval in candidates(config["retrieval"]):
        metrics = run_set(database, provider, items, retrieval, False); gate = quality_gate_result(metrics)
        if gate["passed"]: passing.append((metrics["mrr"], metrics["recall_at_1"], -metrics["false_positive_count"], retrieval, metrics, gate))
    result = {"schema_version": 1, "milestone": MILESTONE, "phase": "CALIBRATION", "algorithm": "fact-evidence-v1", "embedding_fingerprint": EmbeddingSpec.from_dict(config["embedding"]).fingerprint, "dataset_path": str(dataset.relative_to(ROOT)), "dataset_sha256": sha256_file(dataset), "question_ids": [item["id"] for item in items], "candidate_count": 81, "quality_gate_frozen_for_diagnostic": QUALITY_GATE}
    if not passing: return {**result, "status": "CALIBRATION_FAILED", "reason": "no_nonzero_gate_candidate_satisfies_complete_quality_gate"}
    chosen = max(passing, key=lambda item: item[:3]); return {**result, "status": "CALIBRATED", "retrieval": chosen[3], "calibration_metrics": chosen[4], "quality_gate_result": chosen[5]}


def diagnostic(config, database, dataset, frozen):
    artifact = json.loads(frozen.read_text(encoding="utf-8"))
    if artifact.get("status") != "CALIBRATED": raise ContractError("CALIBRATION_FAILED cannot authorize diagnostic")
    items = questions(dataset); metrics = run_set(database, provider_from_config(config), items, artifact["retrieval"], True); gate = quality_gate_result(metrics)
    return {"schema_version": 1, "milestone": MILESTONE, "phase": "DIAGNOSTIC_DEV", "status": "DONE" if gate["passed"] else "PARTIAL", "dataset_path": str(dataset.relative_to(ROOT)), "dataset_sha256": sha256_file(dataset), "quality_gate": QUALITY_GATE, "quality_gate_result": gate, "quality_metrics": metrics, "holdout_execution": "PROHIBITED"}


parser = argparse.ArgumentParser(); parser.add_argument("--phase", choices=("calibration", "diagnostic"), required=True); parser.add_argument("--database", required=True); parser.add_argument("--dataset", required=True); parser.add_argument("--frozen-calibration"); parser.add_argument("--output", required=True); parser.add_argument("--config", default="configs/rag-hybrid-m9.1b-r2.1.json")
args = parser.parse_args()
try:
    config = load_config(ROOT / args.config); database = ROOT / args.database; dataset = ROOT / args.dataset
    result = calibrate(config, database, dataset) if args.phase == "calibration" else diagnostic(config, database, dataset, ROOT / args.frozen_calibration) if args.frozen_calibration else (_ for _ in ()).throw(ContractError("diagnostic requires --frozen-calibration"))
    (ROOT / args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"); print(json.dumps(result, indent=2, ensure_ascii=False))
except (ContractError, RuntimeError) as error:
    print(json.dumps({"status": "BLOCKED", "error": str(error)}, ensure_ascii=False)); raise SystemExit(2)
