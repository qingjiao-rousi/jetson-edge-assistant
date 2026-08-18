import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_mtmd_prefix_reuse", ROOT / "scripts" / "validate_mtmd_prefix_reuse.py")
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def response(prompt_tokens, hit_tokens, miss_tokens):
    return {
        "prompt_tokens": prompt_tokens,
        "metrics": {
            "cache_hit_tokens": hit_tokens,
            "cache_miss_tokens": miss_tokens,
        },
    }


class PrefixReuseBatchBoundaryTest(unittest.TestCase):
    def test_below_batch_zero_hit_is_expected_no_reuse(self):
        result = VALIDATOR.classify_prefix_reuse(response(264, 0, 264), 512)

        self.assertEqual(result["classification"], "PASS_EXPECTED_NO_REUSE")
        self.assertEqual(result["batch_tokens"], 512)

    def test_eligible_prompt_with_hit_is_reuse(self):
        result = VALIDATOR.classify_prefix_reuse(response(1032, 1024, 8), 512)

        self.assertEqual(result["classification"], "PASS_REUSE")

    def test_eligible_prompt_without_hit_fails(self):
        result = VALIDATOR.classify_prefix_reuse(response(1032, 0, 1032), 512)

        self.assertEqual(result["classification"], "FAIL")
        self.assertIn("positive cache hit", result["reason"])

    def test_bad_cache_accounting_fails(self):
        result = VALIDATOR.classify_prefix_reuse(response(1032, 1024, 7), 512)

        self.assertEqual(result["classification"], "FAIL")
        self.assertIn("cache_hit_tokens + cache_miss_tokens", result["reason"])


if __name__ == "__main__":
    unittest.main()
