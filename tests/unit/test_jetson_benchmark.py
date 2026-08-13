import importlib.util
import pathlib
import base64
import subprocess
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "run_jetson_benchmark", ROOT / "scripts" / "run_jetson_benchmark.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class JetsonBenchmarkContractTest(unittest.TestCase):
    def test_git_source_state_records_cleanliness_without_exposing_paths(self):
        with mock.patch.object(MODULE.subprocess, "check_output", side_effect=["abc123\n", " M README.md\n?? local.txt\n"]):
            commit, clean, entries, status_hash = MODULE.git_source_state()
        self.assertEqual(commit, "abc123")
        self.assertFalse(clean)
        self.assertEqual(entries, 2)
        self.assertEqual(len(status_hash), 64)

    def test_clock_status_requires_fixed_cpu_gpu_and_emc(self):
        locked = """
cpu0: Online=1 Governor=schedutil MinFreq=1728000 MaxFreq=1728000 CurrentFreq=1728000
cpu1: Online=1 Governor=schedutil MinFreq=1728000 MaxFreq=1728000 CurrentFreq=1728000
GPU MinFreq=612000000 MaxFreq=612000000 CurrentFreq=612000000
EMC MinFreq=3199000000 MaxFreq=3199000000 CurrentFreq=3199000000 FreqOverride=1
"""
        dynamic = locked.replace("MinFreq=612000000", "MinFreq=306000000", 1).replace("FreqOverride=1", "FreqOverride=0")
        self.assertTrue(MODULE.jetson_clock_status(locked)[0])
        self.assertFalse(MODULE.jetson_clock_status(dynamic)[0])

    def test_request_is_deterministic_and_bound_to_configured_model(self):
        config = {"runtime": {"model": {"sha256": "a" * 64}}}
        request = MODULE.runtime_request(config, "request-1", "prompt", 32)
        self.assertEqual(request["model_sha256"], "a" * 64)
        self.assertEqual(request["sampling"], {
            "seed": 424242, "top_k": 1, "top_p": 1.0, "min_p": 0.0, "temperature": 0.0,
        })
        self.assertEqual(request["max_new_tokens"], 32)
        self.assertFalse(request["stream"])

    def test_image_request_uses_diagnosis_contract_without_raw_evidence_metadata(self):
        config = {"runtime": {"model": {"sha256": "a" * 64}}}
        image = ("tests/fixture.png", b"png-bytes", "image/png", "b" * 64)
        request = MODULE.runtime_request(config, "image-1", "inspect", 128, image)
        self.assertEqual(request["prompt"], "inspect")
        self.assertEqual(request["images"][0]["id"], "tests/fixture.png")
        self.assertEqual(request["images"][0]["mime"], "image/png")
        self.assertEqual(base64.b64decode(request["images"][0]["data_base64"]), b"png-bytes")
        self.assertNotIn("image_sha256", request)

    def test_image_fixture_is_bound_by_relative_path_mime_and_hash(self):
        relative, data, mime, digest = MODULE.load_benchmark_image(
            "tests/fixtures/vlm-service/synthetic-alarm-panel.png"
        )
        self.assertEqual(relative, "tests/fixtures/vlm-service/synthetic-alarm-panel.png")
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertEqual(mime, "image/png")
        self.assertEqual(digest, "455963a828a1272a60cc6774982b874969c067f4c72bc47ef002a6c719483395")

    def test_image_fixture_rejects_paths_outside_repository(self):
        with self.assertRaisesRegex(ValueError, "inside the repository"):
            MODULE.load_benchmark_image("../outside.png")

    def test_environment_binds_workload_endpoint_and_output_limit(self):
        config = {"runtime": {
            "model": {"path": "model.gguf", "sha256": "a" * 64},
            "mmproj": {"path": "mmproj.gguf", "sha256": "b" * 64},
            "chat_endpoint": "/v1/chat",
        }}
        image = ("tests/fixture.png", b"png", "image/png", "c" * 64)
        lines = MODULE.environment_lines(
            config, "q4-image", "inspect", 15, True, "locked", "commit", True, 0, "d" * 64,
            image, 128,
        )
        self.assertIn("workload=single_image", lines)
        self.assertIn("endpoint=/v1/diagnose/image", lines)
        self.assertIn("max_new_tokens=128", lines)

    def test_dry_run_needs_no_config_or_model(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_jetson_benchmark.py"),
             "--config", "missing.json", "--dry-run"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no Runtime started", result.stdout)


if __name__ == "__main__":
    unittest.main()
