import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
from app.qa import manual_qa as M
from app.assistant.application import load_config as load_assistant_config


class RagVlmPrototypeTest(unittest.TestCase):
    def setUp(self):
        self.config = load_assistant_config()["_manual"]
        self.retrieved = {"answerable": True, "admission": {"passed": True, "reasons": []}, "constraints": {}, "results": [{"chunk_id": "BX9-MANUAL-001#pressure", "heading": "Outlet Pressure", "text": "Normal outlet pressure is 2 MPa.", "citation": {"document_id": "BX9-MANUAL-001", "source_path": "knowledge/manuals/bx9-hydraulic-pump-manual.md"}}]}

    def test_prompt_and_response_keep_retrieval_citations(self):
        calls = []
        def retrieval(*_): return self.retrieved
        def model(endpoint, request_id, prompt, *_):
            calls.append((endpoint, request_id, prompt)); return {"request_id": request_id, "text": "The pressure is 2 MPa [S1].", "finish_reason": "stop", "metrics": {}}, {"endpoint": endpoint, "request_id": request_id, "http_status": 200}
        result = M.answer_query("What is BX-9 outlet pressure?", self.config, "test-request", provider=object(), retrieval_fn=retrieval, model_call=model)
        self.assertEqual(result["status"], "OK"); self.assertEqual(result["citations"][0]["id"], "S1")
        self.assertIn("[S1] chunk_id: BX9-MANUAL-001#pressure", calls[0][2]); self.assertIn("2 MPa", calls[0][2])

    def test_no_evidence_does_not_call_model(self):
        def retrieval(*_): return {"answerable": False, "admission": {"passed": False, "reasons": ["missing_core_fact_family"]}, "constraints": {}, "results": []}
        def model(*_): self.fail("model must not be called without retrieval evidence")
        result = M.answer_query("unsupported question", self.config, provider=object(), retrieval_fn=retrieval, model_call=model)
        self.assertEqual(result["status"], "NO_EVIDENCE"); self.assertFalse(result["model"]["called"]); self.assertEqual(result["citations"], [])

    def test_model_failure_is_structured_and_keeps_citations(self):
        def retrieval(*_): return self.retrieved
        def model(endpoint, request_id, *_): return None, {"endpoint": endpoint, "request_id": request_id, "http_status": 503, "error": "http_error"}
        result = M.answer_query("pressure", self.config, provider=object(), retrieval_fn=retrieval, model_call=model)
        self.assertEqual(result["status"], "MODEL_UNAVAILABLE"); self.assertTrue(result["model"]["called"]); self.assertEqual([x["id"] for x in result["citations"]], ["S1"])

    def test_bad_model_body_is_rejected(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return b'{"text": 1}'
        from unittest import mock
        with mock.patch("urllib.request.urlopen", return_value=Response()):
            response, metadata = M.call_model("http://test/v1/chat", "x", "prompt", 10, 1)
        self.assertIsNone(response); self.assertEqual(metadata["error"], "invalid_model_response")

    def test_call_model_accepts_an_explicit_system_prompt(self):
        captured = {}
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return b'{"text":"ok"}'
        def urlopen(request, **_kwargs):
            captured.update(json.loads(request.data.decode("utf-8")))
            return Response()
        from unittest import mock
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            response, _ = M.call_model("http://test/v1/chat", "x", "prompt", 10, 1, system_prompt="general system")
        self.assertEqual(response["text"], "ok")
        self.assertEqual(captured["messages"][0], {"role": "system", "content": "general system"})


if __name__ == "__main__":
    unittest.main()
