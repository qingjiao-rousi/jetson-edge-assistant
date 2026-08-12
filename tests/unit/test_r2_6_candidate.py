import copy
import pathlib
import unittest
from unittest import mock

from app.qa import manual_qa
from app.retrieval import active_pipeline, engine, r2_6_candidate
from app.retrieval.core import ContractError


ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "manual-retrieval-r2.6-candidate.json"
RETRIEVAL = {
    "kind": "hybrid-rrf",
    "top_k": 3,
    "rrf_k": 60,
    "admission": {
        "minimum_vector_score": 0.4,
        "minimum_keyword_coverage": 0.1,
        "minimum_margin": 0.0001,
    },
    "fact_evidence": {"minimum_coverage": 0.25, "minimum_terms": 1},
}


def admitted_response(keyword_coverage: float) -> dict:
    citation = {"chunk_id": "BX9#spec"}
    return {
        "query": "query",
        "answerable": True,
        "results": [{"chunk_id": "BX9#spec", "text": "fact", "citation": citation}],
        "citations": [citation],
        "constraints": {"devices": ["BX-9"], "fault_codes": []},
        "admission": {
            "passed": True,
            "reasons": [],
            "vector_score": 0.4,
            "keyword_coverage": keyword_coverage,
            "margin": 0.0001,
            "fact_evidence": {"core_aligned": True, "coverage": 0.25},
        },
    }


class R26CandidateTest(unittest.TestCase):
    def setUp(self):
        self.original_query = r2_6_candidate._query_r2_5

    def tearDown(self):
        r2_6_candidate._query_r2_5 = self.original_query

    def run_candidate(self, response: dict) -> dict:
        calls = []
        r2_6_candidate._query_r2_5 = lambda *args: calls.append(args) or copy.deepcopy(response)
        result = r2_6_candidate.query_index("database", "query", 3, "provider", RETRIEVAL)
        self.assertEqual(calls, [("database", "query", 3, "provider", RETRIEVAL)])
        return result

    def test_low_keyword_coverage_rejects_and_clears_evidence(self):
        result = self.run_candidate(admitted_response(0.099))
        self.assertFalse(result["answerable"])
        self.assertEqual(result["results"], [])
        self.assertEqual(result["citations"], [])
        self.assertFalse(result["admission"]["passed"])
        self.assertIn("keyword_coverage_below_threshold", result["admission"]["reasons"])
        self.assertEqual(result["admission"]["fact_evidence"], {"core_aligned": True, "coverage": 0.25})

    def test_keyword_coverage_at_threshold_preserves_r2_5_response(self):
        response = admitted_response(0.1)
        self.assertEqual(self.run_candidate(response), response)

    def test_keyword_coverage_above_threshold_preserves_r2_base_ranking(self):
        response = admitted_response(0.5)
        self.assertEqual(self.run_candidate(response), response)

    def test_no_r2_base_candidate_preserves_existing_rejection(self):
        response = {
            "query": "query", "answerable": False, "results": [], "citations": [],
            "constraints": {"devices": [], "fault_codes": []},
            "admission": {"passed": False, "reasons": ["no_candidate_satisfies_hard_constraints", "missing_core_fact_family"]},
        }
        self.assertEqual(self.run_candidate(response), response)

    def test_candidate_config_is_fixed_and_rejects_unknown_fields(self):
        loaded = r2_6_candidate.load_config(CONFIG)
        self.assertEqual(loaded["milestone"], "M9.1B-R2.6-CANDIDATE")
        invalid = {**loaded, "unexpected": True}
        with mock.patch.object(r2_6_candidate.json, "loads", return_value=invalid):
            with self.assertRaises(ContractError):
                r2_6_candidate.load_config(CONFIG)

    def test_default_application_path_remains_frozen_r2_5(self):
        self.assertIs(active_pipeline._query_r2_5, engine.query_index)
        self.assertIs(manual_qa.query_index, active_pipeline.query_index)
        self.assertIsNot(r2_6_candidate.query_index, active_pipeline.query_index)


if __name__ == "__main__":
    unittest.main()
