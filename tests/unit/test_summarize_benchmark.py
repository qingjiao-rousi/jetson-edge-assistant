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


if __name__ == "__main__":
    unittest.main()
