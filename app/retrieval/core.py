#!/usr/bin/env python3
"""M9.1B offline multi-document embedding and hybrid retrieval core."""

from __future__ import annotations

import hashlib
import json
import math
import os
import pathlib
import sqlite3
import struct
import subprocess
import tempfile
import re
from dataclasses import dataclass
from typing import Iterable, Protocol, Sequence

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 2
DTYPE = "float32"
NORMALIZATION = "l2"


class ContractError(ValueError):
    pass


class ProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingSpec:
    provider: str
    model_path: str
    artifact_path: str
    model_sha256: str | None
    dimension: int
    dtype: str
    normalization: str
    batch_size: int
    binary_path: str | None = None
    model_id: str | None = None
    repository: str | None = None
    revision: str | None = None
    license: str | None = None
    model_size_bytes: int | None = None
    xet_hash: str | None = None
    quantization: str | None = None
    pooling: str | None = None
    query_template: str = "{text}"
    document_template: str = "{text}"

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.__dict__, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, value: dict) -> "EmbeddingSpec":
        common = {"provider", "model_path", "artifact_path", "model_sha256", "dimension", "dtype", "normalization", "batch_size"}
        optional = {"binary_path", "model_id", "repository", "revision", "license", "model_size_bytes", "xet_hash", "quantization", "pooling", "query_template", "document_template"}
        if not common <= set(value) or set(value) - common - optional:
            raise ContractError("embedding config fields do not match the frozen contract")
        spec = cls(**value)
        if spec.provider not in {"sentence-transformers-local", "llama-cpp-gguf"}:
            raise ContractError("unsupported embedding provider")
        if not spec.model_path or not spec.artifact_path:
            raise ContractError("embedding model path and artifact must be fixed")
        if spec.model_sha256 is not None and (len(spec.model_sha256) != 64 or any(char not in "0123456789abcdef" for char in spec.model_sha256.lower())):
            raise ContractError("embedding model SHA-256 must be lowercase hexadecimal when an asset is present")
        if spec.dimension < 1 or spec.dtype != DTYPE or spec.normalization != NORMALIZATION or spec.batch_size < 1:
            raise ContractError("invalid embedding dimension, dtype, normalization, or batch size")
        if "{text}" not in spec.query_template or "{text}" not in spec.document_template:
            raise ContractError("query and document templates must contain {text}")
        if spec.provider == "llama-cpp-gguf":
            if not spec.binary_path or spec.quantization != "Q8_0" or spec.pooling != "last":
                raise ContractError("llama-cpp-gguf requires a binary path, Q8_0, and last pooling")
            if spec.dimension != 1024:
                raise ContractError("Qwen3-Embedding-0.6B dimension must be 1024")
            if spec.model_size_bytes is not None and spec.model_size_bytes < 1:
                raise ContractError("GGUF model size must be positive")
            if spec.xet_hash is not None and (len(spec.xet_hash) != 64 or any(char not in "0123456789abcdef" for char in spec.xet_hash)):
                raise ContractError("Xet hash must be lowercase hexadecimal")
        return spec


class EmbeddingProvider(Protocol):
    @property
    def spec(self) -> EmbeddingSpec: ...
    def embed(self, texts: Sequence[str], input_type: str = "document") -> list[list[float]]: ...


def apply_template(spec: EmbeddingSpec, text: str, input_type: str) -> str:
    if input_type not in {"query", "document"}:
        raise ContractError("embedding input_type must be query or document")
    template = spec.query_template if input_type == "query" else spec.document_template
    return template.replace("{text}", text)


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_repo_path(raw: str, allowed_root: pathlib.Path = ROOT / "knowledge" / "manuals") -> pathlib.Path:
    candidate = pathlib.PurePosixPath(raw)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != raw:
        raise ContractError(f"unsafe source path: {raw}")
    resolved = (ROOT / candidate).resolve()
    try:
        resolved.relative_to(allowed_root.resolve())
    except ValueError as error:
        raise ContractError(f"source is outside knowledge/manuals: {raw}") from error
    if not resolved.is_file():
        raise ContractError(f"source is not a regular file: {raw}")
    return resolved


from .markdown_index import parse_manual


