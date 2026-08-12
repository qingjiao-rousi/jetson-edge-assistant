#!/usr/bin/env python3
"""Read-only comparison of frozen R2.5 and isolated R2.6 on a new dev set."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sqlite3
import sys
from collections import Counter
from typing import Callable

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.retrieval import engine, r2_6_candidate
from app.retrieval.core import ContractError, ProviderUnavailable, provider_from_config
from app.retrieval.embedding import load_config as load_embedding_config


def repo_path(raw: str) -> pathlib.Path:
    candidate = pathlib.PurePosixPath(raw)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != raw:
        raise ContractError("evaluation paths must be repository-relative without '..'")
    resolved = (ROOT / candidate).resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError as error:
        raise ContractError("evaluation path escapes repository root") from error
    return resolved


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_questions(path: pathlib.Path) -> tuple[dict, list[dict]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if set(value) != {"schema_version", "dataset_id", "purpose", "questions"} or value["schema_version"] != 1:
        raise ContractError("invalid R2.6 dev dataset shape")
    questions = value["questions"]
    if not isinstance(questions, list) or not 12 <= len(questions) <= 16:
        raise ContractError("R2.6 dev dataset must contain 12 to 16 questions")
    required = {"id", "query", "expected_chunk_id", "answerable", "category", "rationale"}
    ids = set()
    no_answer = 0
    for question in questions:
        if set(question) != required or not isinstance(question["id"], str) or not question["id"] or question["id"] in ids:
            raise ContractError("R2.6 dev question id is invalid or duplicated")
        ids.add(question["id"])
        if not isinstance(question["query"], str) or not question["query"].strip() or not isinstance(question["category"], str) or not isinstance(question["rationale"], str):
            raise ContractError("R2.6 dev question text fields are invalid")
        if not isinstance(question["answerable"], bool):
            raise ContractError("R2.6 dev answerable must be boolean")
        expected = question["expected_chunk_id"]
        if question["answerable"] != isinstance(expected, str):
            raise ContractError("R2.6 dev answerable and expected_chunk_id disagree")
        if not question["answerable"]:
            if expected is not None:
                raise ContractError("R2.6 no-answer question must use null expected_chunk_id")
            no_answer += 1
    if no_answer < 6:
        raise ContractError("R2.6 dev dataset must contain at least six no-answer questions")
    return value, questions


def load_r2_5_config(path: pathlib.Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "milestone", "algorithm_fingerprint", "embedding_fingerprint", "retrieval", "quality_gate", "index_contract"}
    if set(value) != required or value["schema_version"] != 1 or value["milestone"] != "M9.1B-R2.5":
        raise ContractError("invalid frozen R2.5 evaluation config")
    return value


def validate_database(database: pathlib.Path, index_contract: dict) -> dict:
    if not database.is_file():
        raise ContractError(f"read-only R2.2 SQLite is missing: {database.relative_to(ROOT)}")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        metadata = dict(connection.execute("SELECT key,value FROM index_metadata"))
    finally:
        connection.close()
    for key, expected in index_contract.items():
        if metadata.get(key) != expected:
            raise ContractError(f"R2.2 SQLite index contract mismatch: {key}")
    return metadata


def fingerprint_payload(candidate_config: pathlib.Path) -> dict:
    module = ROOT / "app" / "retrieval" / "r2_6_candidate.py"
    return {
        "candidate_module_sha256": sha256_file(module),
        "candidate_config_sha256": sha256_file(candidate_config),
    }


class CachedQueryProvider:
    """Reuse each dev-query embedding across frozen baseline and candidate runs."""

    def __init__(self, provider):
        self._provider = provider
        self._query_cache: dict[str, list[float]] = {}

    @property
    def spec(self):
        return self._provider.spec

    def embed(self, texts, input_type="document"):
        if input_type != "query" or not texts:
            return self._provider.embed(texts, input_type)
        missing = [text for text in dict.fromkeys(texts) if text not in self._query_cache]
        if missing:
            values = self._provider.embed(missing, "query")
            self._query_cache.update(zip(missing, values))
        return [self._query_cache[text] for text in texts]


def provider_preflight(provider: CachedQueryProvider, question: dict) -> dict:
    """Exercise one local query embedding without exposing its vector or query text."""
    vector = provider.embed([question["query"]], "query")[0]
    return {"query_embeddings": 1, "embedding_dimension": len(vector)}


def error_payload(stage: str, error: Exception, frozen: dict) -> dict:
    return {
        "status": "ERROR",
        "stage": stage,
        "error_type": type(error).__name__,
        "error": str(error),
        "r2_5_algorithm_fingerprint": frozen.get("r2_5_algorithm_fingerprint"),
        "r2_6_candidate_module_sha256": frozen.get("candidate_module_sha256"),
        "r2_6_candidate_config_sha256": frozen.get("candidate_config_sha256"),
    }


def emit_json(payload: dict) -> None:
    """Serialize before writing so expected serialization errors remain structured."""
    try:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    except (TypeError, ValueError) as error:
        fallback = {
            "status": "ERROR", "stage": "serialization", "error_type": type(error).__name__,
            "error": str(error), "r2_5_algorithm_fingerprint": None,
            "r2_6_candidate_module_sha256": None, "r2_6_candidate_config_sha256": None,
        }
        encoded = json.dumps(fallback, ensure_ascii=False, sort_keys=True)
    print(encoded)


def dry_run_payload(question_path: pathlib.Path, database: pathlib.Path, embedding_path: pathlib.Path,
                    r2_5_path: pathlib.Path, r2_6_path: pathlib.Path) -> dict:
    dataset, questions = load_questions(question_path)
    r2_5 = load_r2_5_config(r2_5_path)
    r2_6 = r2_6_candidate.load_config(r2_6_path)
    if r2_5["retrieval"] != r2_6["retrieval"] or r2_5["index_contract"] != r2_6["index_contract"]:
        raise ContractError("R2.5 and R2.6 comparison contracts differ")
    embedding = load_embedding_config(embedding_path)
    if r2_5["embedding_fingerprint"] != r2_6["embedding_fingerprint"]:
        raise ContractError("R2.5 and R2.6 embedding fingerprints differ")
    metadata = validate_database(database, r2_6["index_contract"])
    categories = Counter(question["category"] for question in questions)
    return {
        "status": "DRY_RUN",
        "dataset": {"id": dataset["dataset_id"], "sha256": sha256_file(question_path), "questions": len(questions),
                    "answerable": sum(question["answerable"] for question in questions), "no_answer": sum(not question["answerable"] for question in questions),
                    "categories": dict(sorted(categories.items()))},
        "assets": {"database": str(database.relative_to(ROOT)), "database_sha256": sha256_file(database),
                   "embedding_config": str(embedding_path.relative_to(ROOT)), "embedding_provider": embedding["embedding"]["provider"],
                   "index_metadata": metadata},
        "frozen": {"r2_5_algorithm_fingerprint": r2_5["algorithm_fingerprint"], **fingerprint_payload(r2_6_path)},
        "algorithms": ["M9.1B-R2.5", "M9.1B-R2.6-CANDIDATE"],
        "note": "Dry run validated only read-only input contracts; no embedding model or query function was invoked.",
    }


def mismatch_flags(question: dict, response: dict) -> list[str]:
    returned = response.get("results", [])
    query_devices = set(re.findall(r"\b[A-Z]{1,5}-\d{1,4}\b", question["query"].upper()))
    returned_devices = {item.get("device_id") for item in returned if item.get("device_id")}
    flags = []
    if query_devices and returned_devices and not returned_devices <= query_devices:
        flags.append("device_mismatch")
    query_codes = set(re.findall(r"(?<![A-Z0-9-])[A-Z]\d{2,4}(?![A-Z0-9])", question["query"].upper()))
    if query_codes and returned:
        returned_text = " ".join(f"{item.get('heading', '')} {item.get('text', '')}".upper() for item in returned)
        if not all(code in returned_text for code in query_codes):
            flags.append("fault_code_mismatch")
    return flags


def evaluate(questions: list[dict], database: pathlib.Path, provider, retrieval: dict,
             query_fn: Callable) -> dict:
    results = []
    answerable_total = 0
    recall_1 = recall_3 = reciprocal_rank = 0.0
    no_answer_total = no_answer_rejections = false_positives = mismatch_count = 0
    for question in questions:
        response = query_fn(database, question["query"], retrieval["top_k"], provider, retrieval)
        returned = [item["chunk_id"] for item in response["results"]]
        flags = mismatch_flags(question, response)
        mismatch_count += len(flags)
        detail = {
            "id": question["id"], "expected_chunk_id": question["expected_chunk_id"], "expected_answerable": question["answerable"],
            "returned_chunk_ids": returned, "answerable": response["answerable"],
            "admission_reasons": response["admission"].get("reasons", []), "mismatch_flags": flags,
        }
        results.append(detail)
        if question["answerable"]:
            answerable_total += 1
            expected = question["expected_chunk_id"]
            if returned and returned[0] == expected:
                recall_1 += 1.0
            if expected in returned[:3]:
                recall_3 += 1.0
                reciprocal_rank += 1.0 / (returned.index(expected) + 1)
        else:
            no_answer_total += 1
            if not response["answerable"]:
                no_answer_rejections += 1
            else:
                false_positives += 1
    return {
        "metrics": {
            "answerable_questions": answerable_total,
            "recall_at_1": recall_1 / answerable_total if answerable_total else None,
            "recall_at_3": recall_3 / answerable_total if answerable_total else None,
            "mrr": reciprocal_rank / answerable_total if answerable_total else None,
            "no_answer_questions": no_answer_total,
            "no_answer_correct_rejection_rate": no_answer_rejections / no_answer_total if no_answer_total else None,
            "false_positive_count": false_positives,
            "device_or_fault_mismatch_count": mismatch_count,
        },
        "questions": results,
    }


def comparison_decision(baseline: dict, candidate: dict) -> dict:
    base, proposed = baseline["metrics"], candidate["metrics"]
    checks = {
        "no_answer_rejection_not_lower_than_r2_5": proposed["no_answer_correct_rejection_rate"] >= base["no_answer_correct_rejection_rate"],
        "false_positive_count_not_higher_than_r2_5": proposed["false_positive_count"] <= base["false_positive_count"],
        "recall_at_3_at_least_0_875": proposed["recall_at_3"] >= 0.875,
        "no_device_or_fault_mismatch": proposed["device_or_fault_mismatch_count"] == 0,
    }
    return {"eligible_for_new_holdout": all(checks.values()), "checks": checks,
            "failure_outcome": "REJECTED/UNVALIDATED; stop RAG algorithm development"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", default="tests/fixtures/rag-m9.1b-r2.6-dev/questions.json")
    parser.add_argument("--database", default="generated/rag-m9.1b-r2.2/hybrid.sqlite3")
    parser.add_argument("--embedding-config", default="configs/embedding.json")
    parser.add_argument("--r2-5-config", default="configs/manual-retrieval.json")
    parser.add_argument("--r2-6-config", default="configs/manual-retrieval-r2.6-candidate.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--provider-preflight", action="store_true")
    args = parser.parse_args(argv)
    stage = "input_contract"
    frozen = {
        "r2_5_algorithm_fingerprint": None,
        "candidate_module_sha256": None,
        "candidate_config_sha256": None,
    }
    try:
        question_path, database, embedding_path, r2_5_path, r2_6_path = (
            repo_path(args.questions), repo_path(args.database), repo_path(args.embedding_config),
            repo_path(args.r2_5_config), repo_path(args.r2_6_config),
        )
        frozen.update(fingerprint_payload(r2_6_path))
        dry = dry_run_payload(question_path, database, embedding_path, r2_5_path, r2_6_path)
        r2_5 = load_r2_5_config(r2_5_path)
        r2_6 = r2_6_candidate.load_config(r2_6_path)
        frozen["r2_5_algorithm_fingerprint"] = r2_5["algorithm_fingerprint"]
        if args.dry_run:
            stage = "serialization"
            emit_json(dry)
            return 0
        questions = load_questions(question_path)[1]
        stage = "provider_preflight"
        provider = CachedQueryProvider(provider_from_config(load_embedding_config(embedding_path)))
        if args.provider_preflight:
            stage = "serialization"
            emit_json({**dry, "status": "PROVIDER_PREFLIGHT_OK", "provider_preflight": provider_preflight(provider, questions[0])})
            return 0
        stage = "baseline_r2_5"
        baseline = evaluate(questions, database, provider, r2_5["retrieval"], engine.query_index)
        stage = "candidate_r2_6"
        candidate = evaluate(questions, database, provider, r2_6["retrieval"], r2_6_candidate.query_index)
        stage = "serialization"
        emit_json({**dry, "status": "EVALUATED_ONCE", "baseline_r2_5": baseline,
                   "candidate_r2_6": candidate, "decision": comparison_decision(baseline, candidate)})
        return 0
    except (ProviderUnavailable, ContractError, OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as error:
        emit_json(error_payload(stage, error, frozen))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
