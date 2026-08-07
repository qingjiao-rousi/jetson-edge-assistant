#!/usr/bin/env python3
"""M9.2 prototype: retrieve manual passages, then generate an answer with their citations."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]

from app.retrieval.core import ContractError, provider_from_config
from app.retrieval.embedding import load_config as load_embedding_config
from app.retrieval.engine import query_index

MILESTONE = "M9.2-PROTOTYPE"
MANUAL_GROUNDED_SYSTEM_PROMPT = (
    "You are an industrial equipment manual assistant. Answer only from the supplied manual "
    "evidence. Do not invent limits, procedures, causes, or facts. If the evidence is insufficient, "
    "say that the supplied manual evidence is insufficient. Cite every factual statement with one or "
    "more evidence markers such as [S1]. Reply in the user's language when practical."
)
# Compatibility name for callers that imported the original prompt constant.
SYSTEM_PROMPT = MANUAL_GROUNDED_SYSTEM_PROMPT
GENERAL_EXPLANATION_SYSTEM_PROMPT = (
    "你是一般知识解释助手。只做一般知识解释，不假设设备型号、现场参数或工况。"
    "不要输出 [S1] 或其他 citation 标记。不要提供维修步骤、带压操作、旁路或复位安全联锁、"
    "绕过保护、危险化学品处置等安全关键指令。遇到危险或设备特定问题时，建议查阅受控资料并由合格人员确认。"
)


def repo_path(value: str) -> pathlib.Path:
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ContractError("M9.2 paths must be repository-relative")
    return ROOT / path


def load_config(path: pathlib.Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "milestone", "retrieval_config", "embedding_config", "max_new_tokens", "timeout_seconds"}
    if set(config) != required or config["schema_version"] != 2 or config["milestone"] != MILESTONE:
        raise ContractError("invalid M9.2 config")
    if not all(isinstance(config[key], str) and config[key] for key in ("retrieval_config", "embedding_config")):
        raise ContractError("invalid M9.2 module paths")
    if not isinstance(config["max_new_tokens"], int) or config["max_new_tokens"] < 1:
        raise ContractError("invalid M9.2 max_new_tokens")
    if not isinstance(config["timeout_seconds"], int) or config["timeout_seconds"] < 1:
        raise ContractError("invalid M9.2 timeout_seconds")
    return config


def bind_runtime(config: dict, database: str, model_endpoint: str) -> dict:
    """Bind shared top-level assets without duplicating them in this module config."""
    if not isinstance(database, str) or not database:
        raise ContractError("M9.2 database must be a repository-relative path")
    repo_path(database)
    if not isinstance(model_endpoint, str) or not model_endpoint.startswith(("http://", "https://")):
        raise ContractError("M9.2 model endpoint must be HTTP(S)")
    return {**config, "database": database, "model_endpoint": model_endpoint}


def citation_id(index: int) -> str:
    return f"S{index}"


def prompt_for(query: str, results: list[dict]) -> str:
    evidence = []
    for index, result in enumerate(results, 1):
        evidence.append("\n".join((
            f"[{citation_id(index)}] chunk_id: {result['chunk_id']}",
            f"heading: {result['heading']}",
            f"manual text: {result['text']}",
        )))
    return "\n\n".join(("Manual evidence:", "\n\n".join(evidence), f"\nUser question: {query}", "Answer:"))


def cited_results(results: list[dict]) -> list[dict]:
    return [{"id": citation_id(index), "chunk_id": item["chunk_id"], "citation": item["citation"]} for index, item in enumerate(results, 1)]


def call_model(endpoint: str, request_id: str, prompt: str, max_new_tokens: int, timeout_seconds: int,
               system_prompt: str = MANUAL_GROUNDED_SYSTEM_PROMPT) -> tuple[dict | None, dict]:
    """Call the local Runtime, retaining the manual-grounded prompt as the default."""
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise ContractError("system_prompt must be a non-empty string")
    payload = {"request_id": request_id, "session_id": None, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}], "max_new_tokens": max_new_tokens, "stream": False}
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    metadata = {"endpoint": endpoint, "request_id": request_id, "http_status": None}
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
            metadata["http_status"] = response.status
    except urllib.error.HTTPError as error:
        metadata.update(http_status=error.code, error="http_error")
        return None, metadata
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        metadata.update(error="connection_error", detail=str(error))
        return None, metadata
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        metadata["error"] = "invalid_json_response"
        return None, metadata
    if not isinstance(body, dict) or not isinstance(body.get("text"), str) or body.get("error") is not None:
        metadata["error"] = "invalid_model_response"
        return None, metadata
    return body, metadata


def answer_query(query: str, config: dict, request_id: str | None = None, provider=None, retrieval_fn=query_index, model_call=call_model) -> dict:
    if not isinstance(query, str) or not query.strip():
        raise ContractError("query must be non-empty")
    if "database" not in config or "model_endpoint" not in config:
        raise ContractError("M9.2 requires shared Runtime and RAG bindings from configs/assistant.json")
    retrieval_config = json.loads(repo_path(config["retrieval_config"]).read_text(encoding="utf-8"))
    embedding_config = load_embedding_config(repo_path(config["embedding_config"]))
    provider = provider or provider_from_config(embedding_config)
    retrieval = retrieval_fn(repo_path(config["database"]), query, retrieval_config["retrieval"]["top_k"], provider, retrieval_config["retrieval"])
    base = {"schema_version": 1, "milestone": MILESTONE, "prototype_only": True, "query": query, "retrieval": {"answerable": retrieval["answerable"], "admission": retrieval["admission"], "constraints": retrieval.get("constraints", {})}}
    if not retrieval["answerable"] or not retrieval["results"]:
        return {**base, "status": "NO_EVIDENCE", "answer": None, "citations": [], "model": {"called": False}}
    citations = cited_results(retrieval["results"])
    request_id = request_id or f"rag-vlm-m9.2-{uuid.uuid4()}"
    model_response, model_metadata = model_call(config["model_endpoint"], request_id, prompt_for(query, retrieval["results"]), config["max_new_tokens"], config["timeout_seconds"])
    if model_response is None:
        return {**base, "status": "MODEL_UNAVAILABLE", "answer": None, "citations": citations, "model": {"called": True, **model_metadata}}
    return {**base, "status": "OK", "answer": model_response["text"], "citations": citations, "model": {"called": True, **model_metadata, "response_request_id": model_response.get("request_id"), "finish_reason": model_response.get("finish_reason"), "metrics": model_response.get("metrics")}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--config", default="configs/assistant.json", help="top-level assistant config")
    parser.add_argument("--request-id")
    args = parser.parse_args()
    try:
        from app.assistant.application import load_config as load_assistant_config
        assistant_config = load_assistant_config(args.config)
        result = answer_query(args.query, assistant_config["_manual"], args.request_id)
    except (ContractError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"OK", "NO_EVIDENCE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
