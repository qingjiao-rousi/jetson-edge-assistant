#!/usr/bin/env python3
"""Calibration, diagnostic, and one-time authorized holdout evaluation for R2.1."""
import argparse
import copy
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_rag_hybrid_m9_1b import QUALITY_GATE, quality_gate_result
from rag_hybrid_m9_1b import ContractError, EmbeddingSpec, provider_from_config
from rag_hybrid_m9_1b_r2 import sha256_file
from rag_hybrid_m9_1b_r2_1 import ALGORITHM_VERSION, MILESTONE, load_config, query_index


def questions(path): return json.loads(path.read_text(encoding="utf-8"))["questions"]


def load_private_questions(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("questions")
    if not isinstance(items, list) or not items:
        raise ContractError("private holdout must contain a non-empty questions list")
    ids = [item.get("id") for item in items]
    if any(not isinstance(item, str) or not item for item in ids) or len(set(ids)) != len(ids):
        raise ContractError("private holdout question IDs must be non-empty and unique")
    return items


def write_new_json(path, payload):
    if path.exists():
        raise ContractError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = None
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = pathlib.Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            json.dump(payload, handle, indent=2, ensure_ascii=False); handle.write("\n")
        # Link is exclusive: a concurrent or previous output can never be replaced.
        os.link(temporary, path)
    except FileExistsError as error:
        raise ContractError(f"refusing to overwrite existing output: {path}") from error
    finally:
        if descriptor is not None: os.close(descriptor)
        if temporary and temporary.exists(): temporary.unlink()


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"invalid JSON artifact: {path}") from error


def artifact_ids(artifact):
    if artifact.get("phase") == "CALIBRATION": return artifact.get("question_ids", [])
    if artifact.get("phase") == "DIAGNOSTIC_DEV": return [item.get("id") for item in artifact.get("quality_metrics", {}).get("questions", [])]
    return []


def verify_calibration(config, artifact):
    expected_fingerprint = EmbeddingSpec.from_dict(config["embedding"]).fingerprint
    if artifact.get("status") != "CALIBRATED": raise ContractError("holdout requires CALIBRATED calibration")
    if artifact.get("milestone") != MILESTONE or artifact.get("algorithm") != ALGORITHM_VERSION:
        raise ContractError("calibration milestone or algorithm mismatch")
    if artifact.get("embedding_fingerprint") != expected_fingerprint:
        raise ContractError("calibration embedding fingerprint mismatch")
    if artifact.get("quality_gate_frozen_for_diagnostic") != QUALITY_GATE:
        raise ContractError("calibration quality gate mismatch")
    if artifact.get("retrieval") != config["retrieval"]:
        raise ContractError("calibration retrieval parameters mismatch")
    ids = artifact_ids(artifact)
    if not ids or len(ids) != len(set(ids)): raise ContractError("invalid calibration question IDs")


def verify_diagnostic(config, artifact):
    if artifact.get("milestone") != MILESTONE or artifact.get("phase") != "DIAGNOSTIC_DEV":
        raise ContractError("diagnostic milestone or phase mismatch")
    if artifact.get("quality_gate") != QUALITY_GATE or not artifact.get("quality_gate_result", {}).get("passed"):
        raise ContractError("diagnostic does not satisfy the frozen quality gate")
    ids = artifact_ids(artifact)
    if not ids or len(ids) != len(set(ids)): raise ContractError("invalid diagnostic question IDs")


def authorize_holdout(config, calibration_path, diagnostic_path, holdout_path, output_path):
    if output_path.exists(): raise ContractError(f"refusing to overwrite existing output: {output_path}")
    calibration = read_json(calibration_path); diagnostic_artifact = read_json(diagnostic_path)
    verify_calibration(config, calibration); verify_diagnostic(config, diagnostic_artifact)
    items = load_private_questions(holdout_path)
    holdout_ids = {item["id"] for item in items}; calibration_ids = set(artifact_ids(calibration)); diagnostic_ids = set(artifact_ids(diagnostic_artifact))
    if holdout_ids & calibration_ids or holdout_ids & diagnostic_ids:
        raise ContractError("private holdout IDs overlap calibration or diagnostic")
    authorization = {
        "schema_version": 1, "milestone": MILESTONE, "phase": "HOLDOUT_AUTHORIZATION",
        "execution_state": "AUTHORIZED", "algorithm": ALGORITHM_VERSION,
        "embedding_fingerprint": EmbeddingSpec.from_dict(config["embedding"]).fingerprint,
        "holdout_sha256": sha256_file(holdout_path), "holdout_question_count": len(items),
        "calibration_sha256": sha256_file(calibration_path), "diagnostic_sha256": sha256_file(diagnostic_path),
        "retrieval": calibration["retrieval"], "quality_gate": QUALITY_GATE,
    }
    write_new_json(output_path, authorization)
    return authorization


