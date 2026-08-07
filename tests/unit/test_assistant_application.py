import io
import base64
import json
import pathlib
import tempfile
import unittest
import urllib.error
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]

from app.agent.service import AgentApplication, JsonlAgent, ReadOnlyTools, SessionStore, build_application
from app.assistant import application as assistant
from app.audio.voice_gateway import HalfDuplexGateway, InProcessAgentClient
from app.ui.chat_console import ChatConsole


class AssistantApplicationTest(unittest.TestCase):
    def make_agent(self):
        retrieval = {"answerable": True, "results": [{"text": "fact"}], "citations": [{"chunk_id": "x"}]}
        return AgentApplication(ReadOnlyTools(), SessionStore(), lambda _: retrieval, lambda *_: "fact [S1]")

    def test_jsonl_delegates_to_same_core(self):
        core = self.make_agent()
        facade = JsonlAgent(application=core)
        self.assertIs(facade.application, core)
        result = facade.handle({"request_id": "one", "op": "answer", "session_id": "same", "query": "fact"})
        self.assertEqual((result["status"], core.sessions.size()), ("OK", 1))

    def test_in_process_adapter_and_half_duplex_share_session_without_tts_when_disabled(self):
        calls, events = [], []
        class Core:
            def handle(self, request):
                calls.append(request)
                return {"status": "OK", "answer": "fact [S1]", "citations": [{"id": "S1"}]}
        class Audio:
            def record(self, *_): events.append("record"); return b"pcm"
            def play(self, *_): self.fail("TTS must be disabled")
        class Asr:
            def transcribe(self, _): return "heard"
        class Tts:
            def synthesize(self, _): self.fail("TTS must be disabled")
        result = HalfDuplexGateway({"max_record_seconds": 1, "silence_timeout_seconds": 1, "session_id": "console-session", "tts_sample_rate": 8000}, InProcessAgentClient(Core()), Audio(), Asr(), Tts(), speak=False).run_turn("listen-1")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(calls[0], {"request_id": "listen-1", "op": "answer", "session_id": "console-session", "query": "heard"})

    def test_console_speak_switch_and_listen_do_not_play_when_off(self):
        requests, spoken = [], []
        class Agent:
            def request(self, payload):
                requests.append(payload)
                return {"status": "OK", "answer": "answer [S1]"}
            def close(self): pass
        def listen(request_id):
            return {"status": "OK", "text": "heard", "answer": "voice [S1]"}
        output = io.StringIO()
        console = ChatConsole(Agent(), io.StringIO("/speak on\ntext\n/speak off\n/listen\n/quit\n"), output,
                              session_id="same", request_id_factory=iter(["r1", "r2"]).__next__, speaker=spoken.append,
                              listener=listen)
        console.run()
        self.assertEqual(spoken, ["answer [S1]"])
        self.assertEqual(requests[0]["session_id"], "same")
        self.assertIn("你：heard", output.getvalue())

    def test_runtime_and_rag_preflight_have_explicit_success_and_failure(self):
        config = assistant.load_config()
        self.assertEqual(config["_manual"]["database"], config["rag"]["database"])
        self.assertEqual(config["_manual"]["model_endpoint"], config["runtime"]["base_url"] + config["runtime"]["chat_endpoint"])
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return b'{"ready": true}'
        assistant.check_runtime(config, lambda *_args, **_kwargs: Response())
        assistant.check_rag(config)
        with self.assertRaisesRegex(assistant.AssistantPreflightError, "Runtime readiness failed"):
            assistant.check_runtime(config, lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")))
        bad = dict(config, _manual={**config["_manual"], "database": "missing.sqlite3"})
        with self.assertRaisesRegex(assistant.AssistantPreflightError, "RAG SQLite database is missing"):
            assistant.check_rag(bad)

    def test_diagnose_image_posts_non_streaming_fixture_with_default_and_custom_prompts(self):
        config = assistant.load_config()
        application = assistant.AssistantApplication(config, object())
        image_path = "tests/fixtures/vlm-service/synthetic-alarm-panel.png"
        image_bytes = (ROOT / image_path).read_bytes()
        requests = []

        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return b'{"text":"diagnosis"}'

        def urlopen(request, timeout):
            requests.append((request, timeout))
            return Response()

        first = application.diagnose_image(image_path, None, None, urlopen)
        second = application.diagnose_image(image_path, "检查告警灯", None, urlopen)
        self.assertEqual((first["text"], second["text"]), ("diagnosis", "diagnosis"))
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0][0].full_url, "http://127.0.0.1:18086/v1/diagnose/image")
        self.assertEqual(requests[0][1], 120)
        payloads = [json.loads(item[0].data) for item in requests]
        self.assertNotEqual(payloads[0]["request_id"], payloads[1]["request_id"])
        self.assertEqual(payloads[0]["prompt"], assistant.DEFAULT_IMAGE_PROMPT)
        self.assertEqual(payloads[1]["prompt"], "检查告警灯")
        for payload in payloads:
            self.assertFalse(payload["stream"])
            self.assertEqual(payload["images"][0]["mime"], "image/png")
            self.assertEqual(base64.b64decode(payload["images"][0]["data_base64"]), image_bytes)

    def test_diagnose_image_rejects_unsafe_and_invalid_local_assets(self):
        config = assistant.load_config()
        application = assistant.AssistantApplication(config, object())
        with self.assertRaisesRegex(assistant.AssistantImageError, "相对"):
            application.diagnose_image("../README.md", "问题", "one", lambda *_: None)
        with self.assertRaisesRegex(assistant.AssistantImageError, "无法读取"):
            application.diagnose_image("tests/fixtures/vlm-service/missing.png", "问题", "two", lambda *_: None)

        with tempfile.TemporaryDirectory() as temp:
            workspace = pathlib.Path(temp)
            root = workspace / "repo"
            root.mkdir()
            outside = workspace / "outside.png"
            outside.write_bytes(b"outside")
            (root / "escape.png").symlink_to(outside)
            with mock.patch.object(assistant, "ROOT", root):
                with self.assertRaisesRegex(assistant.AssistantImageError, "符号链接"):
                    assistant._read_image("escape.png")
                (root / "plain.png").write_text("not an image", encoding="utf-8")
                with self.assertRaisesRegex(assistant.AssistantImageError, "不受支持"):
                    assistant._read_image("plain.png")
                (root / "fake.png").write_bytes(b"not an image")
                with self.assertRaisesRegex(assistant.AssistantImageError, "不受支持"):
                    assistant._read_image("fake.png")
                (root / "large.jpg").write_bytes(b"\xff\xd8\xff" + b"x" * assistant.MAX_DIAGNOSIS_IMAGE_BYTES)
                with self.assertRaisesRegex(assistant.AssistantImageError, "10 MiB"):
                    assistant._read_image("large.jpg")

    def test_diagnose_image_reports_http_and_json_failures_without_exposing_payload(self):
        application = assistant.AssistantApplication(assistant.load_config(), object())
        image_path = "tests/fixtures/vlm-service/synthetic-device-panel.png"
        with self.assertRaisesRegex(assistant.AssistantImageError, "上游拒绝"):
            def http_error(request, timeout):
                body = '{"error":{"message":"上游拒绝"}}'.encode("utf-8")
                raise urllib.error.HTTPError(request.full_url, 400, "bad", {}, io.BytesIO(body))
            application.diagnose_image(image_path, "问题", "http-error", http_error)
        class InvalidResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return b"not-json"
        with self.assertRaisesRegex(assistant.AssistantImageError, "无效.*JSON"):
            application.diagnose_image(image_path, "问题", "bad-json", lambda *_args, **_kwargs: InvalidResponse())

    def test_shared_bindings_reject_path_traversal(self):
        module = {"schema_version": 2, "milestone": "M9.2-PROTOTYPE", "retrieval_config": "configs/manual-retrieval.json", "embedding_config": "configs/embedding.json", "max_new_tokens": 1, "timeout_seconds": 1}
        with self.assertRaisesRegex(ValueError, "repository-relative"):
            assistant.manual_qa.bind_runtime(module, "generated/../outside.sqlite3", "http://127.0.0.1:18086/v1/chat")

    def test_manual_and_general_use_separate_system_prompts(self):
        retrieval = {"answerable": True, "results": [{"text": "manual fact"}], "citations": [{"id": "S1"}]}
        calls = []
        def model(endpoint, request_id, prompt, max_tokens, timeout, system_prompt):
            calls.append(system_prompt)
            answer = "manual fact [S1]" if system_prompt == assistant.manual_qa.MANUAL_GROUNDED_SYSTEM_PROMPT else "一般概念 [S1]"
            return {"text": answer}, {"http_status": 200}
        config = {"database": "generated/rag-m9.1b-r2.2/hybrid.sqlite3", "model_endpoint": "http://127.0.0.1:18086/v1/chat", "max_new_tokens": 8, "timeout_seconds": 1}
        retrieval_config = {"retrieval": {"top_k": 1}}
        with mock.patch.object(assistant.manual_qa, "query_index", return_value=retrieval), \
             mock.patch.object(assistant.manual_qa, "call_model", side_effect=model):
            application = build_application(config, retrieval_config, object())
            manual = application.handle({"request_id": "manual", "op": "answer", "session_id": "s", "query": "fact"})
            general = application.handle({"request_id": "general", "op": "explain", "session_id": "s", "query": "什么是空化？"})
        self.assertEqual(manual["status"], "OK")
        self.assertEqual(general["status"], "OK")
        self.assertEqual(calls, [assistant.manual_qa.MANUAL_GROUNDED_SYSTEM_PROMPT, assistant.manual_qa.GENERAL_EXPLANATION_SYSTEM_PROMPT])
        self.assertNotIn("[S1]", general["answer"])

    def test_audio_preflight_success_and_failure_are_lazy_and_explicit(self):
        config = assistant.load_config()
        with mock.patch.object(assistant.voice_gateway, "load_config", return_value={"voice": True}), \
             mock.patch.object(assistant.voice_gateway, "build_tts_backends", return_value=(object(), object(), object(), object())), \
             mock.patch.object(assistant.voice_gateway, "build_asr_backends", return_value=(object(), object())), \
             mock.patch.object(assistant.voice_gateway, "check_output_device"), \
             mock.patch.object(assistant.voice_gateway, "check_input_device"):
            self.assertEqual(assistant.check_tts(config), {"voice": True})
            self.assertEqual(assistant.check_listen(config), {"voice": True})
        with mock.patch.object(assistant.voice_gateway, "load_config", side_effect=assistant.voice_gateway.AudioGatewayError("asset hash mismatch")):
            with self.assertRaisesRegex(assistant.AssistantPreflightError, "TTS/output preflight failed"):
                assistant.check_tts(config)

    def test_run_console_uses_in_process_adapter_and_prewarms_tts_without_asr(self):
        fake_config = assistant.load_config()
        class FakeAssistant:
            agent = object()
            def diagnose_image(self, *_args, **_kwargs): return {"text": "unused"}
        with mock.patch.object(assistant, "load_config", return_value=fake_config), \
             mock.patch.object(assistant, "check_runtime"), mock.patch.object(assistant, "check_rag"), \
             mock.patch.object(assistant.AssistantApplication, "create", return_value=FakeAssistant()), \
             mock.patch.object(assistant, "check_tts", return_value=({"voice": True}, object(), object())) as check_tts, \
             mock.patch("app.ui.chat_console.ChatConsole.run"), \
             mock.patch("subprocess.Popen") as popen:
            assistant.run_console(speak=True)
        popen.assert_not_called()
        check_tts.assert_called_once()


if __name__ == "__main__":
    unittest.main()
