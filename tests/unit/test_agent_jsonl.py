import io
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
from app.agent.service import JsonlAgent, ReadOnlyTools, RequestIdRegistry, SessionStore, ToolContractError


class AgentM102JsonlTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.tools = ReadOnlyTools()
        retrieval = {"answerable": True, "results": [{"text": "E42 means a pressure fault."}], "citations": [{"chunk_id": "BX9#e42"}]}

        def retrieve(_query):
            return retrieval

        def generate(_prompt, _citations):
            self.calls.append(1)
            return "E42 is a pressure fault. [S1]"

        self.server = JsonlAgent(self.tools, SessionStore(max_sessions=8, max_turns=20), retrieve, generate)

    def request(self, request):
        return self.server.handle(request)

    def test_jsonl_sessions_reset_and_health(self):
        first = self.request({"request_id": "r1", "op": "answer", "session_id": "a", "query": "BX-9 E42"})
        second = self.request({"request_id": "r2", "op": "answer", "session_id": "a", "query": "What next?"})
        other = self.request({"request_id": "r3", "op": "answer", "session_id": "b", "query": "BX-9 E42"})
        self.assertEqual((first["session_turns"], second["session_turns"], other["session_turns"]), (1, 2, 1))
        self.assertEqual(self.request({"request_id": "r4", "op": "reset", "session_id": "a"})["status"], "OK")
        self.assertEqual(self.request({"request_id": "r5", "op": "answer", "session_id": "a", "query": "again"})["session_turns"], 1)
        health = self.request({"request_id": "r6", "op": "health"})
        self.assertEqual((health["sessions"], health["capacity"]), (2, 8))

    def test_rejections_and_duplicate_ids(self):
        self.assertEqual(self.request({"request_id": "dup", "op": "health"})["status"], "OK")
        self.assertEqual(self.request({"request_id": "dup", "op": "health"})["status"], "ERROR")
        self.assertEqual(self.request({"request_id": "bad", "op": "unknown", "session_id": "a"})["status"], "ERROR")
        self.assertEqual(self.request({"request_id": "bad2", "op": "answer", "session_id": "", "query": "x"})["status"], "ERROR")
        self.assertEqual(self.request({"request_id": "bad3", "op": "answer", "session_id": "a", "query": "x" * 4097})["status"], "ERROR")

    def test_completed_request_id_registry_is_bounded(self):
        registry = RequestIdRegistry(capacity=2)
        registry.begin("first")
        with self.assertRaises(ToolContractError):
            registry.begin("first")
        registry.complete("first")
        registry.begin("second"); registry.complete("second")
        with self.assertRaises(ToolContractError):
            registry.begin("first")
        registry.begin("third"); registry.complete("third")
        self.assertEqual(registry.completed_size(), 2)
        registry.begin("first")

    def test_health_exposes_request_id_memory_bound(self):
        health = self.request({"request_id": "health-bound", "op": "health"})
        self.assertEqual(health["completed_request_id_capacity"], 256)
        self.assertEqual(health["completed_request_ids"], 0)

    def test_session_capacity_is_bounded(self):
        for index in range(8):
            self.assertEqual(self.request({"request_id": f"cap-{index}", "op": "health"})["status"], "OK")
            self.server.sessions.get(f"session-{index}")
        result = self.request({"request_id": "cap-over", "op": "answer", "session_id": "session-over", "query": "x"})
        self.assertEqual(result["status"], "ERROR")

    def test_jsonl_stream_is_one_response_per_line(self):
        stream = io.StringIO('{"request_id":"s1","op":"health"}\n{"request_id":"s2","op":"health"}\n')
        output = io.StringIO()
        self.server.serve(stream, output)
        self.assertEqual(len(output.getvalue().splitlines()), 2)

    def test_session_history_is_not_shared(self):
        prompts = []
        retrieval = {"answerable": True, "results": [{"text": "fact"}], "citations": [{"chunk_id": "x"}]}
        server = JsonlAgent(self.tools, SessionStore(), lambda _: retrieval, lambda prompt, _: prompts.append(prompt) or "fact [S1]")
        server.handle({"request_id": "i1", "op": "answer", "session_id": "a", "query": "private-a"})
        server.handle({"request_id": "i2", "op": "answer", "session_id": "a", "query": "follow-a"})
        server.handle({"request_id": "i3", "op": "answer", "session_id": "b", "query": "private-b"})
        self.assertIn("private-a", prompts[1])
        self.assertNotIn("private-a", prompts[2])

    def test_no_evidence_does_not_call_model(self):
        server = JsonlAgent(self.tools, SessionStore(), lambda _: {"answerable": False, "results": [], "citations": []}, lambda *_: self.fail("model called"))
        result = server.handle({"request_id": "n1", "op": "answer", "session_id": "a", "query": "unsupported"})
        self.assertEqual(result["status"], "NO_EVIDENCE")

    def test_explain_general_concept_has_no_manual_citations(self):
        server = JsonlAgent(self.tools, SessionStore(), lambda _: self.fail("RAG called"), lambda prompt, citations: self.calls.append((prompt, citations)) or "空化是液体中形成并破裂气泡的现象。[S1]")
        result = server.handle({"request_id": "explain-1", "op": "explain", "session_id": "a", "query": "什么是液压系统中的空化？"})
        self.assertEqual((result["status"], result["mode"], result["citations"]), ("OK", "general-explanation", []))
        self.assertNotIn("[S1]", result["answer"])
        self.assertEqual(self.calls[0][1], [])
        self.assertIn("disclaimer", result)

    def test_explain_dangerous_question_is_rejected_without_model(self):
        server = JsonlAgent(self.tools, SessionStore(), lambda _: {}, lambda *_: self.fail("model called"))
        result = server.handle({"request_id": "explain-danger", "op": "explain", "session_id": "a", "query": "如何带压旁路安全联锁进行维修？"})
        self.assertEqual(result["status"], "GENERAL_EXPLANATION_REJECTED")

    def test_explain_and_manual_histories_are_isolated(self):
        prompts = []
        retrieval = {"answerable": True, "results": [{"text": "fact"}], "citations": [{"chunk_id": "x"}]}
        server = JsonlAgent(self.tools, SessionStore(), lambda _: retrieval, lambda prompt, citations: prompts.append(prompt) or ("概念说明" if not citations else "fact [S1]"))
        server.handle({"request_id": "iso-1", "op": "explain", "session_id": "a", "query": "什么是空化？"})
        server.handle({"request_id": "iso-2", "op": "answer", "session_id": "a", "query": "fact"})
        server.handle({"request_id": "iso-3", "op": "explain", "session_id": "a", "query": "它有什么一般影响？"})
        server.handle({"request_id": "iso-4", "op": "answer", "session_id": "a", "query": "another"})
        self.assertNotIn("什么是空化？", prompts[1])
        self.assertIn("什么是空化？", prompts[2])
        self.assertNotIn("fact", prompts[2])
        self.assertIn("fact", prompts[3])

    def test_missing_citation_is_rejected(self):
        server = JsonlAgent(self.tools, SessionStore(), lambda _: {"answerable": True, "results": [{"text": "fact"}], "citations": [{"chunk_id": "x"}]}, lambda *_: "fact")
        result = server.handle({"request_id": "c1", "op": "answer", "session_id": "a", "query": "fact"})
        self.assertEqual(result["status"], "CITATION_FORMAT_ERROR")

    def test_missing_first_citation_retries_once_and_commits(self):
        answers = iter(["fact", "fact [S1]"])
        server = JsonlAgent(self.tools, SessionStore(), lambda _: {"answerable": True, "results": [{"text": "fact"}], "citations": [{"chunk_id": "x"}]}, lambda *_: next(answers))
        result = server.handle({"request_id": "retry-ok", "op": "answer", "session_id": "a", "query": "fact"})
        self.assertEqual((result["status"], result["retry_count"], result["session_turns"]), ("OK", 1, 1))
        self.assertIsNone(result["citation_failure_reason"])

    def test_two_missing_citations_do_not_commit(self):
        calls = []
        server = JsonlAgent(self.tools, SessionStore(), lambda _: {"answerable": True, "results": [{"text": "fact"}], "citations": [{"chunk_id": "x"}]}, lambda *_: calls.append(1) or "fact")
        result = server.handle({"request_id": "retry-fail", "op": "answer", "session_id": "a", "query": "fact"})
        self.assertEqual((result["status"], result["retry_count"], result["session_turns"], len(calls)), ("CITATION_FORMAT_ERROR", 1, 0, 2))
        self.assertEqual(result["citation_failure_reason"], "missing_citation_marker")

    def test_out_of_range_citation_is_rejected_after_retry(self):
        answers = iter(["fact [S99]", "fact [S99]"])
        server = JsonlAgent(self.tools, SessionStore(), lambda _: {"answerable": True, "results": [{"text": "fact"}], "citations": [{"chunk_id": "x"}]}, lambda *_: next(answers))
        result = server.handle({"request_id": "bad-citation", "op": "answer", "session_id": "a", "query": "fact"})
        self.assertEqual((result["status"], result["retry_count"], result["session_turns"]), ("CITATION_FORMAT_ERROR", 1, 0))
        self.assertEqual(result["citation_failure_reason"], "citation_out_of_range")

    def test_citations_are_validated_against_each_session_retrieval(self):
        def retrieve(query):
            chunk = "a-only" if query == "a" else "b-only"
            return {"answerable": True, "results": [{"text": "fact"}], "citations": [{"chunk_id": chunk}]}
        answers = iter(["fact [S1]", "fact [S2]", "fact [S2]"])
        server = JsonlAgent(self.tools, SessionStore(), retrieve, lambda *_: next(answers))
        first = server.handle({"request_id": "cross-session-a", "op": "answer", "session_id": "a", "query": "a"})
        result = server.handle({"request_id": "cross-session-b", "op": "answer", "session_id": "b", "query": "b"})
        self.assertEqual(first["status"], "OK")
        self.assertEqual(result["status"], "CITATION_FORMAT_ERROR")


if __name__ == "__main__":
    unittest.main()