class SentenceTransformersProvider:
    """A local-only provider. It never resolves model names or contacts a hub."""

    def __init__(self, spec: EmbeddingSpec):
        self._spec = spec
        self._cache = {}
        if not spec.model_sha256:
            raise ProviderUnavailable("embedding model SHA-256 is unavailable because the local asset is missing")
        model_dir = safe_model_path(spec.model_path)
        artifact = (model_dir / spec.artifact_path).resolve()
        try:
            artifact.relative_to(model_dir)
        except ValueError as error:
            raise ProviderUnavailable("embedding artifact escapes the model directory") from error
        if not artifact.is_file():
            raise ProviderUnavailable(f"embedding artifact is missing: {spec.artifact_path}")
        actual_hash = sha256_file(artifact)
        if actual_hash != spec.model_sha256:
            raise ProviderUnavailable(f"embedding artifact SHA-256 mismatch: {actual_hash}")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise ProviderUnavailable("sentence-transformers is not installed") from error
        try:
            self._model = SentenceTransformer(str(model_dir), device="cpu", local_files_only=True)
        except Exception as error:
            raise ProviderUnavailable(f"local embedding model failed to load: {error}") from error

    @property
    def spec(self) -> EmbeddingSpec:
        return self._spec

    def embed(self, texts: Sequence[str], input_type: str = "document") -> list[list[float]]:
        if not texts:
            return []
        prepared = [apply_template(self.spec, text, input_type) for text in texts]
        missing = [text for text in dict.fromkeys(prepared) if text not in self._cache]
        if missing:
            values = self._model.encode(
                missing, batch_size=self.spec.batch_size, convert_to_numpy=True,
                normalize_embeddings=False, show_progress_bar=False,
            )
            validated = validate_vectors(values.tolist(), len(missing), self.spec)
            self._cache.update(zip(missing, validated))
        return [self._cache[text] for text in prepared]

    def clear_cache(self):
        self._cache.clear()


class LlamaCppGgufProvider:
    """Offline llama-embedding provider for an audited retrieval GGUF."""

    def __init__(self, spec: EmbeddingSpec):
        self._spec = spec
        self._cache = {}
        missing = [name for name, value in (
            ("model_sha256", spec.model_sha256), ("model_size_bytes", spec.model_size_bytes),
            ("model_id", spec.model_id), ("repository", spec.repository),
            ("revision", spec.revision), ("license", spec.license), ("xet_hash", spec.xet_hash),
        ) if not value]
        if missing:
            raise ProviderUnavailable("unfrozen GGUF asset metadata: " + ", ".join(missing))
        binary = safe_repo_file(spec.binary_path, ROOT / "third_party" / "llama.cpp-omni" / "build-jetson-release" / "bin")
        model = safe_repo_file(spec.model_path, ROOT / "models" / "embedding")
        if not os.access(binary, os.X_OK):
            raise ProviderUnavailable("llama-embedding binary is not executable")
        if model.stat().st_size != spec.model_size_bytes:
            raise ProviderUnavailable(f"embedding GGUF size mismatch: {model.stat().st_size}")
        actual_hash = sha256_file(model)
        if actual_hash != spec.model_sha256:
            raise ProviderUnavailable(f"embedding GGUF SHA-256 mismatch: {actual_hash}")
        self._binary = binary
        self._model = model

    @property
    def spec(self) -> EmbeddingSpec:
        return self._spec

    def embed(self, texts: Sequence[str], input_type: str = "document") -> list[list[float]]:
        if not texts:
            return []
        prepared = [apply_template(self.spec, text, input_type) for text in texts]
        missing = [text for text in dict.fromkeys(prepared) if text not in self._cache]
        if not missing:
            return [self._cache[text] for text in prepared]
        separator = "<|edgeomni_embedding_separator_9f7a1c|>"
        if any(separator in text for text in missing):
            raise ContractError("embedding input contains the reserved separator")
        vectors = []
        for offset in range(0, len(missing), self.spec.batch_size):
            batch = missing[offset:offset + self.spec.batch_size]
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="edgeomni-embedding-", suffix=".txt") as handle:
                handle.write(separator.join(batch)); handle.flush()
                command = [
                    str(self._binary), "--model", str(self._model), "--file", handle.name,
                    "--pooling", self.spec.pooling, "--embd-normalize", "2",
                    "--embd-output-format", "array", "--embd-separator", separator,
                    "--ctx-size", "4096", "--batch-size", "4096", "--ubatch-size", "512",
                    "--gpu-layers", "99", "--no-warmup",
                ]
                result = subprocess.run(command, text=True, capture_output=True, check=False)
            if result.returncode != 0:
                raise ProviderUnavailable(f"llama-embedding failed with exit code {result.returncode}: {result.stderr[-2000:].strip()}")
            try:
                parsed = json.loads(result.stdout.strip())
            except json.JSONDecodeError as error:
                raise ProviderUnavailable("llama-embedding did not return a JSON array") from error
            if not isinstance(parsed, list):
                raise ProviderUnavailable("llama-embedding output is not an array")
            vectors.extend(parsed)
        validated = validate_vectors(vectors, len(missing), self.spec)
        self._cache.update(zip(missing, validated))
        return [self._cache[text] for text in prepared]

    def clear_cache(self):
        self._cache.clear()


