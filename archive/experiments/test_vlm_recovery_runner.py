"""Offline process-supervision tests; these never invoke a model binary."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_vlm_recovery.py"
spec = importlib.util.spec_from_file_location("vlm_recovery_runner_test", SCRIPT)
assert spec and spec.loader
RUNNER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RUNNER)


class VlmRecoveryRunnerTest(unittest.TestCase):
    def write_argv(self, directory: Path, name: str, argv: list[str]) -> Path:
        path = directory / name
        path.write_text(json.dumps(argv), encoding="utf-8")
        return path

    def test_dry_run_never_starts_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            model = self.write_argv(directory, "model.json", [sys.executable, "-c", "raise SystemExit(0)"])
            telemetry = self.write_argv(directory, "telemetry.json", [sys.executable, "-c", "raise SystemExit(0)"])
            output = directory / "result"
            self.assertEqual(RUNNER.main(["--model-command-json", str(model), "--telemetry-command-json", str(telemetry), "--output-dir", str(output)]), 0)
            self.assertFalse(output.exists())

    def test_execute_records_exact_nonzero_returncode_and_cleans_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            model = self.write_argv(directory, "model.json", [sys.executable, "-c", "raise SystemExit(23)"])
            telemetry = self.write_argv(directory, "telemetry.json", [sys.executable, "-c", "import time; time.sleep(60)"])
            output = directory / "result"
            self.assertEqual(RUNNER.main(["--execute", "--model-command-json", str(model), "--telemetry-command-json", str(telemetry), "--output-dir", str(output), "--grace-seconds", "0.2"]), 1)
            result = json.loads((output / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["model"]["returncode"], 23)
            self.assertTrue(result["telemetry_cleanup"]["term_sent"])
            self.assertIsNotNone(result["telemetry"]["returncode"])

    def test_terminate_process_group_stops_child_group(self) -> None:
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        result = RUNNER.terminate_process_group(process, 0.2)
        self.assertTrue(result["term_sent"])
        self.assertEqual(process.poll(), result["returncode"])
        self.assertIsNotNone(result["returncode"])

    def test_interrupt_handler_raises_catchable_interruption(self) -> None:
        observed: list[int] = []

        def handler(signum: int, _frame: object) -> None:
            observed.append(signum)
            raise KeyboardInterrupt("test interruption")

        with self.assertRaises(KeyboardInterrupt):
            handler(15, None)
        self.assertEqual(observed, [15])

    def test_invalid_command_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                RUNNER.read_argv(path)


if __name__ == "__main__":
    unittest.main()
