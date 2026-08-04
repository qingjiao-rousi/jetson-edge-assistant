#!/usr/bin/env python3
"""Calibrate or independently evaluate M9.1B retrieval without network access."""

import argparse
import json
import pathlib
import resource
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rag_hybrid_m9_1b import (  # noqa: E402
    ContractError, EmbeddingSpec, ProviderUnavailable, load_config,
    provider_from_config, query_index, sha256_file,
)

# Frozen before the final evaluation is run. Eight answerable and four no-answer
# cases make these gates equivalent to at least 6/8, 7/8, and 3/4 respectively.
QUALITY_GATE = {
    "mode": "hybrid",
    "minimum_recall_at_1": 0.75,
    "minimum_recall_at_3": 0.875,
    "minimum_mrr": 0.80,
    "minimum_no_answer_correct_rejection_rate": 0.75,
    "maximum_false_positive_count": 1,
}


def asset_audit(config):
    embedding = config["embedding"]
    artifact = ROOT / embedding["model_path"]
    binary = ROOT / embedding["binary_path"] if embedding.get("binary_path") else None
    return {
        "provider": embedding["provider"], "binary_path": embedding.get("binary_path"),
        "binary_exists": binary.is_file() if binary else None,
        "model_id": embedding.get("model_id"), "repository": embedding.get("repository"),
        "revision": embedding.get("revision"), "license": embedding.get("license"),
        "quantization": embedding.get("quantization"), "pooling": embedding.get("pooling"),
        "model_path": embedding["model_path"], "artifact_path": embedding["artifact_path"],
        "expected_size_bytes": embedding.get("model_size_bytes"),
        "actual_size_bytes": artifact.stat().st_size if artifact.is_file() else None,
        "expected_sha256": embedding["model_sha256"],
        "actual_sha256": sha256_file(artifact) if artifact.is_file() else None,
        "xet_hash": embedding.get("xet_hash"), "artifact_exists": artifact.is_file(),
        "dimension": embedding["dimension"], "dtype": embedding["dtype"],
        "normalization": embedding["normalization"], "batch_size": embedding["batch_size"],
        "query_template": embedding.get("query_template"),
        "document_template": embedding.get("document_template"), "network_allowed": False,
    }


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))]


def run_set(database, provider, questions, retrieval, include_details=True):
    answerable_count = sum(item["expected_chunk_id"] is not None for item in questions)
    no_answer_count = len(questions) - answerable_count
    recall_1 = recall_3 = 0
    reciprocal_rank = 0.0
    correct_rejections = false_positives = 0
    latencies = []
    details = []
    for item in questions:
        started = time.perf_counter()
        response = query_index(database, item["query"], 3, provider, retrieval)
        latencies.append((time.perf_counter() - started) * 1000.0)
        returned = [row["chunk_id"] for row in response["results"]]
        expected = item["expected_chunk_id"]
        rank = returned.index(expected) + 1 if expected in returned else None
        if rank == 1:
            recall_1 += 1
        if rank is not None and rank <= 3:
            recall_3 += 1
            reciprocal_rank += 1.0 / rank
        if expected is None and not response["answerable"]:
            correct_rejections += 1
        if expected is None and response["answerable"]:
            false_positives += 1
        if include_details:
            details.append({
                "id": item["id"], "query": item["query"],
                "expected_chunk_id": expected, "answerable": response["answerable"],
                "returned_chunk_ids": returned, "rank": rank,
                "top_candidate_score": response["top_candidate_score"],
            })
    return {
        "sample_count": len(questions), "answerable_count": answerable_count,
        "no_answer_count": no_answer_count,
        "recall_at_1": recall_1 / max(1, answerable_count),
        "recall_at_3": recall_3 / max(1, answerable_count),
        "mrr": reciprocal_rank / max(1, answerable_count),
        "no_answer_correct_rejection_rate": correct_rejections / max(1, no_answer_count),
        "false_positive_count": false_positives,
        "query_latency_ms": {
            "mean": statistics.fmean(latencies), "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
        },
        "questions": details,
    }


def calibrate(database, provider, questions, mode):
    vector_weights = [0.0] if mode == "keyword" else [1.0] if mode == "vector" else [0.25, 0.5, 0.75]
    thresholds = [round(value / 20.0, 2) for value in range(2, 19)]
    candidates = []
    for vector_weight in vector_weights:
        for threshold in thresholds:
            retrieval = {
                "kind": mode, "vector_weight": vector_weight,
                "keyword_weight": 1.0 - vector_weight,
                "min_final_score": threshold, "top_k": 3,
            }
            metrics = run_set(database, provider, questions, retrieval, include_details=False)
            objective = metrics["recall_at_3"] + metrics["no_answer_correct_rejection_rate"]
            candidates.append((objective, metrics["recall_at_1"], -metrics["false_positive_count"], threshold, retrieval, metrics))
    selected = max(candidates, key=lambda item: item[:4])
    return {
        "retrieval": selected[4], "calibration_metrics": selected[5],
        "objective": selected[0], "candidate_count": len(candidates),
    }


