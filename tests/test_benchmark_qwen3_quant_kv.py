#!/usr/bin/env python3
"""Static contract tests for M6.4 benchmark-result provenance."""

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("qwen3_benchmark", ROOT / "scripts/benchmark_qwen3_quant_kv.py")
assert SPEC and SPEC.loader
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


def validation(model_id: str, file_type: str) -> dict:
    return {
        "id": model_id, "path": f"/models/{model_id}.gguf", "sha256": model_id * 16,
        "file_type": file_type, "size_bytes": 1234,
        "metadata": {"gguf_version": 3, "tensor_count": 398, "metadata": {
            "general.architecture": "qwen3", "general.file_type": 15,
            "general.quantization_version": 2, "qwen3.context_length": 40960,
            "qwen3.block_count": 36,
        }, "chat_template_present": True, "chat_template_bytes": 4100,
        "chat_template_sha256": "template"},
    }


class BenchmarkProvenanceTest(unittest.TestCase):
    def test_plan_jsonl_csv_and_summary_carry_complete_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            config = work / "config.json"; config.write_text("{}", encoding="utf-8")
            assets = work / "assets.json"; assets.write_text("{}", encoding="utf-8")
            baseline = work / "baseline.json"; baseline.write_text("{}", encoding="utf-8")
            runner = work / "runner"; runner.write_bytes(b"test runner")
            provenance = BENCHMARK.build_provenance(
                config, assets, baseline, runner,
                {"q4_k_m": validation("q4_k_m", "Q4_K_M"), "q8_0": validation("q8_0", "Q8_0")},
            )
            self.assertEqual(provenance["runtime_contract"]["kv_cache"]["k"], "f16")
            self.assertFalse(provenance["runtime_contract"]["runtime_first_token_ms_is_service_ttft"])
            for key in ("project", "runtime", "tooling", "inputs", "models", "provenance_sha256"):
                self.assertIn(key, provenance)
            for model_id in ("q4_k_m", "q8_0"):
                model = provenance["models"][model_id]
                self.assertIn("sha256", model)
                self.assertIn("size_bytes", model)
                self.assertIn("gguf_metadata", model)

            plan = {"provenance": provenance, "provenance_sha256": provenance["provenance_sha256"], "required_valid_measured": 5, "workloads": ["S", "L", "G"]}
            record = {"phase": "measured", "prompt_id": "S", "attempt": 1, "model_id": "q4_k_m", "valid": False, "failure_class": "workload_token_target_mismatch"}
            BENCHMARK.write_outputs(work, [record], plan)
            plan["provenance"] = provenance
            (work / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

            loaded_plan = json.loads((work / "plan.json").read_text(encoding="utf-8"))
            loaded_record = json.loads((work / "records.jsonl").read_text(encoding="utf-8"))
            loaded_summary = json.loads((work / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(loaded_plan["provenance_sha256"], provenance["provenance_sha256"])
            self.assertEqual(loaded_plan["provenance"]["provenance_sha256"], provenance["provenance_sha256"])
            self.assertEqual(loaded_record["provenance_sha256"], provenance["provenance_sha256"])
            self.assertEqual(loaded_summary["provenance_sha256"], provenance["provenance_sha256"])
            self.assertEqual(set(loaded_summary["by_workload"]), {"S", "L", "G"})
            with (work / "summary.csv").open(newline="", encoding="utf-8") as stream:
                row = next(csv.DictReader(stream))
            for key in ("project_commit", "runtime_commit", "benchmark_script_sha256", "benchmark_runner_sha256", "config_sha256", "asset_manifest_sha256", "deployment_baseline_manifest_sha256", "q4_k_m_model_sha256", "q4_k_m_model_size_bytes", "q4_k_m_gguf_metadata", "q8_0_model_sha256", "q8_0_model_size_bytes", "q8_0_gguf_metadata"):
                self.assertIn(key, row)
                self.assertTrue(row[key])


if __name__ == "__main__":
    unittest.main()
