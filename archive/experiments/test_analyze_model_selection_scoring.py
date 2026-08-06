"""Regression tests for blind-review score propagation."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_model_selection.py"
SPEC = importlib.util.spec_from_file_location("analyze_model_selection", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def measured(candidate: str, prompt: str, attempt: int, response: str, response_hash: str) -> dict:
    return {
        "phase": "measured",
        "valid": True,
        "candidate_id": candidate,
        "prompt_id": prompt,
        "attempt": attempt,
        "response_text": response,
        "response_sha256": response_hash,
        "source_record_sha256": f"source-{candidate}-{prompt}-{attempt}",
    }


class BlindAssociationTest(unittest.TestCase):
    def test_shared_answer_propagates_to_all_candidates_and_attempts(self) -> None:
        records = []
        for candidate in ("qwen25", "qwen3"):
            for attempt in range(1, 6):
                records.append(measured(candidate, "J-09", attempt, "READY", "shared-ready"))
        for attempt in range(1, 3):
            records.append(measured("llama32", "J-03", attempt, "variant-a", "variant-a"))
        for attempt in range(3, 6):
            records.append(measured("llama32", "J-03", attempt, "variant-b", "variant-b"))

        rows, associations = MODULE.blind_rows(records)
        shared = next(row for row in rows if row["response_sha256"] == "shared-ready")
        association = associations[shared["review_id"]]

        self.assertEqual(association["candidate_ids"], ["qwen25", "qwen3"])
        self.assertEqual(association["candidate_record_counts"], {"qwen25": 5, "qwen3": 5})
        self.assertEqual(len(association["source_records"]), 10)

        scores = {"shared-ready": 5, "variant-a": 2, "variant-b": 4}
        reviewer_rows = []
        for row in rows:
            reviewer_rows.append({**row, "score_0_to_5": scores[row["response_sha256"]], "rationale": "fixture", "scorer": "fixture", "scored_at_utc": "2026-07-27T00:00:00Z"})

        with tempfile.TemporaryDirectory() as temporary:
            score_a = Path(temporary) / "scorer-a.jsonl"
            score_b = Path(temporary) / "scorer-b.jsonl"
            payload = "".join(json.dumps(row) + "\n" for row in reviewer_rows)
            score_a.write_text(payload, encoding="utf-8")
            score_b.write_text(payload, encoding="utf-8")
            merged = MODULE.merge_scores(rows, associations, score_a, score_b)

        self.assertEqual(merged["status"], "complete")
        self.assertEqual(len(merged["propagated_record_scores"]), 15)
        prompt_scores = {(item["candidate_id"], item["prompt_id"]): item["mean_quality_score_0_to_5"] for item in merged["candidate_prompt_scores"]}
        self.assertEqual(prompt_scores[("qwen25", "J-09")], 5)
        self.assertEqual(prompt_scores[("qwen3", "J-09")], 5)
        self.assertEqual(prompt_scores[("llama32", "J-03")], 3.2)


if __name__ == "__main__":
    unittest.main()
