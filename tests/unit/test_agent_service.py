import pathlib, unittest
ROOT = pathlib.Path(__file__).resolve().parents[2]
from app.agent.service import ReadOnlyTools, SessionStore, ToolContractError, plan, run_agent


class AgentM102Test(unittest.TestCase):
    def setUp(self): self.tools = ReadOnlyTools(); self.sessions = SessionStore(max_sessions=2, max_turns=2)

    def test_read_tool_stays_inside_manual_root(self):
        result = self.tools.read_manual("knowledge/manuals/bx9-hydraulic-pump-manual.md")
        self.assertIn("nominal outlet pressure", result["text"])
        with self.assertRaises(ToolContractError): self.tools.read_manual("README.md")
        with self.assertRaises(ToolContractError): self.tools.read_manual("knowledge/manuals/../ax17-equipment-manual.md")

    def test_fault_lookup_and_audit(self):
        result = self.tools.lookup_fault_code("BX-9", "E42")
        self.assertTrue(result["found"]); self.assertEqual(result["results"][0]["chunk_id"], "BX9-MANUAL-001#alarm-e42")
        self.assertEqual(self.tools.audit[-1]["status"], "ok")

    def test_plan_is_bounded_and_deterministic(self):
        self.assertEqual(plan("What does E42 mean on BX-9?"), ["lookup_fault_code", "rag_retrieve"])
        self.assertEqual(plan("What is BX-9 pressure?"), ["rag_retrieve", "search_manuals"])

    def test_agent_preserves_citations_and_session_isolation(self):
        retrieval = {"answerable": True, "results": [{"text": "Outlet pressure is 18 MPa."}], "citations": [{"chunk_id": "BX9#spec"}]}
        result = run_agent("What is BX-9 pressure?", "s1", self.tools, lambda _: retrieval, lambda prompt, citations: "18 MPa [S1]", self.sessions)
        self.assertEqual(result["status"], "OK"); self.assertEqual(result["citations"], retrieval["citations"]); self.assertEqual(result["session_turns"], 1)
        self.assertEqual(self.sessions.size(), 1)

    def test_no_evidence_short_circuits_generation(self):
        called = []
        result = run_agent("unsupported", "s1", self.tools, lambda _: {"answerable": False, "results": [], "citations": []}, lambda *_: called.append(True), self.sessions)
        self.assertEqual(result["status"], "NO_EVIDENCE"); self.assertFalse(called); self.assertEqual(self.sessions.size(), 0)

    def test_session_capacity_and_reset(self):
        self.sessions.get("s1"); self.sessions.get("s2")
        with self.assertRaises(ToolContractError): self.sessions.get("s3")
        self.sessions.reset("s1"); self.sessions.get("s3"); self.assertEqual(self.sessions.size(), 2)


if __name__ == "__main__": unittest.main()
