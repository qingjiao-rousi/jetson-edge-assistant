#!/usr/bin/env python3
"""One-time external holdout authorization for frozen M9.1B-R2.5."""
import argparse, hashlib, json, os, pathlib, sqlite3, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_rag_hybrid_m9_1b import quality_gate_result
from rag_hybrid_m9_1b import ContractError, provider_from_config
from rag_hybrid_m9_1b_r2 import sha256_file
from rag_hybrid_m9_1b_r2_1 import load_config
from rag_hybrid_m9_1b_r2_5 import query_index

FROZEN = json.loads((ROOT / "configs/rag-hybrid-m9.1b-r2.5.json").read_text(encoding="utf-8"))
CONTRACT_KEYS = ("milestone", "algorithm_fingerprint", "embedding_fingerprint", "retrieval", "quality_gate")


def read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"invalid JSON: {path}") from error


def write_new(path, payload):
    if path.exists():
        raise ContractError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = pathlib.Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.link(temporary, path)
    except FileExistsError as error:
        raise ContractError(f"refusing to overwrite existing output: {path}") from error
    finally:
        if temporary.exists():
            temporary.unlink()


def artifact_ids(artifact):
    if artifact.get("phase") == "CALIBRATION":
        return artifact.get("question_ids", [])
    return [row.get("id") for row in artifact.get("quality_metrics", {}).get("questions", [])]


def verify_evidence(calibration, diagnostic):
    if calibration.get("status") != "CALIBRATED" or not calibration.get("quality_gate_result", {}).get("passed"):
        raise ContractError("calibration is not CALIBRATED with a passing quality gate")
    if diagnostic.get("status") != "DONE" or not diagnostic.get("quality_gate_result", {}).get("passed"):
        raise ContractError("diagnostic is not DONE with a passing quality gate")
    for artifact in (calibration, diagnostic):
        if any(artifact.get(key) != FROZEN[key] for key in CONTRACT_KEYS):
            raise ContractError("evidence artifact frozen contract mismatch")


def private_questions(path):
    questions = read(path).get("questions")
    if not isinstance(questions, list) or not questions:
        raise ContractError("private holdout requires questions")
    identifiers = [question.get("id") for question in questions]
    if any(not isinstance(identifier, str) or not identifier for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ContractError("private holdout IDs must be unique")
    return questions


def authorize(calibration_path, diagnostic_path, holdout_path, output):
    calibration, diagnostic = read(calibration_path), read(diagnostic_path)
    verify_evidence(calibration, diagnostic)
    questions = private_questions(holdout_path)
    holdout_ids = {question["id"] for question in questions}
    if holdout_ids & set(artifact_ids(calibration)) or holdout_ids & set(artifact_ids(diagnostic)):
        raise ContractError("holdout IDs overlap calibration or diagnostic")
    authorization = {"schema_version": 1, "phase": "HOLDOUT_AUTHORIZATION", "execution_state": "AUTHORIZED",
                     **{key: FROZEN[key] for key in CONTRACT_KEYS}, "index_contract": FROZEN["index_contract"],
                     "holdout_sha256": sha256_file(holdout_path), "holdout_question_count": len(questions),
                     "calibration_sha256": sha256_file(calibration_path), "diagnostic_sha256": sha256_file(diagnostic_path)}
    write_new(output, authorization)
    return authorization


def verify_index(database):
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        metadata = dict(connection.execute("SELECT key,value FROM index_metadata"))
    except sqlite3.DatabaseError as error:
        raise ContractError(f"invalid R2.5 SQLite index: {database}") from error
    finally:
        if 'connection' in locals():
            connection.close()
    expected = {**FROZEN["index_contract"], "embedding_fingerprint": FROZEN["embedding_fingerprint"]}
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise ContractError("SQLite index frozen contract mismatch")


def metrics(database, provider, questions, retrieval):
    answerable = sum(question["expected_chunk_id"] is not None for question in questions)
    no_answer = len(questions) - answerable
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
        rows.append({"id": question["id"], "expected_chunk_id": expected, "returned_chunk_ids": returned,
                     "rank": rank, "answerable": response["answerable"], "admission": response["admission"]})
    return {"sample_count": len(questions), "answerable_count": answerable, "no_answer_count": no_answer,
            "recall_at_1": recall_1 / answerable, "recall_at_3": recall_3 / answerable,
            "mrr": reciprocal_rank / answerable, "no_answer_correct_rejection_rate": rejected / no_answer,
            "false_positive_count": false_positives, "questions": rows}


def consume(authorization_path, authorization):
    claim = authorization_path.with_name(f".{authorization_path.name}.consuming")
    try:
        os.link(authorization_path, claim)
    except FileExistsError as error:
        raise ContractError("authorization has already been consumed") from error
    try:
        consumed = dict(authorization, execution_state="CONSUMED")
        temporary = authorization_path.with_name(f".{authorization_path.name}.consume.tmp")
        temporary.write_text(json.dumps(consumed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, authorization_path)
    finally:
        if claim.exists():
            claim.unlink()


def holdout(database, holdout_path, authorization_path, output):
    if output.exists():
        raise ContractError(f"refusing to overwrite existing output: {output}")
    authorization = read(authorization_path)
    if authorization.get("execution_state") != "AUTHORIZED":
        raise ContractError("authorization has already been consumed")
    if any(authorization.get(key) != FROZEN[key] for key in CONTRACT_KEYS) or authorization.get("index_contract") != FROZEN["index_contract"]:
        raise ContractError("authorization frozen contract mismatch")
    if sha256_file(holdout_path) != authorization.get("holdout_sha256"):
        raise ContractError("holdout SHA-256 mismatch")
    questions = private_questions(holdout_path)
    if len(questions) != authorization.get("holdout_question_count"):
        raise ContractError("holdout question count mismatch")
    verify_index(database)
    consume(authorization_path, authorization)
    config = load_config(ROOT / "configs/rag-hybrid-m9.1b-r2.1.json")
    evaluation = metrics(database, provider_from_config(config), questions, FROZEN["retrieval"])
    gate = quality_gate_result(evaluation)
    result = {"schema_version": 1, "milestone": FROZEN["milestone"], "phase": "HOLDOUT",
              "status": "DONE" if gate["passed"] else "PARTIAL", "algorithm_fingerprint": FROZEN["algorithm_fingerprint"],
              "embedding_fingerprint": FROZEN["embedding_fingerprint"], "index_contract": FROZEN["index_contract"],
              "holdout_sha256": authorization["holdout_sha256"], "holdout_question_count": len(questions),
              "authorization_sha256": sha256_file(authorization_path), "retrieval": FROZEN["retrieval"],
              "quality_gate": FROZEN["quality_gate"], "quality_gate_result": gate, "quality_metrics": evaluation}
    write_new(output, result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("authorize-holdout", "holdout"), required=True)
    parser.add_argument("--calibration")
    parser.add_argument("--diagnostic")
    parser.add_argument("--database")
    parser.add_argument("--holdout", required=True)
    parser.add_argument("--authorization")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.phase == "authorize-holdout":
        if not args.calibration or not args.diagnostic:
            raise ContractError("authorize-holdout requires --calibration and --diagnostic")
        result = authorize(pathlib.Path(args.calibration), pathlib.Path(args.diagnostic), pathlib.Path(args.holdout), pathlib.Path(args.output))
    else:
        if not args.database or not args.authorization:
            raise ContractError("holdout requires --database and --authorization")
        result = holdout(pathlib.Path(args.database), pathlib.Path(args.holdout), pathlib.Path(args.authorization), pathlib.Path(args.output))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
