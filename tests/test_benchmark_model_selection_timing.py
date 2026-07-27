"""Offline fixtures for llama.cpp timing parsing."""

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_model_selection.py"
SPEC = importlib.util.spec_from_file_location("benchmark_model_selection", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RuntimeMetricsTest(unittest.TestCase):
    def test_distinct_complete_timing_lines(self) -> None:
        stderr = """0.1 I slot print_timing: id 0 | task 0 | prompt eval time = 372.95 ms / 147 tokens (2.54 ms per token, 394.16 tokens per second)
0.1 I slot print_timing: id 0 | task 0 |        eval time = 4664.80 ms / 65 tokens (71.77 ms per token, 13.93 tokens per second)
0.1 I slot print_timing: id 0 | task 0 |       total time = 5037.75 ms / 212 tokens
"""
        self.assertEqual(MODULE.runtime_metrics(stderr), {
            "runtime_prompt_eval_ms": 372.95,
            "runtime_prompt_tokens": 147,
            "runtime_prompt_tokens_per_second": 394.16,
            "runtime_decode_eval_ms": 4664.80,
            "runtime_decode_tokens": 65,
            "runtime_decode_tokens_per_second": 13.93,
            "runtime_total_ms": 5037.75,
        })

    def test_prompt_line_cannot_be_decode(self) -> None:
        stderr = "0.1 I slot print_timing: id 0 | task 0 | prompt eval time = 100.00 ms / 10 tokens (10.00 ms per token, 100.00 tokens per second)\n"
        metrics = MODULE.runtime_metrics(stderr)
        self.assertEqual(metrics["runtime_prompt_tokens"], 10)
        self.assertIsNone(metrics["runtime_decode_tokens"])


if __name__ == "__main__":
    unittest.main()
