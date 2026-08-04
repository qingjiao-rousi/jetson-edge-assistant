"""Offline tests for M7.4C-R; no test invokes a model binary."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("m7_4c_r_test", SCRIPTS / "run_vlm_long_context_m7_4c_r.py")
assert spec and spec.loader
RUNNER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RUNNER)
CONFIG = ROOT / "configs/vlm-long-context-m7.4c-r.json"


class VlmLongContextM74CRTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_attempt_accounting_and_policy_are_frozen(self) -> None:
        RUNNER.validate_config(self.config)
        self.assertEqual(self.config["attempt_ordinal"], 2)
        self.assertEqual(self.config["previous_inference_attempt_count"], 1)
        self.assertEqual(self.config["retry_count"], 1)
        self.assertEqual(self.config["policy"]["model_starts_allowed"], 1)
        self.assertFalse(self.config["policy"]["third_attempt_allowed"])
        self.assertFalse(self.config["policy"]["context_32768_executed"])

    def test_model_command_reuses_frozen_fixture_and_parameters(self) -> None:
        command = RUNNER.build_model_command(self.config, ROOT)
        rendered = " ".join(command)
        self.assertIn(str(ROOT / self.config["fixture"]["path"]), command)
        self.assertIn("--ctx-size 16384", rendered)
        self.assertIn("--batch-size 512", rendered)
        self.assertIn("--ubatch-size 512", rendered)
        self.assertIn("--gpu-layers 99", rendered)
        self.assertIn("--flash-attn on", rendered)
        self.assertIn("--offline", command)
        self.assertIn("--no-warmup", command)
        self.assertNotIn("--prompt", command)
        self.assertNotIn("/usr/bin/time", command)

    def test_readonly_references_include_failure_and_audit(self) -> None:
        references = self.config["readonly_references"]
        self.assertIn("m7_4c_failure", references)
        self.assertIn("m7_4c_audit", references)
        for item in references.values():
            self.assertTrue((ROOT / item["path"]).is_file())
            self.assertEqual(len(item["sha256"]), 64)

    def test_dry_run_does_not_start_subprocesses(self) -> None:
        output = io.StringIO()
        with mock.patch.object(RUNNER.subprocess, "run") as run, contextlib.redirect_stdout(output):
            self.assertEqual(RUNNER.main(["--config", str(CONFIG)]), 0)
        run.assert_not_called()
        plan = json.loads(output.getvalue())
        self.assertFalse(plan["execute_requested"])
        self.assertFalse(plan["model_process_started"])


if __name__ == "__main__":
    unittest.main()