def safe_model_path(raw: str) -> pathlib.Path:
    candidate = pathlib.PurePosixPath(raw)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != raw:
        raise ProviderUnavailable("embedding model path must be repository-relative")
    resolved = (ROOT / candidate).resolve()
    try:
        resolved.relative_to((ROOT / "models").resolve())
    except ValueError as error:
        raise ProviderUnavailable("embedding model must be under models/") from error
    if not resolved.is_dir():
        raise ProviderUnavailable(f"embedding model directory is missing: {raw}")
    return resolved


def safe_repo_file(raw: str | None, allowed_root: pathlib.Path) -> pathlib.Path:
    if not raw:
        raise ProviderUnavailable("required repository-relative file path is missing")
    candidate = pathlib.PurePosixPath(raw)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != raw:
        raise ProviderUnavailable("file path must be repository-relative")
    resolved = (ROOT / candidate).resolve()
    try:
        resolved.relative_to(allowed_root.resolve())
    except ValueError as error:
        raise ProviderUnavailable(f"file is outside {allowed_root.relative_to(ROOT)}") from error
    if not resolved.is_file():
        raise ProviderUnavailable(f"required local file is missing: {raw}")
    return resolved


def normalize(vector: Iterable[float]) -> list[float]:
    values = [float(item) for item in vector]
    if not values or not all(math.isfinite(item) for item in values):
        raise ContractError("embedding contains no values or non-finite values")
    norm = math.sqrt(sum(item * item for item in values))
    if norm <= 0.0:
        raise ContractError("embedding has zero norm")
    return [item / norm for item in values]


def validate_vectors(vectors: Sequence[Sequence[float]], count: int, spec: EmbeddingSpec) -> list[list[float]]:
    if len(vectors) != count:
        raise ContractError("embedding provider returned the wrong vector count")
    output = []
    for vector in vectors:
        if len(vector) != spec.dimension:
            raise ContractError("embedding dimension mismatch")
        output.append(normalize(vector))
    return output


