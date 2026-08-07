#!/usr/bin/env python3
"""M12 standard-library terminal console for the local M10.2 JSONL Agent."""
from __future__ import annotations

import argparse
import json
import pathlib
import shlex
import subprocess
import sys
import time
import uuid
from typing import Any, Callable, TextIO

ROOT = pathlib.Path(__file__).resolve().parents[2]
AGENT_COMMAND = ["python3", "scripts/run_agent.py", "--jsonl"]
DIVIDER = "─" * 40


class ConsoleError(RuntimeError):
    pass


class AgentProcess:
    """One long-lived JSONL Agent process; its protocol never reaches the user."""

    def __init__(self, command: list[str] | None = None, popen: Callable[..., Any] = subprocess.Popen):
        self.process = popen(command or AGENT_COMMAND, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, bufsize=1, cwd=str(ROOT))
        if self.process.stdin is None or self.process.stdout is None:
            raise ConsoleError("Agent pipes unavailable")

    def request(self, payload: dict) -> dict:
        try:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
            if not line:
                raise ConsoleError("Agent exited without a response")
            response = json.loads(line)
            if not isinstance(response, dict):
                raise ConsoleError("Agent returned an invalid response")
            return response
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ConsoleError(f"Agent communication failed: {error}") from error

    def close(self) -> None:
        stdin = getattr(self.process, "stdin", None)
        if stdin is not None and not stdin.closed:
            stdin.close()
        terminate = getattr(self.process, "terminate", None)
        if terminate:
            terminate()
        wait = getattr(self.process, "wait", None)
        if wait:
            try:
                wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                kill = getattr(self.process, "kill", None)
                if kill:
                    kill()


def _friendly_response(response: dict, mode: str) -> str:
    status = response.get("status")
    if status == "OK":
        answer = response.get("answer")
        return answer if isinstance(answer, str) and answer else "助手未返回可显示的回答。"
    messages = {
        "NO_EVIDENCE": "本地手册中没有找到足够依据。",
        "GENERAL_EXPLANATION_REJECTED": "该问题涉及安全关键或操作性指导，通用解释模式不提供此类内容。",
        "CITATION_FORMAT_ERROR": "回答未通过手册引用校验，请换一种问法。",
    }
    return messages.get(status, "助手暂时无法回答该问题。")


class ChatConsole:
    def __init__(self, agent: Any, input_stream: TextIO = sys.stdin, output_stream: TextIO = sys.stdout,
                 session_id: str | None = None, request_id_factory: Callable[[], str] | None = None,
                 speaker: Callable[[str], None] | None = None, listener: Callable[[str], dict] | None = None,
                 speak: bool = False, image_diagnoser: Callable[[str, str | None, str], dict] | None = None):
        self.agent = agent
        self.input_stream = input_stream
        self.output_stream = output_stream
        self.session_id = session_id or f"m12-console-{uuid.uuid4().hex}"
        self.request_id_factory = request_id_factory or (lambda: f"m12-{time.time_ns()}-{uuid.uuid4().hex[:8]}")
        self.mode = "manual"
        self.speaker, self.listener, self.speak, self.image_diagnoser = speaker, listener, speak, image_diagnoser

    def _write(self, text: str) -> None:
        self.output_stream.write(text + "\n")
        self.output_stream.flush()

    def _prompt(self) -> None:
        label = "manual" if self.mode == "manual" else "general"
        self.output_stream.write(f"EdgeOmni [{label}] > ")
        self.output_stream.flush()

    def _result(self, text: str) -> None:
        self._write("")
        self._write(text)
        self._write("")
        self._write(DIVIDER)

    def _request(self, op: str, query: str | None = None) -> dict:
        payload = {"request_id": self.request_id_factory(), "op": op, "session_id": self.session_id}
        if query is not None:
            payload["query"] = query
        return self.agent.request(payload)

    def _show_response(self, response: dict) -> None:
        answer = _friendly_response(response, self.mode)
        self._result(answer)
        if response.get("status") == "OK":
            if self.speak and self.speaker is not None:
                try:
                    self.speaker(answer)
                except (OSError, RuntimeError, ValueError):
                    self.speak = False
                    self._result("语音输出不可用，已继续文本对话。")

    def handle_line(self, line: str) -> bool:
        text = line.strip()
        if not text:
            return True
        if text == "/quit":
            return False
        if text == "/reset":
            response = self._request("reset")
            self._result("会话已重置。" if response.get("status") == "OK" else "会话重置失败。")
            return True
        if text == "/image" or text.startswith("/image "):
            try:
                parts = shlex.split(text)
            except ValueError as error:
                self._result(f"图像诊断命令格式错误：{error}")
                return True
            if len(parts) < 2 or self.image_diagnoser is None:
                self._result("用法：/image <仓库内相对图片路径> [可选问题]。")
                return True
            image_path = parts[1]
            prompt = " ".join(parts[2:]) or None
            try:
                response = self.image_diagnoser(image_path, prompt, self.request_id_factory())
                self._result("图像诊断，未经过 RAG 检索或引用校验。\n" + response["text"])
            except (OSError, RuntimeError, ValueError) as error:
                self._result(f"图像诊断失败：{error}")
            return True
        if text.startswith("/mode "):
            requested = text[6:].strip().lower()
            if requested not in {"manual", "general"}:
                self._result("用法：/mode manual 或 /mode general。")
            else:
                self.mode = requested
                if requested == "general":
                    self._result("已切换到通用解释模式。内容不构成设备手册结论。")
                else:
                    self._result("已切换到手册模式。")
            return True
        if text.startswith("/speak "):
            requested = text[7:].strip().lower()
            if requested not in {"on", "off"}:
                self._result("用法：/speak on 或 /speak off。")
            elif requested == "on" and self.speaker is None:
                self._result("语音输出不可用。")
            else:
                self.speak = requested == "on"
                self._result("语音输出已开启。" if self.speak else "语音输出已关闭。")
            return True
        if text == "/listen":
            if self.listener is None:
                self._result("语音输入不可用。")
                return True
            try:
                result = self.listener(self.request_id_factory())
                heard = result.get("text", "")
                if heard:
                    self._write("你：" + heard)
                self._show_response(result)
            except (OSError, RuntimeError, ValueError) as error:
                self._result(f"语音输入失败：{error}")
            return True
        if text.startswith("/"):
            self._result("未知命令。可用：/mode manual、/mode general、/speak on、/speak off、/listen、/image <图片路径> [问题]、/reset、/quit。")
            return True
        response = self._request("answer" if self.mode == "manual" else "explain", text)
        self._show_response(response)
        return True

    def run(self) -> None:
        try:
            while True:
                self._prompt()
                line = self.input_stream.readline()
                if not line:
                    break
                if not self.handle_line(line):
                    break
        finally:
            self.agent.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", help="optional fixed session id for this console process")
    args = parser.parse_args()
    try:
        ChatConsole(AgentProcess(), session_id=args.session_id).run()
        return 0
    except (ConsoleError, OSError, ValueError) as error:
        print(f"助手：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
