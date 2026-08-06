#!/usr/bin/env python3
"""M9.1B-R2: constrained hybrid retrieval with separate admission."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import sqlite3
import tempfile
from typing import Sequence

from .core import (
    ROOT, ContractError, EmbeddingProvider, EmbeddingSpec, cosine, load_documents,
    normalize, pack_vector, unpack_vector, validate_vectors,
)

SCHEMA_VERSION = 3
MILESTONE = "M9.1B-R2"
TEXT_FORMAT_VERSION = "structured-v1"
CHINESE_FTS_STRATEGY = "unicode61-cjk-bigram-v1"
STOP_WORDS = frozenset({
    "a", "an", "and", "are", "be", "by", "does", "for", "how", "in", "is",
    "it", "of", "on", "should", "the", "to", "what", "when", "which", "with",
})


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_config(path: pathlib.Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "milestone", "sources", "tokenizer", "embedding", "retrieval", "generated_database"}
    if set(value) != required or value["schema_version"] != 1 or value["milestone"] != MILESTONE:
        raise ContractError("invalid M9.1B-R2 config")
    EmbeddingSpec.from_dict(value["embedding"])
    retrieval = value["retrieval"]
    expected = {"kind", "top_k", "rrf_k", "admission"}
    admission = {"minimum_vector_score", "minimum_keyword_coverage", "minimum_margin"}
    if set(retrieval) != expected or retrieval["kind"] != "hybrid-rrf" or retrieval["top_k"] < 1 or retrieval["rrf_k"] < 1:
        raise ContractError("invalid R2 retrieval contract")
    if set(retrieval["admission"]) != admission:
        raise ContractError("invalid R2 admission contract")
    for key, value_ in retrieval["admission"].items():
        if not isinstance(value_, (int, float)) or value_ < 0.0 or value_ > 1.0:
            raise ContractError(f"invalid R2 admission value: {key}")
    return value


def cjk_bigrams(text: str) -> list[str]:
    values = []
    for sequence in re.findall(r"[\u3400-\u9fff]+", text):
        values.extend(sequence[index:index + 2] for index in range(len(sequence) - 1))
        if len(sequence) == 1:
            values.append(sequence)
    return values


def fts_text(value: str) -> str:
    return " ".join(cjk_bigrams(value))


def structured_text(document: dict, chunk: dict) -> str:
    return "\n".join((
        f"Document: {document['title']}",
        f"Device: {device_id(document)}",
        f"Section: {chunk['heading']}",
        f"Content: {chunk['text']}",
    ))


def device_id(document: dict) -> str:
    found = re.search(r"\b[A-Z]{1,5}-\d{1,4}\b", document["title"].upper())
    if not found:
        raise ContractError(f"document title has no stable device ID: {document['document_id']}")
    return found.group(0)


def parse_constraints(query: str, devices: set[str]) -> tuple[set[str], set[str]]:
    normalized = query.upper()
    requested_devices = set()
    for device in devices:
        pattern = re.escape(device).replace("\\-", "[- ]?")
        if re.search(rf"(?<![A-Z0-9]){pattern}(?![A-Z0-9])", normalized):
            requested_devices.add(device)
    codes = set(re.findall(r"(?<![A-Z0-9-])[A-Z]\d{2,4}(?![A-Z0-9])", normalized))
    return requested_devices, codes


def informative_terms(query: str, devices: set[str], codes: set[str]) -> list[str]:
    excluded = {item.lower() for item in devices | codes}
    ascii_terms = [
        item.lower() for item in re.findall(r"[A-Za-z0-9]+", query)
        if len(item) > 2 and item.lower() not in STOP_WORDS and item.lower() not in excluded
    ]
    return list(dict.fromkeys(ascii_terms + cjk_bigrams(query)))


def require_fts5(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("CREATE VIRTUAL TABLE fts5_probe USING fts5(body, tokenize='unicode61')")
        connection.execute("INSERT INTO fts5_probe VALUES (?)", ("输送带 跑偏",))
        if connection.execute("SELECT count(*) FROM fts5_probe WHERE fts5_probe MATCH '输送带'").fetchone()[0] != 1:
            raise ContractError("SQLite FTS5 unicode61 probe failed")
        connection.execute("DROP TABLE fts5_probe")
    except sqlite3.DatabaseError as error:
        raise ContractError(f"SQLite FTS5 is unavailable: {error}") from error


def build_index(config: dict, database: pathlib.Path, provider: EmbeddingProvider, token_counter=None) -> dict:
    spec = EmbeddingSpec.from_dict(config["embedding"])
    if provider.spec != spec:
        raise ContractError("provider spec does not match R2 index config")
    documents, chunks = load_documents(config)
    documents_by_id = {item["document_id"]: item for item in documents}
    prepared = [structured_text(documents_by_id[item["document_id"]], item) for item in chunks]
    vectors = validate_vectors(provider.embed(prepared, "document"), len(chunks), spec)
    for chunk, content in zip(chunks, prepared):
        chunk["structured_text"] = content
        chunk["fts_text"] = "\n".join((content, fts_text(content)))
        chunk["token_count"] = token_counter(content) if token_counter else 0
    database.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{database.name}.", suffix=".tmp", dir=database.parent)
    os.close(descriptor)
    temporary = pathlib.Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary)
        try:
            require_fts5(connection)
            connection.executescript("""
            CREATE TABLE index_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE documents(document_id TEXT PRIMARY KEY, device_id TEXT NOT NULL UNIQUE, revision TEXT NOT NULL, source_path TEXT NOT NULL UNIQUE, content_sha256 TEXT NOT NULL, title TEXT NOT NULL, language TEXT NOT NULL, classification TEXT NOT NULL);
            CREATE TABLE chunks(chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(document_id), heading TEXT NOT NULL, source_order INTEGER NOT NULL, ordinal INTEGER NOT NULL, text TEXT NOT NULL, structured_text TEXT NOT NULL, fts_text TEXT NOT NULL, text_sha256 TEXT NOT NULL, token_count INTEGER NOT NULL, citation_json TEXT NOT NULL, UNIQUE(document_id, ordinal));
            CREATE TABLE chunk_embeddings(chunk_id TEXT PRIMARY KEY REFERENCES chunks(chunk_id), dimension INTEGER NOT NULL, dtype TEXT NOT NULL, normalization TEXT NOT NULL, vector BLOB NOT NULL);
            CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, body, tokenize='unicode61');
            """)
            metadata = {
                "schema_version": str(SCHEMA_VERSION), "milestone": MILESTONE,
                "embedding_fingerprint": spec.fingerprint, "text_format_version": TEXT_FORMAT_VERSION,
                "chinese_fts_strategy": CHINESE_FTS_STRATEGY,
            }
            connection.executemany("INSERT INTO index_metadata VALUES(?,?)", sorted(metadata.items()))
            for document in documents:
                connection.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?)", (
                    document["document_id"], device_id(document), document["revision"], document["source_path"],
                    document["content_sha256"], document["title"], document["language"], document["classification"],
                ))
            for chunk, vector in zip(chunks, vectors):
                connection.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                    chunk["chunk_id"], chunk["document_id"], chunk["heading"], chunk["source_order"], chunk["ordinal"],
                    chunk["text"], chunk["structured_text"], chunk["fts_text"], chunk["text_sha256"], chunk["token_count"],
                    json.dumps(chunk["citation"], sort_keys=True, separators=(",", ":")),
                ))
                connection.execute("INSERT INTO chunk_embeddings VALUES(?,?,?,?,?)", (chunk["chunk_id"], spec.dimension, spec.dtype, spec.normalization, pack_vector(vector)))
                connection.execute("INSERT INTO chunks_fts VALUES(?,?)", (chunk["chunk_id"], chunk["fts_text"]))
            connection.commit()
        finally:
            connection.close()
        os.replace(temporary, database)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"schema_version": SCHEMA_VERSION, "milestone": MILESTONE, "database_path": str(database), "embedding_fingerprint": spec.fingerprint, "text_format_version": TEXT_FORMAT_VERSION, "chinese_fts_strategy": CHINESE_FTS_STRATEGY, "documents": documents, "database_size_bytes": database.stat().st_size}


def keyword_rankings(connection: sqlite3.Connection, terms: list[str], allowed_devices: set[str], codes: set[str]) -> dict[str, int]:
    if not terms:
        return {}
    expression = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
    clauses, params = [], [expression]
    if allowed_devices:
        clauses.append("d.device_id IN (%s)" % ",".join("?" for _ in allowed_devices))
        params.extend(sorted(allowed_devices))
    if codes:
        clauses.extend("upper(c.fts_text) LIKE ?" for _ in codes)
        params.extend(f"%{code}%" for code in sorted(codes))
    where = (" AND " + " AND ".join(clauses)) if clauses else ""
    rows = connection.execute("SELECT f.chunk_id FROM chunks_fts f JOIN chunks c USING(chunk_id) JOIN documents d USING(document_id) WHERE f.body MATCH ?" + where + " ORDER BY bm25(chunks_fts), c.chunk_id", params).fetchall()
    return {row[0]: rank for rank, row in enumerate(rows, 1)}


def query_index(database: pathlib.Path, query: str, top_k: int, provider: EmbeddingProvider, retrieval: dict) -> dict:
    if not query.strip() or top_k < 1:
        raise ContractError("query must be non-empty and top_k must be positive")
    spec = provider.spec
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        meta = dict(connection.execute("SELECT key,value FROM index_metadata"))
        if meta.get("schema_version") != str(SCHEMA_VERSION) or meta.get("embedding_fingerprint") != spec.fingerprint or meta.get("text_format_version") != TEXT_FORMAT_VERSION or meta.get("chinese_fts_strategy") != CHINESE_FTS_STRATEGY:
            raise ContractError("R2 index metadata mismatch")
        device_rows = connection.execute("SELECT device_id FROM documents").fetchall()
        devices = {row[0] for row in device_rows}
        requested_devices, codes = parse_constraints(query, devices)
        terms = informative_terms(query, requested_devices, codes)
        keyword = keyword_rankings(connection, terms, requested_devices, codes)
        clauses, params = [], []
        if requested_devices:
            clauses.append("d.device_id IN (%s)" % ",".join("?" for _ in requested_devices)); params.extend(sorted(requested_devices))
        if codes:
            clauses.extend("upper(c.fts_text) LIKE ?" for _ in codes); params.extend(f"%{code}%" for code in sorted(codes))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = connection.execute("SELECT c.*,d.device_id,e.dimension,e.vector FROM chunks c JOIN documents d USING(document_id) JOIN chunk_embeddings e USING(chunk_id)" + where, params).fetchall()
        if not rows:
            return {"query": query, "answerable": False, "results": [], "citations": [], "admission": {"passed": False, "reasons": ["no_candidate_satisfies_hard_constraints"]}, "constraints": {"devices": sorted(requested_devices), "fault_codes": sorted(codes)}}
        query_vector = validate_vectors(provider.embed([query], "query"), 1, spec)[0]
        scored = []
        for row in rows:
            vector_score = cosine(query_vector, unpack_vector(row["vector"], row["dimension"]))
            covered = sum(term.lower() in row["fts_text"].lower() for term in terms) / len(terms) if terms else 1.0
            scored.append({"row": row, "vector_score": vector_score, "keyword_rank": keyword.get(row["chunk_id"]), "keyword_coverage": covered})
        for rank, item in enumerate(sorted(scored, key=lambda value: (-value["vector_score"], value["row"]["chunk_id"])), 1):
            item["vector_rank"] = rank
        for item in scored:
            rrf = 1.0 / (retrieval["rrf_k"] + item["vector_rank"])
            if item["keyword_rank"] is not None:
                rrf += 1.0 / (retrieval["rrf_k"] + item["keyword_rank"])
            item["ranking_score"] = rrf
        ranked = sorted(scored, key=lambda value: (-value["ranking_score"], -value["vector_score"], value["row"]["source_order"], value["row"]["ordinal"], value["row"]["chunk_id"]))
        top = ranked[0]
        margin = top["ranking_score"] - ranked[1]["ranking_score"] if len(ranked) > 1 else top["ranking_score"]
        gate = retrieval["admission"]
        reasons = []
        if top["vector_score"] < gate["minimum_vector_score"]: reasons.append("vector_score_below_threshold")
        if top["keyword_coverage"] < gate["minimum_keyword_coverage"]: reasons.append("keyword_coverage_below_threshold")
        if margin < gate["minimum_margin"]: reasons.append("top1_top2_margin_below_threshold")
        response = {"query": query, "answerable": not reasons, "results": [], "citations": [], "constraints": {"devices": sorted(requested_devices), "fault_codes": sorted(codes)}, "admission": {"passed": not reasons, "reasons": reasons, "vector_score": round(top["vector_score"], 8), "keyword_coverage": round(top["keyword_coverage"], 8), "margin": round(margin, 8)}}
        if reasons:
            return response
        for item in ranked[:top_k]:
            row = item["row"]; citation = json.loads(row["citation_json"])
            response["results"].append({"document_id": row["document_id"], "device_id": row["device_id"], "chunk_id": row["chunk_id"], "heading": row["heading"], "text": row["text"], "citation": citation, "ranking_score": round(item["ranking_score"], 8), "vector_score": round(item["vector_score"], 8), "keyword_rank": item["keyword_rank"], "keyword_coverage": round(item["keyword_coverage"], 8)})
            response["citations"].append(citation)
        return response
    finally:
        connection.close()