def pack_vector(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(raw: bytes, dimension: int) -> list[float]:
    if len(raw) != dimension * 4:
        raise ContractError("embedding blob length does not match index dimension")
    return list(struct.unpack(f"<{dimension}f", raw))


def load_config(path: pathlib.Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "milestone", "sources", "tokenizer", "embedding", "retrieval", "generated_database"}
    if set(value) != required or value["schema_version"] != 2 or value["milestone"] != "M9.1B":
        raise ContractError("invalid M9.1B config")
    sources = value["sources"]
    if not isinstance(sources, list) or len(sources) < 2:
        raise ContractError("M9.1B requires at least two documents")
    paths = [item.get("source_path") for item in sources]
    if paths != sorted(paths) or len(set(paths)) != len(paths):
        raise ContractError("source paths must be unique and sorted")
    EmbeddingSpec.from_dict(value["embedding"])
    tokenizer = value["tokenizer"]
    if set(tokenizer) != {"binary", "model", "arguments"} or not isinstance(tokenizer["arguments"], list):
        raise ContractError("invalid tokenizer contract")
    retrieval = value["retrieval"]
    if set(retrieval) != {"kind", "vector_weight", "keyword_weight", "min_final_score", "top_k"}:
        raise ContractError("invalid retrieval config fields")
    if retrieval["kind"] not in {"vector", "hybrid"} or retrieval["top_k"] < 1:
        raise ContractError("invalid retrieval mode or top_k")
    pending = [retrieval[key] is None for key in ("vector_weight", "keyword_weight", "min_final_score")]
    if any(pending) and not all(pending):
        raise ContractError("retrieval weights and threshold must be all fixed or all pending")
    if not all(pending):
        if not 0.0 <= retrieval["min_final_score"] <= 1.0:
            raise ContractError("min_final_score must be in [0,1]")
        if abs(retrieval["vector_weight"] + retrieval["keyword_weight"] - 1.0) > 1e-9:
            raise ContractError("hybrid weights must sum to one")
    return value


def tokenizer_counter(config):
    tokenizer = config["tokenizer"]
    binary = ROOT / tokenizer["binary"]
    model = ROOT / tokenizer["model"]
    if not binary.is_file() or not model.is_file():
        raise ProviderUnavailable("frozen M9.1A tokenizer or model asset is missing")
    def count(text: str) -> int:
        command = [str(binary), "--model", str(model)] + [str(item) for item in tokenizer["arguments"]]
        import subprocess
        result = subprocess.run(command, input=text, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise ProviderUnavailable(f"frozen tokenizer failed with exit code {result.returncode}")
        try:
            tokens = json.loads(result.stdout.strip())
        except json.JSONDecodeError as error:
            raise ProviderUnavailable("frozen tokenizer returned invalid JSON") from error
        if not isinstance(tokens, list) or not all(isinstance(token, int) for token in tokens):
            raise ProviderUnavailable("frozen tokenizer returned invalid token IDs")
        return len(tokens)
    return count


def load_documents(config: dict) -> tuple[list[dict], list[dict]]:
    documents, chunks = [], []
    seen_documents, seen_hashes, seen_chunks = set(), set(), set()
    configured_paths = [item.get("source_path") for item in config["sources"]]
    if configured_paths != sorted(configured_paths):
        raise ContractError("source paths must be provided in stable sorted order")
    configured_ids = [item.get("document_id") for item in config["sources"]]
    if len(set(configured_ids)) != len(configured_ids):
        raise ContractError("duplicate configured document_id")
    configured_hashes = [item.get("content_sha256") for item in config["sources"]]
    if len(set(configured_hashes)) != len(configured_hashes):
        raise ContractError("duplicate document content hash")
    for source_spec in config["sources"]:
        if set(source_spec) != {"source_path", "document_id", "revision", "content_sha256"}:
            raise ContractError("invalid source config fields")
        if source_spec["content_sha256"] in seen_hashes:
            raise ContractError(f"duplicate document content hash: {source_spec['content_sha256']}")
        seen_hashes.add(source_spec["content_sha256"])
        source = safe_repo_path(source_spec["source_path"])
        document, parsed_chunks = parse_manual(source, ROOT)
        expected = (source_spec["document_id"], source_spec["revision"], source_spec["content_sha256"])
        actual = (document["document_id"], document["revision"], document["content_sha256"])
        if actual != expected:
            raise ContractError(f"document identity, revision, or hash mismatch: {source_spec['source_path']}")
        if document["source_path"] != source_spec["source_path"]:
            raise ContractError("parsed source path is unstable")
        if document["document_id"] in seen_documents:
            raise ContractError(f"duplicate document_id: {document['document_id']}")
        seen_documents.add(document["document_id"])
        for chunk in parsed_chunks:
            if chunk["chunk_id"] in seen_chunks:
                raise ContractError(f"duplicate chunk_id: {chunk['chunk_id']}")
            seen_chunks.add(chunk["chunk_id"])
            chunk["source_order"] = len(documents) + 1
            chunks.append(chunk)
        documents.append(document)
    return documents, chunks


def build_index(config: dict, database: pathlib.Path, provider: EmbeddingProvider, token_counter=None) -> dict:
    spec = EmbeddingSpec.from_dict(config["embedding"])
    if provider.spec != spec:
        raise ContractError("provider spec does not match index config")
    documents, chunks = load_documents(config)
    vectors = validate_vectors(provider.embed([chunk["text"] for chunk in chunks], "document"), len(chunks), spec)
    for chunk in chunks:
        chunk["token_count"] = token_counter(chunk["text"]) if token_counter else 0
    database.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{database.name}.", suffix=".tmp", dir=database.parent)
    os.close(file_descriptor)
    temporary = pathlib.Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript("""
            CREATE TABLE index_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE documents(document_id TEXT PRIMARY KEY, revision TEXT NOT NULL, source_path TEXT NOT NULL UNIQUE, content_sha256 TEXT NOT NULL, title TEXT NOT NULL, language TEXT NOT NULL, classification TEXT NOT NULL);
            CREATE TABLE chunks(chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(document_id), heading TEXT NOT NULL, source_order INTEGER NOT NULL, ordinal INTEGER NOT NULL, text TEXT NOT NULL, text_sha256 TEXT NOT NULL, token_count INTEGER NOT NULL, citation_json TEXT NOT NULL, UNIQUE(document_id, ordinal));
            CREATE TABLE chunk_embeddings(chunk_id TEXT PRIMARY KEY REFERENCES chunks(chunk_id), dimension INTEGER NOT NULL, dtype TEXT NOT NULL, normalization TEXT NOT NULL, vector BLOB NOT NULL);
            CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, heading, text, tokenize='porter unicode61');
            """)
            metadata = {
                "schema_version": str(SCHEMA_VERSION), "milestone": "M9.1B",
                "embedding_fingerprint": spec.fingerprint, "embedding_provider": spec.provider,
                "model_path": spec.model_path, "model_sha256": spec.model_sha256,
                "dimension": str(spec.dimension), "dtype": spec.dtype,
                "normalization": spec.normalization,
            }
            connection.executemany("INSERT INTO index_metadata VALUES(?,?)", sorted(metadata.items()))
            for document in documents:
                connection.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)", tuple(document.values()))
            for chunk, vector in zip(chunks, vectors):
                citation = json.dumps(chunk["citation"], sort_keys=True, separators=(",", ":"))
                connection.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?)", (
                    chunk["chunk_id"], chunk["document_id"], chunk["heading"], chunk["source_order"],
                    chunk["ordinal"], chunk["text"], chunk["text_sha256"], chunk["token_count"], citation,
                ))
                connection.execute("INSERT INTO chunk_embeddings VALUES(?,?,?,?,?)", (
                    chunk["chunk_id"], spec.dimension, spec.dtype, spec.normalization, pack_vector(vector),
                ))
                connection.execute("INSERT INTO chunks_fts VALUES(?,?,?)", (chunk["chunk_id"], chunk["heading"], chunk["text"]))
            connection.commit()
            validate_index(connection, spec)
        finally:
            connection.close()
        os.replace(temporary, database)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "schema_version": SCHEMA_VERSION, "documents": documents,
        "chunks": [{key: chunk[key] for key in ("chunk_id", "document_id", "heading", "source_order", "ordinal", "text_sha256", "token_count", "citation")} for chunk in chunks],
        "embedding_fingerprint": spec.fingerprint, "database_path": str(database),
        "database_size_bytes": database.stat().st_size,
    }


