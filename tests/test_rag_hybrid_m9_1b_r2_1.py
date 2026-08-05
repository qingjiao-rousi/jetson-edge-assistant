import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from rag_hybrid_m9_1b import EmbeddingSpec
import rag_hybrid_m9_1b_r2_1 as R21

SPEC = EmbeddingSpec(provider="sentence-transformers-local", model_path="models/test-embedding", artifact_path="fixture.bin", model_sha256="a" * 64, dimension=4, dtype="float32", normalization="l2", batch_size=4)


class Provider:
    spec = SPEC
    def embed(self, texts, input_type="document"):
        vectors = []
        for text in texts:
            lower = text.lower()
            value = [float("ax-17" in lower), float("bx-9" in lower), float("ct-4" in lower or "输送" in text), float("e42" in lower or "t17" in lower)]
            vectors.append(value if any(value) else [0.0, 0.0, 0.0, 1.0])
        return vectors


def config():
    value = json.loads((ROOT / "configs/rag-hybrid-m9.1b-r2.1.json").read_text())
    value["embedding"] = dict(SPEC.__dict__)
    value["retrieval"]["admission"] = {"minimum_vector_score": 0.0, "minimum_keyword_coverage": 0.0, "minimum_margin": 0.0}
    value["retrieval"]["fact_evidence"] = {"minimum_coverage": 0.25, "minimum_terms": 1}
    return value


class R21Test(unittest.TestCase):
    def build(self):
        directory = tempfile.TemporaryDirectory(); database = pathlib.Path(directory.name) / "index.sqlite3"
        R21.build_index(config(), database, Provider())
        self.addCleanup(directory.cleanup)
        return database

    def test_identifiers_do_not_count_as_fact_evidence(self):
        terms = R21.fact_terms("Does AX-17 E42 specify lubricant viscosity?", {"AX-17"}, {"E42"})
        self.assertNotIn("ax", terms); self.assertNotIn("17", terms); self.assertNotIn("e42", terms)
        self.assertIn("lubricant", terms); self.assertIn("viscosity", terms)

    def test_missing_fact_evidence_returns_no_citation(self):
        response = R21.query_index(self.build(), "What lubricant viscosity is required by AX-17?", 3, Provider(), config()["retrieval"])
        self.assertFalse(response["answerable"])
        self.assertEqual(response["results"], [])
        self.assertEqual(response["citations"], [])
        self.assertIn("missing_fact_evidence", response["admission"]["reasons"])

    def test_device_fault_and_chinese_evidence(self):
        database = self.build()
        missing = R21.query_index(database, "CT-4 E42 故障码表示什么？", 3, Provider(), config()["retrieval"])
        self.assertFalse(missing["answerable"])
        accepted = R21.query_index(database, "CT-4 输送带跑偏 T17", 3, Provider(), config()["retrieval"])
        self.assertTrue(accepted["answerable"])
        self.assertGreater(accepted["admission"]["fact_evidence"]["coverage"], 0.0)

    def test_index_metadata_binds_algorithm_and_gate(self):
        database = self.build(); connection = sqlite3.connect(database)
        try: metadata = dict(connection.execute("SELECT key,value FROM index_metadata"))
        finally: connection.close()
        self.assertEqual(metadata["algorithm_version"], "fact-evidence-v1")
        self.assertIn("minimum_coverage", metadata["fact_evidence_config"])
        self.assertEqual(len(metadata["r2_1_index_fingerprint"]), 64)

    def test_incompatible_algorithm_index_is_rejected(self):
        database = self.build(); connection = sqlite3.connect(database)
        try:
            connection.execute("UPDATE index_metadata SET value='wrong-version' WHERE key='algorithm_version'"); connection.commit()
        finally: connection.close()
        with self.assertRaisesRegex(Exception, "algorithm version mismatch"):
            R21.query_index(database, "AX-17 pressure", 3, Provider(), config()["retrieval"])


if __name__ == "__main__": unittest.main()
