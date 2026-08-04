import copy
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rag_hybrid_m9_1b import EmbeddingSpec
import rag_hybrid_m9_1b_r2 as R2
import evaluate_rag_hybrid_m9_1b_r2 as EVALUATOR

SPEC = EmbeddingSpec(provider="sentence-transformers-local", model_path="models/test-embedding", artifact_path="fixture.bin", model_sha256="a" * 64, dimension=4, dtype="float32", normalization="l2", batch_size=4)


class Provider:
    spec = SPEC
    def embed(self, texts, input_type="document"):
        result = []
        for text in texts:
            lower = text.lower()
            value = [1.0 if "ax-17" in lower else 0.0, 1.0 if "bx-9" in lower else 0.0, 1.0 if "ct-4" in lower or "输送" in text else 0.0, 1.0 if "e42" in lower or "t17" in lower else 0.0]
            result.append(value if any(value) else [0.0, 0.0, 0.0, 1.0])
        return result


def config():
    value = json.loads((ROOT / "configs/rag-hybrid-m9.1b-r2.json").read_text())
    value["embedding"] = dict(SPEC.__dict__)
    return value


class R2Test(unittest.TestCase):
    def build(self):
        directory = tempfile.TemporaryDirectory(); database = pathlib.Path(directory.name) / "index.sqlite3"
        R2.build_index(config(), database, Provider())
        return directory, database

    def test_structured_text_and_metadata_are_fingerprinted(self):
        directory, database = self.build()
        self.addCleanup(directory.cleanup)
        connection = __import__("sqlite3").connect(database)
        try:
            text = connection.execute("SELECT structured_text FROM chunks WHERE chunk_id='AX17-MANUAL-001#maintenance-schedule'").fetchone()[0]
            metadata = dict(connection.execute("SELECT key,value FROM index_metadata"))
        finally: connection.close()
        self.assertIn("Document: AX-17 Industrial Compressor Manual", text)
        self.assertIn("Device: AX-17", text)
        self.assertIn("Section: Maintenance Schedule", text)
        self.assertEqual(metadata["text_format_version"], "structured-v1")
        self.assertEqual(metadata["chinese_fts_strategy"], "unicode61-cjk-bigram-v1")

    def test_device_and_fault_are_hard_constraints(self):
        directory, database = self.build(); self.addCleanup(directory.cleanup)
        result = R2.query_index(database, "What does E42 mean on AX-17?", 3, Provider(), config()["retrieval"])
        self.assertEqual({item["device_id"] for item in result["results"]}, {"AX-17"})
        missing = R2.query_index(database, "CT-4 E42 故障码表示什么？", 3, Provider(), config()["retrieval"])
        self.assertFalse(missing["answerable"])
        self.assertEqual(missing["results"], [])
        self.assertIn("no_candidate_satisfies_hard_constraints", missing["admission"]["reasons"])

    def test_chinese_bigrams_are_not_silently_discarded(self):
        directory, database = self.build(); self.addCleanup(directory.cleanup)
        result = R2.query_index(database, "CT-4 输送带跑偏 T17", 3, Provider(), config()["retrieval"])
        self.assertGreater(result["admission"]["keyword_coverage"], 0.0)

    def test_failed_calibration_cannot_authorize_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "failed.json"
            path.write_text(json.dumps({"status": "CALIBRATION_FAILED"}), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "CALIBRATION_FAILED"):
                EVALUATOR.run_holdout(config(), pathlib.Path(directory) / "none.sqlite3", ROOT / "tests/fixtures/rag-m9.1b-r2/holdout-set.json", path)


if __name__ == "__main__": unittest.main()
