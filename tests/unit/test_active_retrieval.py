import unittest

from app.qa import manual_qa
from app.retrieval import active_pipeline


class ActiveRetrievalPipelineTest(unittest.TestCase):
    def test_application_uses_the_stage_neutral_active_entry_point(self):
        self.assertIs(manual_qa.query_index, active_pipeline.query_index)

    def test_active_entry_point_delegates_without_changing_arguments(self):
        original = active_pipeline._query_r2_5
        calls = []
        try:
            active_pipeline._query_r2_5 = lambda *args: calls.append(args) or {"answerable": False}
            result = active_pipeline.query_index("database", "query", 3, "provider", {"kind": "hybrid-rrf"})
        finally:
            active_pipeline._query_r2_5 = original
        self.assertEqual(result, {"answerable": False})
        self.assertEqual(calls, [("database", "query", 3, "provider", {"kind": "hybrid-rrf"})])


if __name__ == "__main__":
    unittest.main()