def quality_gate_result(metrics):
    checks = {
        "recall_at_1": metrics["recall_at_1"] >= QUALITY_GATE["minimum_recall_at_1"],
        "recall_at_3": metrics["recall_at_3"] >= QUALITY_GATE["minimum_recall_at_3"],
        "mrr": metrics["mrr"] >= QUALITY_GATE["minimum_mrr"],
        "no_answer_correct_rejection_rate": metrics["no_answer_correct_rejection_rate"] >= QUALITY_GATE["minimum_no_answer_correct_rejection_rate"],
        "false_positive_count": metrics["false_positive_count"] <= QUALITY_GATE["maximum_false_positive_count"],
    }
    return {"passed": all(checks.values()), "checks": checks}


def load_questions(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["questions"]


def run_calibration(config, database, dataset_path):
    questions = load_questions(dataset_path)
    provider = provider_from_config(config)
    calibrations = {mode: calibrate(database, provider, questions, mode) for mode in ("keyword", "vector", "hybrid")}
    return {
        "schema_version": 1, "milestone": "M9.1B", "phase": "CALIBRATION",
        "embedding_fingerprint": EmbeddingSpec.from_dict(config["embedding"]).fingerprint,
        "calibration_set_path": str(dataset_path.relative_to(ROOT)),
        "calibration_set_sha256": sha256_file(dataset_path),
        "calibration_question_ids": [item["id"] for item in questions],
        "sample_count": len(questions), "calibration": calibrations,
        "quality_gate_frozen_for_final": QUALITY_GATE,
    }


def run_evaluation(config, database, dataset_path, frozen_path, index_manifest_path):
    questions = load_questions(dataset_path)
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    fingerprint = EmbeddingSpec.from_dict(config["embedding"]).fingerprint
    if frozen.get("phase") != "CALIBRATION" or frozen.get("embedding_fingerprint") != fingerprint:
        raise ContractError("frozen calibration artifact does not match the embedding config")
    overlap = set(frozen["calibration_question_ids"]) & {item["id"] for item in questions}
    if overlap:
        raise ContractError("calibration and evaluation question IDs overlap")
    if frozen.get("quality_gate_frozen_for_final") != QUALITY_GATE:
        raise ContractError("quality gate differs from the pre-evaluation frozen gate")
    provider = provider_from_config(config)
    final = {}
    for mode in ("keyword", "vector", "hybrid"):
        if hasattr(provider, "clear_cache"):
            provider.clear_cache()
        final[mode] = run_set(database, provider, questions, frozen["calibration"][mode]["retrieval"])
    gate_result = quality_gate_result(final["hybrid"])
    index_manifest = json.loads(index_manifest_path.read_text(encoding="utf-8"))
    return {
        "schema_version": 3, "milestone": "M9.1B",
        "status": "DONE" if gate_result["passed"] else "PARTIAL",
        "scope": "Three synthetic manuals; frozen calibration; independent final evaluation; no answer generation",
        "embedding_asset": asset_audit(config),
        "dataset": {
            "calibration_count": frozen["sample_count"],
            "final_evaluation_count": len(questions), "sets_disjoint": True,
            "calibration_set_sha256": frozen["calibration_set_sha256"],
            "evaluation_set_sha256": sha256_file(dataset_path),
        },
        "calibration_artifact": str(frozen_path.relative_to(ROOT)),
        "calibration_artifact_sha256": sha256_file(frozen_path),
        "calibration": frozen["calibration"], "quality_gate": QUALITY_GATE,
        "quality_gate_result": gate_result, "quality_metrics": final,
        "resource_metrics": {
            "index_time_ms": index_manifest["index_time_ms"],
            "index_size_bytes": index_manifest["database_size_bytes"],
            "index_process_peak_rss_mb": index_manifest["process_peak_rss_mb"],
            "index_embedding_children_peak_rss_mb": index_manifest["embedding_children_peak_rss_mb"],
            "evaluation_process_peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0,
            "evaluation_embedding_children_peak_rss_mb": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024.0,
        },
        "limitations": [
            "Metrics cover 12 fixed questions over three synthetic manuals and do not establish general retrieval quality.",
            "CLI process startup is included in vector and hybrid query latency; this is not a persistent embedding service benchmark.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("calibration", "evaluation"), required=True)
    parser.add_argument("--config", default="configs/rag-hybrid-m9.1b.json")
    parser.add_argument("--database")
    parser.add_argument("--dataset")
    parser.add_argument("--frozen-calibration")
    parser.add_argument("--index-manifest")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = load_config(ROOT / args.config)
    database = ROOT / (args.database or config["generated_database"])
    if args.phase == "calibration":
        dataset = ROOT / (args.dataset or "tests/fixtures/rag-m9.1b/calibration-set.json")
        result = run_calibration(config, database, dataset)
    else:
        if not args.frozen_calibration or not args.index_manifest:
            raise ContractError("evaluation requires --frozen-calibration and --index-manifest")
        dataset = ROOT / (args.dataset or "tests/fixtures/rag-m9.1b/evaluation-set.json")
        result = run_evaluation(
            config, database, dataset, ROOT / args.frozen_calibration,
            ROOT / args.index_manifest,
        )
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ContractError, ProviderUnavailable, RuntimeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, ensure_ascii=False))
        raise SystemExit(2)
