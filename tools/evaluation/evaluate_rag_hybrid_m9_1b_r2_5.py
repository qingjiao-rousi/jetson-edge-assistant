#!/usr/bin/env python3
"""Calibration and diagnostic evaluator for M9.1B-R2.5."""
import argparse, copy, hashlib, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evaluate_rag_hybrid_m9_1b import QUALITY_GATE, quality_gate_result
from app.retrieval.core import EmbeddingSpec, provider_from_config
from app.retrieval.retrieval import sha256_file
from app.retrieval.embedding import load_config
from app.retrieval.engine import ALGORITHM_VERSION, LEXICON_VERSION, MILESTONE, query_index

VECTORS = (.4, .5, .6)
FACT_COVERAGES = (.25, .5, 1.0)
MARGINS = (.0001, .0002, .0003, .0005, .001)


def path(value: str) -> pathlib.Path:
    candidate = pathlib.Path(value)
    return candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()


def evaluate(database, questions, retrieval, provider, details):
    answerable_count = sum(q["expected_chunk_id"] is not None for q in questions)
    no_answer_count = len(questions) - answerable_count
    recall_1 = recall_3 = rejected = false_positives = 0
    reciprocal_rank = 0.0
    rows = []
    for question in questions:
        response = query_index(database, question["query"], 3, provider, retrieval)
        returned = [item["chunk_id"] for item in response["results"]]
        expected = question["expected_chunk_id"]
        rank = returned.index(expected) + 1 if expected in returned else None
        recall_1 += rank == 1
        recall_3 += rank is not None and rank <= 3
        reciprocal_rank += 1 / rank if rank else 0
        rejected += expected is None and not response["answerable"]
        false_positives += expected is None and response["answerable"]
        if details:
            rows.append({"id": question["id"], "expected_chunk_id": expected,
                         "returned_chunk_ids": returned, "rank": rank,
                         "answerable": response["answerable"], "admission": response["admission"]})
    return {"sample_count": len(questions), "answerable_count": answerable_count,
            "no_answer_count": no_answer_count, "recall_at_1": recall_1 / answerable_count,
            "recall_at_3": recall_3 / answerable_count, "mrr": reciprocal_rank / answerable_count,
            "no_answer_correct_rejection_rate": rejected / no_answer_count,
            "false_positive_count": false_positives, "questions": rows}


def candidates(config):
    for vector in VECTORS:
        for fact_coverage in FACT_COVERAGES:
            for margin in MARGINS:
                retrieval = copy.deepcopy(config["retrieval"])
                retrieval["admission"] = {"minimum_vector_score": vector,
                                          "minimum_keyword_coverage": .1,
                                          "minimum_margin": margin}
                retrieval["fact_evidence"] = {"minimum_coverage": fact_coverage,
                                               "minimum_terms": 1}
                yield retrieval


def algorithm_fingerprint(retrieval):
    payload = {"algorithm": ALGORITHM_VERSION, "lexicon": LEXICON_VERSION, "retrieval": retrieval}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def calibration(config, database, dataset):
    questions = json.loads(dataset.read_text(encoding="utf-8"))["questions"]
    provider = provider_from_config(config)
    evaluated = []
    for retrieval in candidates(config):
        metrics = evaluate(database, questions, retrieval, provider, True)
        gate = quality_gate_result(metrics)
        evaluated.append({"retrieval": retrieval, "metrics": metrics, "quality_gate_result": gate})
    passed = [candidate for candidate in evaluated if candidate["quality_gate_result"]["passed"]]
    result = {"schema_version": 1, "milestone": MILESTONE, "phase": "CALIBRATION",
              "algorithm": ALGORITHM_VERSION, "lexicon_version": LEXICON_VERSION,
              "embedding_fingerprint": EmbeddingSpec.from_dict(config["embedding"]).fingerprint,
              "dataset_sha256": sha256_file(dataset), "question_ids": [q["id"] for q in questions],
              "candidate_count": len(evaluated), "candidates": evaluated,
              "quality_gate": QUALITY_GATE}
    if not passed:
        return {**result, "status": "CALIBRATION_FAILED"}
    selected = max(passed, key=lambda item: (item["metrics"]["mrr"], item["metrics"]["recall_at_1"],
                                               -item["retrieval"]["admission"]["minimum_margin"]))
    return {**result, "status": "CALIBRATED", "retrieval": selected["retrieval"],
            "calibration_metrics": selected["metrics"], "quality_gate_result": selected["quality_gate_result"],
            "algorithm_fingerprint": algorithm_fingerprint(selected["retrieval"])}


def diagnostic(config, database, dataset, frozen):
    calibration_result = json.loads(frozen.read_text(encoding="utf-8"))
    if calibration_result.get("status") != "CALIBRATED" or calibration_result.get("milestone") != MILESTONE:
        raise ValueError("diagnostic requires a calibrated M9.1B-R2.5 artifact")
    if calibration_result.get("embedding_fingerprint") != EmbeddingSpec.from_dict(config["embedding"]).fingerprint:
        raise ValueError("calibration embedding fingerprint mismatch")
    retrieval = calibration_result["retrieval"]
    if calibration_result.get("algorithm_fingerprint") != algorithm_fingerprint(retrieval):
        raise ValueError("calibration algorithm fingerprint mismatch")
    questions = json.loads(dataset.read_text(encoding="utf-8"))["questions"]
    metrics = evaluate(database, questions, retrieval, provider_from_config(config), True)
    gate = quality_gate_result(metrics)
    return {"schema_version": 1, "milestone": MILESTONE, "phase": "DIAGNOSTIC_DEV",
            "status": "DONE" if gate["passed"] else "PARTIAL", "algorithm": ALGORITHM_VERSION,
            "lexicon_version": LEXICON_VERSION, "algorithm_fingerprint": algorithm_fingerprint(retrieval),
            "embedding_fingerprint": EmbeddingSpec.from_dict(config["embedding"]).fingerprint,
            "dataset_sha256": sha256_file(dataset), "question_ids": [q["id"] for q in questions],
            "retrieval": retrieval, "quality_gate": QUALITY_GATE, "quality_gate_result": gate,
            "quality_metrics": metrics, "holdout_execution": "PROHIBITED"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("calibration", "diagnostic"), required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--frozen-calibration")
    args = parser.parse_args()
    if args.phase == "diagnostic" and not args.frozen_calibration:
        parser.error("--frozen-calibration is required for diagnostic")
    config = load_config(ROOT / "configs/embedding.json")
    database, dataset, output = path(args.database), path(args.dataset), path(args.output)
    result = calibration(config, database, dataset) if args.phase == "calibration" else diagnostic(config, database, dataset, path(args.frozen_calibration))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"milestone": result["milestone"], "phase": result["phase"], "status": result["status"],
                      "quality_gate_result": result.get("quality_gate_result")}, indent=2))


if __name__ == "__main__":
    main()
