#!/usr/bin/env python3
"""M10.2 bounded read-only tools, deterministic planning, and process-local sessions."""
from __future__ import annotations

import json
import argparse
import pathlib
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
MILESTONE = "M10.2-PROTOTYPE"
ALLOWED_TOOLS = frozenset({"search_manuals", "read_manual", "lookup_fault_code"})
MAX_STEPS = 3
MAX_SESSIONS = 8
MAX_TURNS = 20


class ToolContractError(ValueError):
    pass


def _safe_manual_path(raw: str) -> pathlib.Path:
    candidate = pathlib.PurePosixPath(raw)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != raw:
        raise ToolContractError("path must be repository-relative without '..'")
    resolved = (ROOT / candidate).resolve()
    try:
        resolved.relative_to((ROOT / "knowledge" / "manuals").resolve())
    except ValueError as error:
        raise ToolContractError("path is outside knowledge/manuals") from error
    if not resolved.is_file():
        raise ToolContractError("manual path is not a regular file")
    return resolved


@dataclass
class ToolAudit:
    tool: str
    arguments: dict
    status: str
    elapsed_ms: int
    error: str | None = None

    def as_dict(self) -> dict:
        value = {"tool": self.tool, "arguments": self.arguments, "status": self.status, "elapsed_ms": self.elapsed_ms}
        if self.error:
            value["error"] = self.error
        return value


class ReadOnlyTools:
    """Allowlisted local tools. Every call returns a structured audit record."""

    def __init__(self, fault_config: pathlib.Path | None = None, max_bytes: int = 256 * 1024):
        self.max_bytes = max_bytes
        path = fault_config or ROOT / "configs" / "tool-fault-codes-m10.2.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or value.get("milestone") != MILESTONE or not isinstance(value.get("fault_codes"), list):
            raise ToolContractError("invalid fault-code tool manifest")
        self.fault_codes = value["fault_codes"]
        self.audit: list[dict] = []

    def _record(self, name: str, arguments: dict, started: float, status: str, error: str | None = None) -> None:
        item = ToolAudit(name, arguments, status, round((time.monotonic() - started) * 1000), error).as_dict()
        self.audit.append(item)

    def read_manual(self, source_path: str) -> dict:
        started = time.monotonic(); args = {"source_path": source_path}
        try:
            path = _safe_manual_path(source_path)
            if path.stat().st_size > self.max_bytes:
                raise ToolContractError("manual exceeds read size limit")
            result = {"source_path": source_path, "text": path.read_text(encoding="utf-8"), "bytes": path.stat().st_size}
            self._record("read_manual", args, started, "ok")
            return result
        except (OSError, UnicodeError, ToolContractError) as error:
            self._record("read_manual", args, started, "error", str(error)); raise

    def search_manuals(self, query: str, max_results: int = 5) -> dict:
        started = time.monotonic(); args = {"query": query, "max_results": max_results}
        try:
            if not isinstance(query, str) or not query.strip() or not 1 <= max_results <= 20:
                raise ToolContractError("query must be non-empty and max_results must be 1..20")
            needle = query.casefold()
            matches = []
            for path in sorted((ROOT / "knowledge" / "manuals").glob("*.md")):
                text = path.read_text(encoding="utf-8")
                if needle in text.casefold():
                    lines = [line.strip() for line in text.splitlines() if needle in line.casefold()][:3]
                    matches.append({"source_path": str(path.relative_to(ROOT)), "matches": lines})
                if len(matches) >= max_results: break
            result = {"query": query, "results": matches}
            self._record("search_manuals", args, started, "ok"); return result
        except (OSError, UnicodeError, ToolContractError) as error:
            self._record("search_manuals", args, started, "error", str(error)); raise

    def lookup_fault_code(self, device_id: str, code: str) -> dict:
        started = time.monotonic(); args = {"device_id": device_id, "code": code}
        try:
            if not re.fullmatch(r"[A-Z]{1,5}-\d{1,4}", device_id.upper()) or not re.fullmatch(r"[A-Z]\d{2,4}", code.upper()):
                raise ToolContractError("invalid device_id or fault code format")
            found = [item for item in self.fault_codes if item["device_id"].casefold() == device_id.casefold() and item["code"].casefold() == code.casefold()]
            result = {"device_id": device_id.upper(), "code": code.upper(), "found": bool(found), "results": found}
            self._record("lookup_fault_code", args, started, "ok"); return result
        except ToolContractError as error:
            self._record("lookup_fault_code", args, started, "error", str(error)); raise


@dataclass
class Session:
    session_id: str
    turns: list[dict] = field(default_factory=list)