def metadata(connection: sqlite3.Connection) -> dict[str, str]:
    try:
        return dict(connection.execute("SELECT key,value FROM index_metadata"))
    except sqlite3.DatabaseError as error:
        raise ContractError(f"index metadata is unreadable: {error}") from error


def validate_index(connection: sqlite3.Connection, spec: EmbeddingSpec) -> None:
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ContractError(f"SQLite integrity check failed: {integrity}")
        meta = metadata(connection)
        expected = {
            "schema_version": str(SCHEMA_VERSION), "milestone": "M9.1B",
            "embedding_fingerprint": spec.fingerprint, "embedding_provider": spec.provider,
            "model_path": spec.model_path, "model_sha256": spec.model_sha256,
            "dimension": str(spec.dimension), "dtype": spec.dtype, "normalization": spec.normalization,
        }
        if meta != expected:
            raise ContractError("index metadata or embedding fingerprint mismatch")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ContractError("index contains foreign-key violations")
        rows = connection.execute("SELECT dimension,dtype,normalization,length(vector),vector FROM chunk_embeddings ORDER BY chunk_id").fetchall()
        chunk_count = connection.execute("SELECT count(*) FROM chunks").fetchone()[0]
        fts_count = connection.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
        if not rows or len(rows) != chunk_count or fts_count != chunk_count:
            raise ContractError("index has missing chunk embeddings")
        for dimension, dtype, normalization_name, byte_count, raw in rows:
            if (dimension, dtype, normalization_name, byte_count) != (spec.dimension, spec.dtype, spec.normalization, spec.dimension * 4):
                raise ContractError("index contains an incompatible embedding")
            vector = unpack_vector(raw, dimension)
            norm = math.sqrt(sum(value * value for value in vector))
            if not all(math.isfinite(value) for value in vector) or abs(norm - 1.0) > 1e-4:
                raise ContractError("index contains a non-finite or non-normalized embedding")
    except sqlite3.DatabaseError as error:
        raise ContractError(f"index is corrupt or has an invalid schema: {error}") from error


