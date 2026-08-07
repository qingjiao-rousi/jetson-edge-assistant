import io
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
from app.ui.chat_console import AgentProcess, ChatConsole


class FakeProcess:
    def __init__(self, responses):
        self.stdin = CaptureStream()
        self.stdout = io.StringIO("".join(json.dumps(value, ensure_ascii=False) + "\n" for value in responses))
        self.stderr = io.StringIO()
        self.terminated = False
        self.waited = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = True


class CaptureStream(io.StringIO):
    def close(self):
        pass


class ChatConsoleM12Test(unittest.TestCase):
    def make_console(self, responses, lines):
        holder = {}
        def popen(*args, **kwargs):
            holder["process"] = FakeProcess(responses)
            return holder["process"]
        agent = AgentProcess(popen=popen)
        output = io.StringIO()
        console = ChatConsole(agent, io.StringIO("\n".join(lines) + "\n"), output,
                              session_id="session-fixed", request_id_factory=iter(["r1", "r2", "r3", "r4"]).__next__)
        return console, holder, output

    def requests(self, process):
        return [json.loads(line) for line in process.stdin.getvalue().splitlines()]

    def test_default_manual_sends_answer_and_hides_metadata(self):
        console, holder, output = self.make_console(
            [{"status": "OK", "answer": "压力是 18 MPa。[S1]", "citations": [{"id": "x"}], "tool_audit": [{"tool": "search_manuals"},], "request_id": "r1"}],
            ["设备压力是多少？", "/quit"])
        console.run()
        request = self.requests(holder["process"])[0]
        self.assertEqual((request["op"], request["session_id"], request["query"]), ("answer", "session-fixed", "设备压力是多少？"))
        shown = output.getvalue()
        self.assertIn("EdgeOmni [manual] > ", shown)
        self.assertIn("[S1]", shown)
        self.assertIn("─" * 40, shown)
        self.assertNotIn("助手：", shown)
        self.assertNotIn("tool_audit", shown)
        self.assertNotIn('"request_id"', shown)

    def test_general_mode_sends_explain_and_notice_once(self):
        console, holder, output = self.make_console(
            [{"status": "OK", "answer": "空化是气泡形成和破裂的现象。", "citations": [], "mode": "general-explanation"}],
            ["/mode general", "什么是空化？", "/quit"])
        console.run()
        self.assertEqual(self.requests(holder["process"])[0]["op"], "explain")
        self.assertEqual(output.getvalue().count("不构成设备手册结论"), 1)
        self.assertNotIn("citations", output.getvalue())
        self.assertIn("EdgeOmni [general] > ", output.getvalue())

    def test_reset_uses_same_session_and_non_ok_is_friendly(self):
        console, holder, output = self.make_console(
            [{"status": "NO_EVIDENCE"}, {"status": "OK", "session_turns": 0}],
            ["没有依据的问题", "/reset", "/quit"])
        console.run()
        requests = self.requests(holder["process"])
        self.assertEqual([item["op"] for item in requests], ["answer", "reset"])
        self.assertEqual({item["session_id"] for item in requests}, {"session-fixed"})
        self.assertIn("没有找到足够依据", output.getvalue())
        self.assertNotIn("NO_EVIDENCE", output.getvalue())

    def test_quit_closes_agent_without_request(self):
        console, holder, output = self.make_console([], ["/quit"])
        console.run()
        self.assertEqual(holder["process"].stdin.getvalue(), "")
        self.assertTrue(holder["process"].terminated)
        self.assertTrue(holder["process"].waited)

    def test_tts_failure_keeps_text_session_running_and_disables_tts(self):
        responses = [{"status": "OK", "answer": "first [S1]"}, {"status": "OK", "answer": "second [S1]"}]
        console, holder, output = self.make_console(responses, ["one", "two", "/quit"])
        console.speaker = lambda _: (_ for _ in ()).throw(RuntimeError("TTS unavailable"))
        console.speak = True
        console.run()
        self.assertFalse(console.speak)
        self.assertEqual([request["query"] for request in self.requests(holder["process"])], ["one", "two"])
        self.assertEqual(output.getvalue().count("语音输出不可用，已继续文本对话。"), 1)

    def test_image_command_uses_shlex_path_and_shows_unfused_diagnosis(self):
        calls = []
        class Agent:
            def close(self): pass
        def diagnose(path, prompt, request_id):
            calls.append((path, prompt, request_id))
            return {"text": "面板显示告警。"}
        output = io.StringIO()
        console = ChatConsole(Agent(), io.StringIO('/image "tests/fixtures/vlm-service/synthetic-alarm-panel.png" 检查 告警\n/quit\n'), output,
                              request_id_factory=iter(["image-request"]).__next__, image_diagnoser=diagnose)
        console.run()
        self.assertEqual(calls, [("tests/fixtures/vlm-service/synthetic-alarm-panel.png", "检查 告警", "image-request")])
        self.assertIn("图像诊断，未经过 RAG 检索或引用校验", output.getvalue())
        self.assertIn("面板显示告警", output.getvalue())

    def test_image_command_uses_default_prompt_and_reports_usage_or_callback_errors(self):
        calls = []
        class Agent:
            def close(self): pass
        def diagnose(path, prompt, request_id):
            calls.append((path, prompt, request_id))
            raise RuntimeError("图片读取失败")
        output = io.StringIO()
        console = ChatConsole(Agent(), io.StringIO('/image tests/fixtures/vlm-service/synthetic-device-panel.png\n/image\n/quit\n'), output,
                              request_id_factory=iter(["image-request"]).__next__, image_diagnoser=diagnose)
        console.run()
        self.assertEqual(calls[0], ("tests/fixtures/vlm-service/synthetic-device-panel.png", None, "image-request"))
        self.assertIn("图像诊断失败：图片读取失败", output.getvalue())
        self.assertIn("用法：/image <仓库内相对图片路径> [可选问题]", output.getvalue())


if __name__ == "__main__":
    unittest.main()
