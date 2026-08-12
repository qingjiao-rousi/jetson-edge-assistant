"""Unvalidated R2.6 candidate: restore the final keyword-coverage gate.

This module is intentionally not imported by the active RAG pipeline. It
delegates to the frozen R2.5 query-time gate and only rejects an otherwise
admitted response when its existing R2 base keyword coverage is below the
configured admission threshold.
"""

from __future__ import annotations

import json
import pathlib

from .core import ContractError
from .engine import query_index as _query_r2_5


MILESTONE = "M9.1B-R2.6-CANDIDATE"
_CANDIDATE = {
    "status": "UNVALIDATED",
    "algorithm_difference": "restore_minimum_keyword_coverage_final_gate",
    "does_not_replace": "M9.1B-R2.5",
}
_RETRIEVAL = {
    "kind": "hybrid-rrf",
    "top_k": 3,
    "rrf_k": 60,
    "admission": {
        "minimum_vector_score": 0.4,
        "minimum_keyword_coverage": 0.1,
        "minimum_margin": 0.0001,
    },
    "fact_evidence": {"minimum_coverage": 0.25, "minimum_terms": 1},
}
_QUALITY_GATE = {
    "mode": "hybrid",
    "minimum_recall_at_1": 0.75,
    "minimum_recall_at_3": 0.875,
    "minimum_mrr": 0.8,
    "minimum_no_answer_correct_rejection_rate": 0.75,
    "maximum_false_positive_count": 1,
}
_INDEX_CONTRACT = {
    "schema_version": "3",
    "milestone": "M9.1B-R2",
    "text_format_version": "structured-v1",
    "chinese_fts_strategy": "unicode61-cjk-bigram-v1",
    "algorithm_version": "concept-fact-family-v1",
    "r2_2_index_fingerprint": "efa33d208db4c9401b06233027e1fc3126051b6bf383bef81d4b3f6a104d103f",
}
_EMBEDDING_FINGERPRINT = "d0540b3ebba59a403437b0866625bd5d8392484806b41716a95c528bab4547b9"
_BASE_ALGORITHM_FINGERPRINT = "0d84afa229f49d779059ea83d658b768ba91063832377d651702d8d330575df2"


def load_config(path: pathlib.Path) -> dict:
    """Load the fixed candidate contract and reject unknown or tuned fields."""
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version", "milestone", "candidate", "base_algorithm_fingerprint",
        "embedding_fingerprint", "retrieval", "quality_gate", "index_contract",
    }
    if set(value) != required or value["schema_version"] != 1 or value["milestone"] != MILESTONE:
        raise ContractError("invalid R2.6 candidate config shape")
    if value["candidate"] != _CANDIDATE:
        raise ContractError("invalid R2.6 candidate status or algorithm declaration")
    if value["base_algorithm_fingerprint"] != _BASE_ALGORITHM_FINGERPRINT:
        raise ContractError("R2.6 candidate must retain the frozen R2.5 base fingerprint")
    if value["embedding_fingerprint"] != _EMBEDDING_FINGERPRINT:
        raise ContractError("R2.6 candidate must retain the R2.2 embedding contract")
    if value["retrieval"] != _RETRIEVAL:
        raise ContractError("R2.6 candidate retrieval parameters must remain frozen")
    if value["quality_gate"] != _QUALITY_GATE or value["index_contract"] != _INDEX_CONTRACT:
        raise ContractError("R2.6 candidate quality or index contract mismatch")
    return value


def query_index(database, query, top_k, provider, retrieval):
    """Apply exactly one additional final gate to an R2.5 query response."""
    response = _query_r2_5(database, query, top_k, provider, retrieval)
    if not response["results"]:
        return response

    admission = response["admission"]
    if admission["keyword_coverage"] >= retrieval["admission"]["minimum_keyword_coverage"]:
        return response

    reasons = list(dict.fromkeys(admission["reasons"] + ["keyword_coverage_below_threshold"]))
    response["answerable"] = False
    response["results"] = []
    response["citations"] = []
    response["admission"] = {**admission, "passed": False, "reasons": reasons}
    return response
