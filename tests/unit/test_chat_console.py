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
        self.assertIn("[S1]", shown)
        self.assertIn("助手：回答结束。", shown)
        self.assertNotIn("tool_audit", shown)
        self.assertNotIn('"request_id"', shown)

    def test_general_mode_sends_explain_and_notice_once(self):
        console, holder, output = self.make_console(
            [{"status": "OK", "answer": "空化是气泡形成和破裂的现象。", "citations": [], "mode": "general-explanation"}],
            ["/mode general", "什么是空化？", "/quit"])
        console.run()
        self.assertEqual(self.requests(holder["process"])[0]["op"], "explain")
        self.assertEqual(output.getvalue().count("非设备手册结论"), 1)
        self.assertNotIn("citations", output.getvalue())

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


if __name__ == "__main__":
    unittest.main()
