import json
import pathlib
import unittest
from unittest import mock

from tests.evaluation import rag_r2_6_compare as evaluation
from app.retrieval.core import ProviderUnavailable


ROOT = pathlib.Path(__file__).resolve().parents[2]


class R26EvaluationContractTest(unittest.TestCase):
    def test_dry_run_validates_frozen_assets_without_loading_embedding_model(self):
        payload = evaluation.dry_run_payload(
            ROOT / "tests/fixtures/rag-m9.1b-r2.6-dev/questions.json",
            ROOT / "generated/rag-m9.1b-r2.2/hybrid.sqlite3",
            ROOT / "configs/embedding.json",
            ROOT / "configs/manual-retrieval.json",
            ROOT / "configs/manual-retrieval-r2.6-candidate.json",
        )
        self.assertEqual(payload["status"], "DRY_RUN")
        self.assertEqual((payload["dataset"]["questions"], payload["dataset"]["answerable"], payload["dataset"]["no_answer"]), (14, 7, 7))
        self.assertEqual(payload["algorithms"], ["M9.1B-R2.5", "M9.1B-R2.6-CANDIDATE"])

    def test_pre_registered_decision_requires_all_conditions(self):
        baseline = {"metrics": {"no_answer_correct_rejection_rate": 0.5, "false_positive_count": 3, "recall_at_3": 1.0, "device_or_fault_mismatch_count": 0}}
        candidate = {"metrics": {"no_answer_correct_rejection_rate": 0.5, "false_positive_count": 3, "recall_at_3": 0.875, "device_or_fault_mismatch_count": 0}}
        self.assertTrue(evaluation.comparison_decision(baseline, candidate)["eligible_for_new_holdout"])
        candidate["metrics"]["false_positive_count"] = 4
        self.assertFalse(evaluation.comparison_decision(baseline, candidate)["eligible_for_new_holdout"])

    def test_cached_query_provider_reuses_one_embedding_for_both_algorithms(self):
        class Provider:
            spec = object()
            def __init__(self): self.calls = []
            def embed(self, texts, input_type):
                self.calls.append((list(texts), input_type))
                return [[float(index)] for index, _ in enumerate(texts)]
        provider = Provider()
        cached = evaluation.CachedQueryProvider(provider)
        self.assertEqual(cached.embed(["same-query"], "query"), [[0.0]])
        self.assertEqual(cached.embed(["same-query"], "query"), [[0.0]])
        self.assertEqual(provider.calls, [(["same-query"], "query")])

    def test_provider_failure_emits_structured_json_with_fingerprints(self):
        output = []
        with mock.patch.object(evaluation, "provider_from_config", side_effect=ProviderUnavailable("local provider unavailable")), \
             mock.patch("builtins.print", side_effect=output.append):
            status = evaluation.main(["--provider-preflight"])
        self.assertEqual(status, 2)
        payload = json.loads(output[0])
        self.assertEqual((payload["status"], payload["stage"], payload["error_type"]), ("ERROR", "provider_preflight", "ProviderUnavailable"))
        self.assertEqual(payload["r2_5_algorithm_fingerprint"], "0d84afa229f49d779059ea83d658b768ba91063832377d651702d8d330575df2")
        self.assertEqual(len(payload["r2_6_candidate_module_sha256"]), 64)
        self.assertEqual(len(payload["r2_6_candidate_config_sha256"]), 64)

    def test_baseline_provider_failure_emits_structured_json(self):
        class Provider:
            spec = object()

            def embed(self, texts, input_type):
                raise AssertionError("evaluate is expected to fail before embedding")

        output = []
        with mock.patch.object(evaluation, "provider_from_config", return_value=Provider()), \
             mock.patch.object(evaluation, "evaluate", side_effect=ProviderUnavailable("embedding subprocess unavailable")), \
             mock.patch("builtins.print", side_effect=output.append):
            status = evaluation.main([])
        self.assertEqual(status, 2)
        payload = json.loads(output[0])
        self.assertEqual((payload["status"], payload["stage"], payload["error_type"]), ("ERROR", "baseline_r2_5", "ProviderUnavailable"))
        self.assertEqual(payload["r2_5_algorithm_fingerprint"], "0d84afa229f49d779059ea83d658b768ba91063832377d651702d8d330575df2")


if __name__ == "__main__":
    unittest.main()