def consume_authorization(path, authorization):
    if authorization.get("execution_state") != "AUTHORIZED": raise ContractError("authorization has already been consumed")
    consumed = dict(authorization, execution_state="CONSUMED")
    temporary = path.with_name(f".{path.name}.consume.tmp")
    if temporary.exists(): raise ContractError("authorization consume temporary already exists")
    temporary.write_text(json.dumps(consumed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run_holdout(config, database, holdout_path, authorization_path, output_path):
    if output_path.exists(): raise ContractError(f"refusing to overwrite existing output: {output_path}")
    authorization = read_json(authorization_path)
    if authorization.get("execution_state") != "AUTHORIZED": raise ContractError("authorization has already been consumed")
    calibration_like = {"phase": "CALIBRATION", "status": "CALIBRATED", "milestone": authorization.get("milestone"), "algorithm": authorization.get("algorithm"), "embedding_fingerprint": authorization.get("embedding_fingerprint"), "quality_gate_frozen_for_diagnostic": authorization.get("quality_gate"), "retrieval": authorization.get("retrieval"), "question_ids": ["authorization-placeholder"]}
    verify_calibration(config, calibration_like)
    if authorization.get("phase") != "HOLDOUT_AUTHORIZATION": raise ContractError("invalid holdout authorization phase")
    if sha256_file(holdout_path) != authorization.get("holdout_sha256"): raise ContractError("private holdout SHA-256 mismatch")
    items = load_private_questions(holdout_path)
    if len(items) != authorization.get("holdout_question_count"): raise ContractError("private holdout question count mismatch")
    # Consume before evaluation so a failed process cannot be retried with the same authorization.
    consume_authorization(authorization_path, authorization)
    provider = provider_from_config(config); metrics = run_set(database, provider, items, authorization["retrieval"], True); gate = quality_gate_result(metrics)
    result = {"schema_version": 1, "milestone": MILESTONE, "phase": "HOLDOUT", "status": "DONE" if gate["passed"] else "PARTIAL", "algorithm": ALGORITHM_VERSION, "holdout_sha256": authorization["holdout_sha256"], "holdout_question_count": len(items), "authorization_sha256": sha256_file(authorization_path), "retrieval": authorization["retrieval"], "quality_gate": QUALITY_GATE, "quality_gate_result": gate, "quality_metrics": metrics}
    write_new_json(output_path, result)
    return result


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("calibration", "diagnostic", "authorize-holdout", "holdout"), required=True)
    parser.add_argument("--database")
    parser.add_argument("--dataset")
    parser.add_argument("--frozen-calibration")
    parser.add_argument("--diagnostic")
    parser.add_argument("--holdout")
    parser.add_argument("--authorization")
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="configs/rag-hybrid-m9.1b-r2.1.json")
    args = parser.parse_args(); config = load_config(ROOT / args.config); output = pathlib.Path(args.output)
    if args.phase == "calibration":
        if not args.database or not args.dataset: raise ContractError("calibration requires --database and --dataset")
        result = calibrate(config, ROOT / args.database, ROOT / args.dataset)
    elif args.phase == "diagnostic":
        if not args.database or not args.dataset or not args.frozen_calibration: raise ContractError("diagnostic requires --database, --dataset, and --frozen-calibration")
        result = diagnostic(config, ROOT / args.database, ROOT / args.dataset, ROOT / args.frozen_calibration)
    elif args.phase == "authorize-holdout":
        if not args.frozen_calibration or not args.diagnostic or not args.holdout: raise ContractError("authorize-holdout requires --frozen-calibration, --diagnostic, and --holdout")
        result = authorize_holdout(config, ROOT / args.frozen_calibration, ROOT / args.diagnostic, pathlib.Path(args.holdout), output)
    else:
        if not args.database or not args.holdout or not args.authorization: raise ContractError("holdout requires --database, --holdout, and --authorization")
        result = run_holdout(config, ROOT / args.database, pathlib.Path(args.holdout), pathlib.Path(args.authorization), output)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try: main()
    except (ContractError, RuntimeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, ensure_ascii=False)); raise SystemExit(2)
