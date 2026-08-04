#!/usr/bin/env python3
"""R2 calibration enforces the complete frozen M9.1B quality gate."""
import argparse
import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_rag_hybrid_m9_1b import QUALITY_GATE, quality_gate_result
from rag_hybrid_m9_1b import ContractError, EmbeddingSpec, provider_from_config
from rag_hybrid_m9_1b_r2 import MILESTONE, load_config, query_index, sha256_file


def load_questions(path):
    return json.loads(path.read_text(encoding="utf-8"))["questions"]


def _run(database, provider, questions, retrieval, include_details):
    answerable_count = sum(item["expected_chunk_id"] is not None for item in questions)
    no_answer_count = len(questions) - answerable_count
    recall_1 = recall_3 = correct_rejections = false_positives = 0
    reciprocal_rank = 0.0; details = []
    for item in questions:
        response = query_index(database, item["query"], 3, provider, retrieval)
        returned = [row["chunk_id"] for row in response["results"]]
        expected = item["expected_chunk_id"]
        rank = returned.index(expected) + 1 if expected in returned else None
        recall_1 += rank == 1; recall_3 += rank is not None and rank <= 3
        reciprocal_rank += 1.0 / rank if rank else 0.0
        correct_rejections += expected is None and not response["answerable"]
        false_positives += expected is None and response["answerable"]
        if include_details:
            details.append({"id": item["id"], "query": item["query"], "expected_chunk_id": expected, "answerable": response["answerable"], "returned_chunk_ids": returned, "rank": rank, "admission": response["admission"]})
    return {"sample_count": len(questions), "answerable_count": answerable_count, "no_answer_count": no_answer_count, "recall_at_1": recall_1 / max(1, answerable_count), "recall_at_3": recall_3 / max(1, answerable_count), "mrr": reciprocal_rank / max(1, answerable_count), "no_answer_correct_rejection_rate": correct_rejections / max(1, no_answer_count), "false_positive_count": false_positives, "questions": details}


def calibration_candidates(base):
    for vector in (0.0, 0.2, 0.4, 0.6):
        for coverage in (0.0, 0.1, 0.25, 0.5, 0.75):
            for margin in (0.0, 0.002, 0.005, 0.01):
                candidate = copy.deepcopy(base)
                candidate["admission"] = {"minimum_vector_score": vector, "minimum_keyword_coverage": coverage, "minimum_margin": margin}
                yield candidate


def run_calibration(config, database, dataset_path):
    questions = load_questions(dataset_path); provider = provider_from_config(config)
    candidates = []
    for retrieval in calibration_candidates(config["retrieval"]):
        metrics = _run(database, provider, questions, retrieval, include_details=False)
        gate = quality_gate_result(metrics)
        if gate["passed"]:
            candidates.append((metrics["mrr"], metrics["recall_at_1"], -metrics["false_positive_count"], retrieval, metrics, gate))
    result = {"schema_version": 1, "milestone": MILESTONE, "phase": "CALIBRATION", "embedding_fingerprint": EmbeddingSpec.from_dict(config["embedding"]).fingerprint, "calibration_set_path": str(dataset_path.relative_to(ROOT)), "calibration_set_sha256": sha256_file(dataset_path), "calibration_question_ids": [item["id"] for item in questions], "sample_count": len(questions), "quality_gate_frozen_for_holdout": QUALITY_GATE, "candidate_count": 80}
    if not candidates:
        result.update({"status": "CALIBRATION_FAILED", "reason": "no_candidate_satisfies_complete_quality_gate"})
        return result
    selected = max(candidates, key=lambda item: item[:3])
    result.update({"status": "CALIBRATED", "retrieval": selected[3], "calibration_metrics": selected[4], "quality_gate_result": selected[5]})
    return result


def run_holdout(config, database, dataset_path, frozen_path):
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if frozen.get("status") != "CALIBRATED":
        raise ContractError("CALIBRATION_FAILED artifacts cannot authorize a holdout run")
    questions = load_questions(dataset_path)
    if set(frozen["calibration_question_ids"]) & {item["id"] for item in questions}:
        raise ContractError("calibration and holdout IDs overlap")
    if frozen.get("quality_gate_frozen_for_holdout") != QUALITY_GATE:
        raise ContractError("quality gate changed after calibration")
    metrics = _run(database, provider_from_config(config), questions, frozen["retrieval"], True)
    return {"schema_version": 1, "milestone": MILESTONE, "phase": "HOLDOUT", "status": "DONE" if quality_gate_result(metrics)["passed"] else "PARTIAL", "holdout_set_sha256": sha256_file(dataset_path), "quality_gate": QUALITY_GATE, "quality_gate_result": quality_gate_result(metrics), "quality_metrics": metrics}


def run_diagnostic(config, database, dataset_path, frozen_path):
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if frozen.get("status") != "CALIBRATED":
        raise ContractError("CALIBRATION_FAILED artifacts cannot authorize diagnostic evaluation")
    metrics = _run(database, provider_from_config(config), load_questions(dataset_path), frozen["retrieval"], True)
    return {"schema_version": 1, "milestone": MILESTONE, "phase": "DIAGNOSTIC_DEV", "status": "DIAGNOSTIC_ONLY", "dataset_path": str(dataset_path.relative_to(ROOT)), "dataset_sha256": sha256_file(dataset_path), "quality_gate": QUALITY_GATE, "quality_gate_result": quality_gate_result(metrics), "quality_metrics": metrics, "prohibition": "This inspected R1 evaluation set is diagnostic/dev only and is not an independent final result."}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--phase", choices=("calibration", "diagnostic", "holdout"), required=True); parser.add_argument("--config", default="configs/rag-hybrid-m9.1b-r2.json"); parser.add_argument("--database", required=True); parser.add_argument("--dataset", required=True); parser.add_argument("--frozen-calibration"); parser.add_argument("--output", required=True)
    args = parser.parse_args(); config = load_config(ROOT / args.config); database = ROOT / args.database; dataset = ROOT / args.dataset
    if args.phase == "calibration": result = run_calibration(config, database, dataset)
    elif not args.frozen_calibration: raise ContractError(f"{args.phase} requires --frozen-calibration")
    elif args.phase == "diagnostic": result = run_diagnostic(config, database, dataset, ROOT / args.frozen_calibration)
    else: result = run_holdout(config, database, dataset, ROOT / args.frozen_calibration)
    (ROOT / args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try: main()
    except (ContractError, RuntimeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, ensure_ascii=False)); raise SystemExit(2)
