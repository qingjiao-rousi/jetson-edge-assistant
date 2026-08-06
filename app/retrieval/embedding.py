#!/usr/bin/env python3
"""M9.1B-R2.1 fact-evidence admission over the frozen R2 ranker."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import re
import sqlite3

from . import retrieval as R2
from .core import ContractError, EmbeddingProvider, EmbeddingSpec

ROOT = R2.ROOT
MILESTONE = "M9.1B-R2.1"
ALGORITHM_VERSION = "fact-evidence-v1"
FACT_STOP_WORDS = R2.STOP_WORDS | frozenset({
    "alarm", "button", "code", "condition", "does", "fault", "indicate", "mean",
    "means", "report", "reports", "required", "sequence", "specify", "warning", "which",
})


def load_config(path: pathlib.Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "milestone", "sources", "tokenizer", "embedding", "retrieval", "generated_database"}
    if set(value) != required or value["schema_version"] != 1 or value["milestone"] != MILESTONE:
        raise ContractError("invalid M9.1B-R2.1 config")
    EmbeddingSpec.from_dict(value["embedding"])
    # R2 validates the inherited retrieval/index contract. R2.1 adds fact evidence.
    inherited = dict(value, milestone=R2.MILESTONE)
    R2.load_config_from_value(inherited) if hasattr(R2, "load_config_from_value") else _validate_inherited(inherited)
    fact = value["retrieval"].get("fact_evidence")
    if set(value["retrieval"]) != {"kind", "top_k", "rrf_k", "admission", "fact_evidence"} or set(fact or {}) != {"minimum_coverage", "minimum_terms"}:
        raise ContractError("invalid R2.1 fact-evidence contract")
    if not 0.0 <= fact["minimum_coverage"] <= 1.0 or not isinstance(fact["minimum_terms"], int) or fact["minimum_terms"] < 1:
        raise ContractError("invalid R2.1 fact-evidence thresholds")
    return value


def _validate_inherited(value: dict) -> None:
    retrieval = dict(value["retrieval"])
    retrieval.pop("fact_evidence", None)
    R2.load_config_from_value({**value, "retrieval": retrieval}) if hasattr(R2, "load_config_from_value") else _validate_r2_shape(value, retrieval)


def _validate_r2_shape(value: dict, retrieval: dict) -> None:
    if value["schema_version"] != 1 or value["milestone"] != R2.MILESTONE or set(retrieval) != {"kind", "top_k", "rrf_k", "admission"}:
        raise ContractError("invalid inherited R2 retrieval contract")


def fact_terms(query: str, devices: set[str], codes: set[str]) -> list[str]:
    """Deterministic lexical evidence terms; identifiers are intentionally excluded."""
    identifier_forms = {item.lower() for item in devices | codes}
    english = [
        token.lower() for token in re.findall(r"[A-Za-z0-9]+", query)
        if len(token) > 2 and token.lower() not in FACT_STOP_WORDS and token.lower() not in identifier_forms
    ]
    chinese = R2.cjk_bigrams(query)
    return list(dict.fromkeys(english + chinese))


def fact_evidence(text: str, terms: list[str]) -> dict:
    matched = [term for term in terms if term.lower() in text.lower()]
    coverage = len(matched) / len(terms) if terms else 0.0
    return {"terms": terms, "matched_terms": matched, "coverage": coverage}


def index_fingerprint(config: dict) -> str:
    payload = {"algorithm_version": ALGORITHM_VERSION, "embedding_fingerprint": config["embedding"], "retrieval": config["retrieval"]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_index(config: dict, database: pathlib.Path, provider: EmbeddingProvider, token_counter=None) -> dict:
    inherited = copy.deepcopy(config)
    inherited["milestone"] = R2.MILESTONE
    inherited["retrieval"].pop("fact_evidence")
    result = R2.build_index(inherited, database, provider, token_counter)
    connection = sqlite3.connect(database)
    try:
        connection.executemany("INSERT INTO index_metadata(key,value) VALUES(?,?)", [
            ("algorithm_version", ALGORITHM_VERSION),
            ("r2_1_index_fingerprint", index_fingerprint(config)),
            ("fact_evidence_config", json.dumps(config["retrieval"]["fact_evidence"], sort_keys=True, separators=(",", ":"))),
        ])
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ContractError("R2.1 SQLite integrity check failed")
        connection.commit()
    finally:
        connection.close()
    return {**result, "milestone": MILESTONE, "algorithm_version": ALGORITHM_VERSION, "r2_1_index_fingerprint": index_fingerprint(config)}


def query_index(database: pathlib.Path, query: str, top_k: int, provider: EmbeddingProvider, retrieval: dict) -> dict:
    if retrieval.get("kind") != "hybrid-rrf":
        raise ContractError("R2.1 requires hybrid-rrf")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        metadata = dict(connection.execute("SELECT key,value FROM index_metadata"))
    finally:
        connection.close()
    if metadata.get("algorithm_version") != ALGORITHM_VERSION:
        raise ContractError("R2.1 index algorithm version mismatch")
    raw_retrieval = copy.deepcopy(retrieval)
    raw_retrieval.pop("fact_evidence")
    raw_retrieval["admission"] = {"minimum_vector_score": 0.0, "minimum_keyword_coverage": 0.0, "minimum_margin": 0.0}
    response = R2.query_index(database, query, top_k, provider, raw_retrieval)
    if not response["results"]:
        response["admission"]["reasons"] = list(dict.fromkeys(response["admission"]["reasons"] + ["missing_fact_evidence"]))
        return response
    constraints = response["constraints"]
    evidence = fact_evidence(response["results"][0]["text"], fact_terms(query, set(constraints["devices"]), set(constraints["fault_codes"])))
    gate = retrieval["fact_evidence"]
    reasons = []
    if len(evidence["terms"]) < gate["minimum_terms"] or evidence["coverage"] < gate["minimum_coverage"]:
        reasons.append("missing_fact_evidence")
    base = response["admission"]
    if base["vector_score"] < retrieval["admission"]["minimum_vector_score"]: reasons.append("vector_score_below_threshold")
    if base["keyword_coverage"] < retrieval["admission"]["minimum_keyword_coverage"]: reasons.append("keyword_coverage_below_threshold")
    if base["margin"] < retrieval["admission"]["minimum_margin"]: reasons.append("top1_top2_margin_below_threshold")
    response["admission"] = {**base, "passed": not reasons, "reasons": reasons, "fact_evidence": evidence}
    if reasons:
        response["answerable"] = False; response["results"] = []; response["citations"] = []
    return response