def keyword_ranks(connection: sqlite3.Connection, query: str) -> dict[str, float]:
    terms = re.findall(r"[A-Za-z0-9]+", query.lower())
    terms = [term for term in terms if len(term) > 1]
    if not terms:
        return {}
    expression = " OR ".join(f'"{term}"' for term in dict.fromkeys(terms))
    rows = connection.execute(
        "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts), chunk_id", (expression,)
    ).fetchall()
    return {row[0]: 1.0 / rank for rank, row in enumerate(rows, 1)}


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ContractError("cosine dimension mismatch")
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def query_index(database: pathlib.Path, query: str, top_k: int, provider: EmbeddingProvider, retrieval: dict) -> dict:
    if not query.strip() or top_k < 1:
        raise ContractError("query must be non-empty and top_k must be positive")
    spec = provider.spec
    mode = retrieval["kind"]
    if mode not in {"keyword", "vector", "hybrid"}:
        raise ContractError("retrieval kind must be keyword, vector, or hybrid")
    query_vector = validate_vectors(provider.embed([query], "query"), 1, spec)[0] if mode != "keyword" else None
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    except sqlite3.DatabaseError as error:
        raise ContractError(f"index cannot be opened read-only: {error}") from error
    connection.row_factory = sqlite3.Row
    try:
        validate_index(connection, spec)
        keyword = keyword_ranks(connection, query) if mode in {"keyword", "hybrid"} else {}
        rows = connection.execute("SELECT c.*,e.dimension,e.vector FROM chunks c JOIN chunk_embeddings e USING(chunk_id) ORDER BY c.source_order,c.ordinal").fetchall()
        ranked = []
        for row in rows:
            vector_score = cosine(query_vector, unpack_vector(row["vector"], row["dimension"])) if query_vector is not None else 0.0
            keyword_score = keyword.get(row["chunk_id"], 0.0)
            final_score = retrieval["vector_weight"] * max(0.0, vector_score) + retrieval["keyword_weight"] * keyword_score
            ranked.append((final_score, vector_score, keyword_score, row))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[3]["source_order"], item[3]["ordinal"], item[3]["chunk_id"]))
        threshold = float(retrieval["min_final_score"])
        top_score = ranked[0][0] if ranked else None
        response = {
            "query": query, "mode": mode, "answerable": False, "top_k": top_k,
            "threshold": threshold, "top_candidate_score": top_score, "results": [], "citations": [],
        }
        if top_score is None or top_score < threshold:
            return response
        admitted = [item for item in ranked if item[0] >= threshold][:top_k]
        for final_score, vector_score, keyword_score, row in admitted:
            citation = json.loads(row["citation_json"])
            result = {
                "document_id": row["document_id"], "chunk_id": row["chunk_id"],
                "heading": row["heading"], "text": row["text"], "citation": citation,
                "vector_score": round(vector_score, 8), "keyword_score": round(keyword_score, 8),
                "final_score": round(final_score, 8),
            }
            response["results"].append(result)
            response["citations"].append(citation)
        response["answerable"] = True
        return response
    finally:
        connection.close()


def provider_from_config(config: dict) -> EmbeddingProvider:
    spec = EmbeddingSpec.from_dict(config["embedding"])
    if spec.provider == "llama-cpp-gguf":
        return LlamaCppGgufProvider(spec)
    return SentenceTransformersProvider(spec)
