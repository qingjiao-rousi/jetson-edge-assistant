"""Offline tests for the M7.4B synthetic long-context runner."""

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


GENERATOR = load_script("generate_vlm_long_context_fixture_test", SCRIPTS / "generate_vlm_long_context_fixture.py")
RUNNER = load_script("run_vlm_long_context_test", SCRIPTS / "run_vlm_long_context.py")
CONFIG = ROOT / "evidence/milestones/configs/vlm/vlm-long-context-m7.4b.json"


class VlmLongContextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_fixture_is_deterministic_synthetic_and_has_unique_facts(self) -> None:
        first = GENERATOR.generate_fixture(100)
        second = GENERATOR.generate_fixture(100)
        self.assertEqual(first, second)
        validation = GENERATOR.validate_fixture(first)
        self.assertTrue(validation["synthetic_only"])
        self.assertFalse(validation["contains_real_customer_information"])
        self.assertEqual(validation["fact_marker_counts"], {
            "start_code": 1,
            "middle_torque_nm": 1,
            "reset_seconds": 1,
        })
        self.assertNotIn("The New York Times", first)

    def test_facts_are_at_start_middle_and_end(self) -> None:
        validation = GENERATOR.validate_fixture(GENERATOR.generate_fixture(120))
        ratios = validation["fact_position_ratios"]
        self.assertLess(ratios["start_code"], 0.10)
        self.assertGreaterEqual(ratios["middle_torque_nm"], 0.40)
        self.assertLessEqual(ratios["middle_torque_nm"], 0.60)
        self.assertGreater(ratios["reset_seconds"], 0.90)

    def test_fixture_ends_with_exact_json_contract(self) -> None:
        fixture = GENERATOR.generate_fixture(80)
        self.assertTrue(fixture.endswith(
            '{\n  "publisher": "...",\n  "start_code": "...",\n'
            '  "middle_torque_nm": 0,\n  "reset_seconds": 0\n}'
        ))

    def test_tokenizer_count_is_directly_parsed(self) -> None:
        self.assertEqual(RUNNER.parse_tokenizer_count("[1, 2]\nTotal number of tokens: 6321\n"), 6321)
        with self.assertRaises(RUNNER.context_smoke.SmokeError):
            RUNNER.parse_tokenizer_count("no count")

    def test_inference_command_is_frozen_and_uses_file(self) -> None:
        command = RUNNER.build_inference_command(self.config, Path("fixture.txt"), ROOT)
        rendered = " ".join(command)
        self.assertIn("--file", command)
        self.assertNotIn("--prompt", command)
        self.assertNotIn("/usr/bin/time", command)
        self.assertNotIn("-hf", command)
        self.assertIn("--offline", command)
        self.assertIn("--no-warmup", command)
        self.assertIn("--ctx-size 8192", rendered)
        self.assertIn("--batch-size 512", rendered)
        self.assertIn("--ubatch-size 512", rendered)
        self.assertIn("--gpu-layers 99", rendered)
        self.assertIn("--flash-attn on", rendered)
        self.assertIn("--temperature 0", rendered)
        self.assertIn("--seed 424242", rendered)
        self.assertIn("--predict 128", rendered)

    def test_correctness_gate_accepts_only_exact_answer(self) -> None:
        valid = json.dumps({
            "publisher": "The New York Times",
            "start_code": "A17",
            "middle_torque_nm": 42,
            "reset_seconds": 7,
        })
        result = RUNNER.validate_answer(valid, self.config)
        self.assertTrue(result["passed"])
        self.assertIsNone(result["failure_class_if_failed"])

        invalid_json = RUNNER.validate_answer("```json\n{}\n```", self.config)
        self.assertFalse(invalid_json["passed"])
        self.assertEqual(invalid_json["failure_class_if_failed"], "quality_gate_failed")

        wrong_fact = RUNNER.validate_answer(json.dumps({
            "publisher": "The New York Times",
            "start_code": "A17",
            "middle_torque_nm": 41,
            "reset_seconds": 7,
        }), self.config)
        self.assertFalse(wrong_fact["passed"])
        self.assertEqual(wrong_fact["failure_class_if_failed"], "quality_gate_failed")

    def test_numeric_fact_types_are_strict(self) -> None:
        answer = json.dumps({
            "publisher": "The New York Times",
            "start_code": "A17",
            "middle_torque_nm": "42",
            "reset_seconds": 7,
        })
        result = RUNNER.validate_answer(answer, self.config)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["middle_torque_nm_exact"])

    def test_dry_run_starts_no_subprocess(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(RUNNER.subprocess, "run") as run,
            mock.patch.object(RUNNER.subprocess, "Popen") as popen,
            contextlib.redirect_stdout(output),
        ):
            exit_code = RUNNER.main(["--config", str(CONFIG), "--dry-run"])
        self.assertEqual(exit_code, 0)
        run.assert_not_called()
        popen.assert_not_called()
        plan = json.loads(output.getvalue())
        self.assertFalse(plan["model_process_started"])
        self.assertFalse(plan["execute_requested"])

    def test_only_execute_reaches_execution_path(self) -> None:
        output = io.StringIO()
        with mock.patch.object(RUNNER, "execute_run", return_value=9) as execute:
            with contextlib.redirect_stdout(output):
                default_code = RUNNER.main(["--config", str(CONFIG)])
                dry_code = RUNNER.main(["--config", str(CONFIG), "--dry-run"])
                execute_code = RUNNER.main(["--config", str(CONFIG), "--execute"])
        self.assertEqual(default_code, 0)
        self.assertEqual(dry_code, 0)
        self.assertEqual(execute_code, 9)
        execute.assert_called_once()

    def test_result_schema_contains_required_fields(self) -> None:
        result = RUNNER.initial_result(self.config)
        self.assertEqual(RUNNER.missing_required_result_fields(result), [])
        del result["correctness"]["parsed_answer"]
        self.assertIn("correctness.parsed_answer", RUNNER.missing_required_result_fields(result))

    def test_config_rejects_other_context(self) -> None:
        changed = json.loads(json.dumps(self.config))
        changed["fixed_parameters"]["context"] = 16384
        with self.assertRaises(ValueError):
            RUNNER.validate_config(changed)


if __name__ == "__main__":
    unittest.main()
