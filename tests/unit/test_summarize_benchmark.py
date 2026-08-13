import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "summarize_benchmark", ROOT / "scripts" / "summarize_benchmark.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BenchmarkSummaryTest(unittest.TestCase):
    def test_nearest_rank_and_stats(self):
        values = list(range(1, 16))
        self.assertEqual(MODULE.nearest_rank(values, 0.9), 14)
        self.assertEqual(MODULE.stats(values)["median"], 8)

    def test_metric_summary_preserves_small_sample_count(self):
        summary = MODULE.stats([15.0, 15.1, 15.2])
        self.assertEqual(summary["n"], 3)
        self.assertEqual(summary["min"], 15.0)
        self.assertEqual(summary["max"], 15.2)

    def test_single_image_summary_includes_vision_metrics_and_hash(self):
        row = {
            "sample_index": 1,
            "workload": "single_image",
            "image_sha256": "a" * 64,
            "model_sha256": "b" * 64,
            "client_http_status": 200,
            "client_total_ms": 30,
            "error": None,
            "prompt_tokens": 10,
            "output_tokens": 4,
            "finish_reason": "eog",
            "text": "panel",
            "image_tokens": 12,
            "measurement_status": {"vision_encode_ms": "measured"},
            "metrics": {
                "ttft_ms": 20,
                "prefill_ms": 3,
                "decode_ms": 4,
                "decode_tokens_per_second": 1,
                "total_ms": 27,
                "image_preprocess_ms": 2,
                "vision_encode_ms": 8,
                "image_embedding_ms": 1,
            },
        }
        summary = MODULE.summarize_rows([row])
        self.assertEqual(summary["validity"]["workload"], "single_image")
        self.assertEqual(summary["validity"]["image_sha256_values"], ["a" * 64])
        self.assertEqual(summary["metrics"]["vision_encode_ms"]["median"], 8.0)
        self.assertEqual(summary["metrics"]["image_tokens"]["median"], 12.0)

    def test_single_image_summary_rejects_mixed_image_hashes(self):
        rows = []
        for index, digest in enumerate(("a" * 64, "b" * 64), 1):
            rows.append({
                "sample_index": index, "workload": "single_image", "image_sha256": digest,
                "model_sha256": "c" * 64, "client_http_status": 200, "client_total_ms": 1,
                "error": None, "prompt_tokens": 1, "output_tokens": 1, "finish_reason": "eog",
                "text": "x", "image_tokens": 1, "measurement_status": {},
                "metrics": {"ttft_ms": 1, "prefill_ms": 1, "decode_ms": 1,
                            "decode_tokens_per_second": 1, "total_ms": 1,
                            "image_preprocess_ms": 1, "vision_encode_ms": 1, "image_embedding_ms": 1},
            })
        with self.assertRaisesRegex(ValueError, "one image SHA-256"):
            MODULE.summarize_rows(rows)


if __name__ == "__main__":
    unittest.main()