class SessionStore:
    """Bounded process-local conversation store; it is not a persistent KV cache."""

    def __init__(self, max_sessions: int = MAX_SESSIONS, max_turns: int = MAX_TURNS):
        if not 1 <= max_sessions <= 64 or not 1 <= max_turns <= 100:
            raise ToolContractError("invalid session limits")
        self.max_sessions, self.max_turns = max_sessions, max_turns
        self._sessions: dict[str, Session] = {}

    def get(self, session_id: str) -> Session:
        if not isinstance(session_id, str) or not session_id or len(session_id) > 128:
            raise ToolContractError("session_id must be a non-empty string of at most 128 characters")
        if session_id not in self._sessions:
            if len(self._sessions) >= self.max_sessions:
                raise ToolContractError("session capacity exceeded")
            self._sessions[session_id] = Session(session_id)
        return self._sessions[session_id]

    def append(self, session_id: str, user: str, assistant: str) -> Session:
        session = self.get(session_id)
        session.turns.append({"user": user, "assistant": assistant})
        del session.turns[:-self.max_turns]
        return session

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def size(self) -> int:
        return len(self._sessions)


def plan(query: str) -> list[str]:
    """Deterministic, bounded plan. No model is allowed to invent tool names."""
    if not isinstance(query, str) or not query.strip():
        raise ToolContractError("query must be non-empty")
    if re.search(r"\b[A-Z]\d{2,4}\b", query.upper()):
        return ["lookup_fault_code", "rag_retrieve"]
    return ["rag_retrieve", "search_manuals"]


def _citation_failure(answer: str, citations: list[dict]) -> str | None:
    markers = {int(value) for value in re.findall(r"\[S(\d+)\]", answer or "")}
    if not markers:
        return "missing_citation_marker"
    if any(value < 1 or value > len(citations) for value in markers):
        return "citation_out_of_range"
    return None


def _answer_prompt(query: str, evidence: str, history_text: str, retry: bool = False) -> str:
    retry_instruction = (
        "Your previous draft failed citation validation. Rewrite it and include at least one valid citation marker."
        if retry else ""
    )
    return f"""You are a constrained manual assistant.
Use only the Manual evidence below; do not invent facts.
Every factual sentence must end with an ASCII citation marker such as [S1] or [S2].
When answering in Chinese, preserve these ASCII citation markers exactly.
Do not output a Markdown code block.
Example: BX-9 的 E42 表示电机绕组温度超过安全限制。[S1]
{retry_instruction}

Manual evidence:
{evidence}

{history_text}
Current question: {query}
Answer:"""


def run_agent(query: str, session_id: str, tools: ReadOnlyTools, retrieve: Callable[[str], dict], generate: Callable[[str, list[dict]], str], sessions: SessionStore) -> dict:
    steps = plan(query)
    if len(steps) > MAX_STEPS:
        raise ToolContractError("agent step budget exceeded")
    tool_results = []
    for step in steps:
        if step == "lookup_fault_code":
            match = re.search(r"\b([A-Z]{1,5}-\d{1,4})\b", query.upper()); code = re.search(r"\b([A-Z]\d{2,4})\b", query.upper())
            tool_results.append({"step": step, "result": tools.lookup_fault_code(match.group(1), code.group(1))})
        elif step == "search_manuals":
            terms = [word for word in re.findall(r"[A-Za-z]{4,}", query)][:1]
            tool_results.append({"step": step, "result": tools.search_manuals(terms[0] if terms else query[:32])})
        elif step == "rag_retrieve":
            tool_results.append({"step": step, "result": retrieve(query)})
    retrieval = next((item["result"] for item in tool_results if item["step"] == "rag_retrieve"), None)
    citations = retrieval.get("citations", []) if retrieval else []
    if not retrieval or not retrieval.get("answerable") or not retrieval.get("results"):
        return {"schema_version": 1, "milestone": MILESTONE, "status": "NO_EVIDENCE", "session_id": session_id, "answer": None, "citations": [], "plan": steps, "tool_audit": tools.audit[-len(steps):], "retry_count": 0, "citation_failure_reason": None}
    evidence = "\n\n".join(f"[S{index}] {item['text']}" for index, item in enumerate(retrieval["results"], 1))
    history = sessions.get(session_id).turns
    history_text = "\n".join(f"Previous user: {turn['user']}\nPrevious answer: {turn['assistant']}" for turn in history[-3:])
    answer = generate(_answer_prompt(query, evidence, history_text), citations)
    failure = _citation_failure(answer, citations)
    retry_count = 0
    if failure:
        retry_count = 1
        answer = generate(_answer_prompt(query, evidence, history_text, retry=True), citations)
        failure = _citation_failure(answer, citations)
    if failure:
        return {"schema_version": 1, "milestone": MILESTONE, "status": "CITATION_FORMAT_ERROR", "session_id": session_id, "answer": answer, "citations": citations, "plan": steps, "tool_audit": tools.audit[-len(steps):], "session_turns": len(sessions.get(session_id).turns), "retry_count": retry_count, "citation_failure_reason": failure}
    sessions.append(session_id, query, answer)
    return {"schema_version": 1, "milestone": MILESTONE, "status": "OK", "session_id": session_id, "answer": answer, "citations": citations, "plan": steps, "tool_audit": tools.audit[-len(steps):], "session_turns": len(sessions.get(session_id).turns), "retry_count": retry_count, "citation_failure_reason": None}


