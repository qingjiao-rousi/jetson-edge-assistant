"""Offline tests for the M7.4C 16384 synthetic long-context protocol."""

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


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GENERATOR = load_script("generate_vlm_long_context_fixture_m7_4c_test", SCRIPTS / "generate_vlm_long_context_fixture_m7_4c.py")
RUNNER = load_script("run_vlm_long_context_m7_4c_test", SCRIPTS / "run_vlm_long_context_m7_4c.py")
CONFIG = ROOT / "evidence/milestones/configs/vlm/vlm-long-context-m7.4c.json"


class VlmLongContextM74CTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_fixture_is_deterministic_synthetic_and_versioned(self) -> None:
        first = GENERATOR.generate_fixture(190)
        second = GENERATOR.generate_fixture(190)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("SYNTHETIC DEVICE SERVICE MANUAL - DETERMINISTIC M7.4C"))
        validation = GENERATOR.validate_fixture(first)
        self.assertTrue(validation["synthetic_only"])
        self.assertFalse(validation["contains_real_customer_information"])
        self.assertEqual(validation["fact_marker_counts"], {"start_code": 1, "middle_torque_nm": 1, "reset_seconds": 1})
        self.assertNotIn("The New York Times", first)

    def test_fixed_context_and_policy_are_16384_only(self) -> None:
        RUNNER.validate_config(self.config)
        self.assertEqual(self.config["fixed_parameters"]["context"], 16384)
        self.assertEqual(self.config["policy"]["contexts_executed"], [16384])
        self.assertFalse(self.config["policy"]["context_32768_executed"])
        changed = json.loads(json.dumps(self.config))
        changed["fixed_parameters"]["context"] = 8192
        with self.assertRaises(ValueError):
            RUNNER.validate_config(changed)

    def test_inference_command_is_frozen_and_offline(self) -> None:
        command = RUNNER.build_inference_command(self.config, Path("fixture.txt"), ROOT)
        rendered = " ".join(command)
        self.assertIn("--file", command)
        self.assertNotIn("--prompt", command)
        self.assertIn("--ctx-size 16384", rendered)
        self.assertIn("--batch-size 512", rendered)
        self.assertIn("--ubatch-size 512", rendered)
        self.assertIn("--gpu-layers 99", rendered)
        self.assertIn("--flash-attn on", rendered)
        self.assertIn("--offline", command)
        self.assertIn("--no-warmup", command)
        self.assertNotIn("/usr/bin/time", command)

    def test_correctness_gate_is_strict(self) -> None:
        valid = json.dumps({"publisher": "The New York Times", "start_code": "A17", "middle_torque_nm": 42, "reset_seconds": 7})
        self.assertTrue(RUNNER.validate_answer(valid, self.config)["passed"])
        wrong_type = json.dumps({"publisher": "The New York Times", "start_code": "A17", "middle_torque_nm": "42", "reset_seconds": 7})
        self.assertFalse(RUNNER.validate_answer(wrong_type, self.config)["passed"])
        self.assertFalse(RUNNER.validate_answer("```json\n{}\n```", self.config)["passed"])

    def test_dry_run_starts_no_subprocess(self) -> None:
        output = io.StringIO()
        with mock.patch.object(RUNNER.subprocess, "run") as run, mock.patch.object(RUNNER.subprocess, "Popen") as popen, contextlib.redirect_stdout(output):
            self.assertEqual(RUNNER.main(["--config", str(CONFIG), "--dry-run"]), 0)
        run.assert_not_called()
        popen.assert_not_called()
        plan = json.loads(output.getvalue())
        self.assertFalse(plan["model_process_started"])
        self.assertFalse(plan["execute_requested"])

    def test_m7_4b_references_are_explicit_and_read_only(self) -> None:
        references = self.config["readonly_references"]
        self.assertEqual(set(references), {"m7_4b_result", "m7_4b_evaluation", "m7_4b_runner", "m7_4b_config"})
        for reference in references.values():
            self.assertTrue((ROOT / reference["path"]).is_file())
            self.assertEqual(len(reference["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
