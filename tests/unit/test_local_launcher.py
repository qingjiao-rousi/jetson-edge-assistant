import pathlib
import sys
import os
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import run_local_assistant as launcher_module


def config():
    return {"runtime": {
        "host": "127.0.0.1", "port": 18086, "base_url": "http://127.0.0.1:18086", "executable": "runtime-host",
        "model": {"path": "model.gguf", "size_bytes": 1, "sha256": "a" * 64},
        "mmproj": {"path": "mmproj.gguf", "size_bytes": 1, "sha256": "b" * 64},
        "context_tokens": 8192, "batch_tokens": 512, "ubatch_tokens": 512, "gpu_layers": 99,
    }}


class Process:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.terminated = False
        self.killed = False
        self.wait_calls = 0

    def poll(self): return self.returncode
    def terminate(self): self.terminated = True; self.returncode = 0
    def kill(self): self.killed = True; self.returncode = -9
    def wait(self, timeout=None): self.wait_calls += 1; return 0 if self.returncode is None else self.returncode


class LocalLauncherTest(unittest.TestCase):
    def make_launcher(self, popen, ready_check, *, times=None, port_check=None, config_path="configs/assistant.json"):
        clock = iter(times or [0.0, 0.1, 0.2, 0.3, 1.0])
        return launcher_module.LocalAssistantLauncher(
            config(), popen=popen, ready_check=ready_check, sleep=lambda _: None,
            monotonic=lambda: next(clock), port_check=port_check or (lambda *_: None), asset_check=lambda _: None,
            config_path=config_path)

    def test_ready_success_starts_assistant_and_cleans_children(self):
        runtime, assistant = Process(), Process(returncode=0)
        calls = []
        def popen(command, **_): calls.append(command); return runtime if len(calls) == 1 else assistant
        instance = self.make_launcher(popen, lambda _: None)
        self.assertEqual(instance.run(False, 1), 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(runtime.terminated)

    def test_custom_config_is_forwarded_to_assistant(self):
        runtime, assistant = Process(), Process()
        calls = []
        def popen(command, **_): calls.append(command); return runtime if len(calls) == 1 else assistant
        instance = self.make_launcher(popen, lambda _: None, config_path="configs/assistant-custom.json")
        self.assertEqual(instance.run(False, 1), 0)
        self.assertEqual(calls[1][-2:], ["--config", "configs/assistant-custom.json"])
        self.assertTrue(assistant.terminated)
        self.assertTrue(runtime.terminated)

    def test_ready_timeout_stops_runtime(self):
        runtime = Process()
        instance = self.make_launcher(lambda *_args, **_kwargs: runtime,
                                      lambda _: (_ for _ in ()).throw(launcher_module.AssistantPreflightError("not ready")),
                                      times=[0.0, 0.1, 0.2, 1.1])
        with self.assertRaisesRegex(launcher_module.LauncherError, "did not become ready"):
            instance.run(False, 1)
        self.assertTrue(runtime.terminated)

    def test_runtime_start_failure_is_diagnostic(self):
        instance = self.make_launcher(lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")), lambda _: None)
        with self.assertRaisesRegex(launcher_module.LauncherError, "Could not start Runtime"):
            instance.run(False, 1)

    def test_port_conflict_prevents_any_child(self):
        called = []
        instance = self.make_launcher(lambda *_args, **_kwargs: called.append(True), lambda _: None,
                                      port_check=lambda *_: (_ for _ in ()).throw(launcher_module.LauncherError("already in use")))
        with self.assertRaisesRegex(launcher_module.LauncherError, "already in use"):
            instance.run(False, 1)
        self.assertEqual(called, [])

    def test_assistant_start_failure_cleans_runtime(self):
        runtime = Process()
        calls = 0
        def popen(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1: return runtime
            raise OSError("assistant missing")
        instance = self.make_launcher(popen, lambda _: None)
        with self.assertRaisesRegex(launcher_module.LauncherError, "Could not start unified Assistant"):
            instance.run(False, 1)
        self.assertTrue(runtime.terminated)

    def test_speak_does_not_run_asr_preflight(self):
        runtime, assistant = Process(), Process(returncode=0)
        calls = []
        def popen(command, **_): calls.append(command); return runtime if len(calls) == 1 else assistant
        instance = self.make_launcher(popen, lambda _: None)
        with mock.patch("app.assistant.application.check_listen") as check_listen:
            self.assertEqual(instance.run(True, 1), 0)
        check_listen.assert_not_called()
        self.assertIn("--speak", calls[1])

    def test_runtime_output_is_captured_not_inherited_and_success_log_is_removed(self):
        runtime, assistant = Process(), Process(returncode=0)
        calls = []
        def popen(command, **kwargs):
            calls.append((command, kwargs))
            return runtime if len(calls) == 1 else assistant
        instance = self.make_launcher(popen, lambda _: None)
        self.assertEqual(instance.run(False, 1), 0)
        self.assertIsNotNone(instance.runtime_log_path)
        self.assertFalse(os.path.exists(instance.runtime_log_path))
        self.assertIsNotNone(calls[0][1]["stdout"])
        self.assertIs(calls[0][1]["stdout"], calls[0][1]["stderr"])


if __name__ == "__main__":
    unittest.main()