class JsonlAgent:
    """Long-lived JSONL facade; all state is deliberately process-local."""

    def __init__(self, tools: ReadOnlyTools, sessions: SessionStore, retrieve: Callable[[str], dict], generate: Callable[[str, list[dict]], str], tool_version: str = "m10.2-readonly-tools-v1"):
        self.tools, self.sessions, self.retrieve, self.generate = tools, sessions, retrieve, generate
        self.tool_version = tool_version
        self.request_ids: set[str] = set()

    @staticmethod
    def _required_string(value: Any, name: str, maximum: int | None = None) -> str:
        if not isinstance(value, str) or not value.strip() or (maximum is not None and len(value) > maximum):
            limit = f" of at most {maximum} characters" if maximum else ""
            raise ToolContractError(f"{name} must be a non-empty string{limit}")
        return value

    def handle(self, request: dict) -> dict:
        started = time.monotonic()
        request_id = request.get("request_id") if isinstance(request, dict) else None
        session_id = request.get("session_id") if isinstance(request, dict) else None
        op = request.get("op") if isinstance(request, dict) else None
        base = {"schema_version": 1, "milestone": MILESTONE, "request_id": request_id, "session_id": session_id, "op": op}
        plan_value, audit, turns, status = [], [], 0, "ERROR"
        audit_start = len(self.tools.audit)
        response = None
        try:
            if not isinstance(request, dict): raise ToolContractError("request must be a JSON object")
            request_id = self._required_string(request_id, "request_id")
            if request_id in self.request_ids: raise ToolContractError("request_id must be unique")
            self.request_ids.add(request_id)
            if op not in {"answer", "reset", "health"}: raise ToolContractError("unknown op")
            if op in {"answer", "reset"}:
                session_id = self._required_string(session_id, "session_id", 128)
            if op == "health":
                status = "OK"
                response = {**base, "status": status, "sessions": self.sessions.size(), "capacity": self.sessions.max_sessions, "tool_version": self.tool_version}
            elif op == "reset":
                self.sessions.reset(session_id); status = "OK"; turns = 0
                response = {**base, "status": status, "session_turns": turns}
            else:
                query = self._required_string(request.get("query"), "query", 4096)
                plan_value = plan(query)
                result = run_agent(query, session_id, self.tools, self.retrieve, self.generate, self.sessions)
                plan_value, audit, turns, status = result.get("plan", []), result.get("tool_audit", []), result.get("session_turns", 0), result["status"]
                response = {**base, **result, "request_id": request_id, "session_id": session_id, "op": op}
        except (ToolContractError, OSError, ValueError, KeyError, RuntimeError) as error:
            audit = self.tools.audit[audit_start:]
            response = {**base, "status": "ERROR", "error": str(error), "session_turns": turns}
        response.update({"request_id": request_id, "session_id": session_id, "op": op, "plan": plan_value, "tool_audit": audit, "session_turns": turns, "status": response.get("status", status), "elapsed_ms": round((time.monotonic() - started) * 1000)})
        return response

    def serve(self, stream_in, stream_out) -> None:
        for line in stream_in:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                response = self.handle(request)
            except (json.JSONDecodeError, TypeError, ValueError, RuntimeError) as error:
                response = {"schema_version": 1, "milestone": MILESTONE, "status": "ERROR", "error": str(error)}
            stream_out.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream_out.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query")
    parser.add_argument("--session-id")
    parser.add_argument("--jsonl", action="store_true", help="serve one JSON response per JSONL request")
    parser.add_argument("--config", default="configs/rag-vlm-m9.2.json")
    parser.add_argument("--request-id")
    args = parser.parse_args()
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import rag_vlm_m9_2 as m92
        config = m92.load_config(m92.repo_path(args.config))
        retrieval_config = json.loads(m92.repo_path(config["retrieval_config"]).read_text(encoding="utf-8"))
        embedding_config = m92.load_embedding_config(m92.repo_path(config["embedding_config"]))
        provider = m92.provider_from_config(embedding_config)
        tools = ReadOnlyTools()
        sessions = SessionStore()
        def retrieve(query: str) -> dict:
            return m92.query_index(m92.repo_path(config["database"]), query, retrieval_config["retrieval"]["top_k"], provider, retrieval_config["retrieval"])
        def generate(prompt: str, citations: list[dict]) -> str:
            body, _ = m92.call_model(config["model_endpoint"], f"agent-m10.2-{time.time_ns()}", prompt, config["max_new_tokens"], config["timeout_seconds"])
            if body is None:
                raise ToolContractError("model generation failed")
            return body["text"]
        server = JsonlAgent(tools, sessions, retrieve, generate)
        if args.jsonl:
            server.serve(sys.stdin, sys.stdout)
            return 0
        if not args.query or not args.session_id:
            raise ToolContractError("--query and --session-id are required outside --jsonl")
        request_id = args.request_id or f"agent-m10.2-{int(time.time() * 1000)}"
        result = server.handle({"request_id": request_id, "op": "answer", "session_id": args.session_id, "query": args.query})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"OK", "NO_EVIDENCE"} else 2
    except (ToolContractError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"schema_version": 1, "milestone": MILESTONE, "status": "ERROR", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
