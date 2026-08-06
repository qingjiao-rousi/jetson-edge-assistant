import importlib.util, json, pathlib, sys, tempfile, unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("r25h", ROOT / "scripts/evaluate_rag_hybrid_m9_1b_r2_5_holdout.py")
M = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = M
spec.loader.exec_module(M)


class HoldoutContractTest(unittest.TestCase):
    def artifacts(self, directory):
        root = pathlib.Path(directory)
        frozen = M.FROZEN
        calibration = root / "calibration.json"
        diagnostic = root / "diagnostic.json"
        holdout = root / "holdout.json"
        calibration.write_text(json.dumps({"phase": "CALIBRATION", "status": "CALIBRATED", "quality_gate_result": {"passed": True}, **{key: frozen[key] for key in M.CONTRACT_KEYS}, "question_ids": ["cal"]}))
        diagnostic.write_text(json.dumps({"phase": "DIAGNOSTIC_DEV", "status": "DONE", "quality_gate_result": {"passed": True}, **{key: frozen[key] for key in M.CONTRACT_KEYS}, "quality_metrics": {"questions": [{"id": "dev"}]}}))
        holdout.write_text(json.dumps({"questions": [{"id": "blind", "query": "test", "expected_chunk_id": None}]}))
        return calibration, diagnostic, holdout

    def test_authorization_rejects_failed_evidence_overlap_and_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            calibration, diagnostic, holdout = self.artifacts(directory)
            output = pathlib.Path(directory) / "authorization.json"
            bad = json.loads(calibration.read_text()); bad["status"] = "CALIBRATION_FAILED"; calibration.write_text(json.dumps(bad))
            with self.assertRaisesRegex(Exception, "CALIBRATED"):
                M.authorize(calibration, diagnostic, holdout, output)
            calibration, diagnostic, holdout = self.artifacts(directory)
            overlapping = json.loads(holdout.read_text()); overlapping["questions"][0]["id"] = "cal"; holdout.write_text(json.dumps(overlapping))
            with self.assertRaisesRegex(Exception, "overlap"):
                M.authorize(calibration, diagnostic, holdout, output)
            holdout.write_text(json.dumps({"questions": [{"id": "blind", "query": "test", "expected_chunk_id": None}]}))
            M.authorize(calibration, diagnostic, holdout, output)
            with self.assertRaisesRegex(Exception, "overwrite"):
                M.authorize(calibration, diagnostic, holdout, output)

    def test_authorization_rejects_algorithm_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            calibration, diagnostic, holdout = self.artifacts(directory)
            artifact = json.loads(diagnostic.read_text()); artifact["algorithm_fingerprint"] = "wrong"; diagnostic.write_text(json.dumps(artifact))
            with self.assertRaisesRegex(Exception, "contract mismatch"):
                M.authorize(calibration, diagnostic, holdout, pathlib.Path(directory) / "authorization.json")

    def test_holdout_rejects_sha_change_and_single_consumption(self):
        with tempfile.TemporaryDirectory() as directory:
            calibration, diagnostic, holdout = self.artifacts(directory)
            authorization = pathlib.Path(directory) / "authorization.json"
            result = pathlib.Path(directory) / "result.json"
            M.authorize(calibration, diagnostic, holdout, authorization)
            holdout.write_text(json.dumps({"questions": [{"id": "blind", "query": "changed", "expected_chunk_id": None}]}))
            with self.assertRaisesRegex(Exception, "SHA-256"):
                M.holdout(pathlib.Path(directory) / "missing.sqlite3", holdout, authorization, result)
            holdout.write_text(json.dumps({"questions": [{"id": "blind", "query": "test", "expected_chunk_id": None}]}))
            with mock.patch.object(M, "verify_index"), mock.patch.object(M, "provider_from_config", return_value=object()), mock.patch.object(M, "metrics", return_value={"recall_at_1": 1, "recall_at_3": 1, "mrr": 1, "no_answer_correct_rejection_rate": 1, "false_positive_count": 0, "questions": []}):
                M.holdout(pathlib.Path(directory) / "index.sqlite3", holdout, authorization, result)
            self.assertEqual(M.read(authorization)["execution_state"], "CONSUMED")
            with self.assertRaisesRegex(Exception, "overwrite"):
                M.holdout(pathlib.Path(directory) / "index.sqlite3", holdout, authorization, result)
            result.unlink()
            with self.assertRaisesRegex(Exception, "consumed"):
                M.holdout(pathlib.Path(directory) / "index.sqlite3", holdout, authorization, result)


if __name__ == "__main__":
    unittest.main()
