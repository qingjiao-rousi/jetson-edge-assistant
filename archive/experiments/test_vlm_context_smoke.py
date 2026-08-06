"""Offline tests for the explicit-only VLM context smoke runner."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_vlm_context_smoke.py"
CONFIG = ROOT / "evidence/milestones/configs/vlm/vlm-context-smoke-m7.4.json"
SPEC = importlib.util.spec_from_file_location("run_vlm_context_smoke", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class VlmContextSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_context_outside_frozen_matrix_is_rejected(self) -> None:
        for context in (0, 2048, 12288, 65536):
            with self.subTest(context=context), self.assertRaises(ValueError):
                MODULE.validate_context(context, self.config)

    def test_hash_mismatch_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"local fixture"
            (root / "asset.bin").write_bytes(payload)
            expected = {
                "path": "asset.bin",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(b"different fixture").hexdigest(),
            }
            with self.assertRaises(MODULE.SmokeError) as raised:
                MODULE.verify_file(root, expected, "model")
            self.assertEqual(raised.exception.failure_class, "asset_hash_mismatch")

    def test_dry_run_starts_no_process(self) -> None:
        stdout = io.StringIO()
        with (
            mock.patch.object(MODULE.subprocess, "run") as run,
            mock.patch.object(MODULE.subprocess, "Popen") as popen,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = MODULE.main([
                "--config", str(CONFIG), "--context", "8192", "--dry-run"
            ])
        self.assertEqual(exit_code, 0)
        run.assert_not_called()
        popen.assert_not_called()
        plan = json.loads(stdout.getvalue())
        self.assertFalse(plan["model_process_started"])
        self.assertFalse(plan["execute_requested"])

    def test_command_has_no_usr_bin_time_or_download_argument(self) -> None:
        command = MODULE.build_model_command(self.config, 8192, ROOT)
        rendered = " ".join(command)
        self.assertNotIn("/usr/bin/time", rendered)
        self.assertNotIn("-hf", command)
        self.assertNotIn("--hf-repo", command)
        self.assertIn("--offline", command)
        self.assertIn("--no-warmup", command)

    def test_failure_class_mapping(self) -> None:
        cases = [
            (124, "", "", True, "timeout"),
            (1, "CUDA error", "", True, "cuda_error"),
            (1, "out of memory", "", True, "oom_or_allocation_failed"),
            (1, "context overflow", "", True, "context_limit"),
            (1, "failed to load model", "", True, "model_load_failed"),
            (1, "Failed to load vision model from mmproj", "", True, "mmproj_load_failed"),
            (1, "unable to load image", "", True, "image_decode_failed"),
            (1, "failed to encode image slice", "", True, "vision_encode_failed"),
            (1, "failed to decode token", "", True, "decode_failed"),
            (0, "", "answer", False, "telemetry_missing"),
            (1, "unexpected", "", True, "internal"),
        ]
        for exit_code, stderr, stdout, telemetry_valid, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    MODULE.classify_failure(exit_code, stderr, stdout, telemetry_valid),
                    expected,
                )

    def test_result_schema_contains_required_fields(self) -> None:
        result = MODULE.initial_result(8192, self.config)
        self.assertEqual(MODULE.missing_required_result_fields(result), [])
        del result["kv_cache"]["total_mib"]
        self.assertIn("kv_cache.total_mib", MODULE.missing_required_result_fields(result))

    def test_only_execute_allows_model_execution_path(self) -> None:
        stdout = io.StringIO()
        with mock.patch.object(MODULE, "execute_run", return_value=7) as execute:
            with contextlib.redirect_stdout(stdout):
                default_exit = MODULE.main([
                    "--config", str(CONFIG), "--context", "8192"
                ])
                dry_exit = MODULE.main([
                    "--config", str(CONFIG), "--context", "8192", "--dry-run"
                ])
            execute.assert_not_called()
            execute_exit = MODULE.main([
                "--config", str(CONFIG), "--context", "8192", "--execute"
            ])
        self.assertEqual(default_exit, 0)
        self.assertEqual(dry_exit, 0)
        self.assertEqual(execute_exit, 7)
        execute.assert_called_once()

    def test_m7_4a_execute_guard_rejects_other_matrix_contexts(self) -> None:
        for context in (4096, 16384, 32768):
            with self.subTest(context=context), self.assertRaises(ValueError):
                MODULE.validate_execution_context(context, self.config)


if __name__ == "__main__":
    unittest.main()
