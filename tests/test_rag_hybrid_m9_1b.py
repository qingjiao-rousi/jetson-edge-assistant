import copy, importlib.util, json, pathlib, sqlite3, tempfile, sys, unittest
from types import SimpleNamespace
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rag_m9_1b", ROOT / "scripts/rag_hybrid_m9_1b.py")
RAG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RAG
SPEC.loader.exec_module(RAG)
EVAL_SPEC = importlib.util.spec_from_file_location("evaluate_rag_m9_1b", ROOT / "scripts/evaluate_rag_hybrid_m9_1b.py")
EVALUATOR = importlib.util.module_from_spec(EVAL_SPEC)
EVAL_SPEC.loader.exec_module(EVALUATOR)

BASE_CONFIG = json.loads((ROOT / "configs/rag-hybrid-m9.1b.json").read_text())
QUALITY = json.loads((ROOT / "tests/fixtures/rag-m9.1b/quality-set.json").read_text())["questions"]
CALIBRATION = json.loads((ROOT / "tests/fixtures/rag-m9.1b/calibration-set.json").read_text())["questions"]
EVALUATION = json.loads((ROOT / "tests/fixtures/rag-m9.1b/evaluation-set.json").read_text())["questions"]


TEST_SPEC = RAG.EmbeddingSpec(
    provider="sentence-transformers-local", model_path="models/test-embedding", artifact_path="fixture.bin",
    model_sha256="a" * 64, dimension=8, dtype="float32", normalization="l2", batch_size=4,
)


class FixtureProvider:
    """Explicit test double with hand-authored semantic axes; never used for evaluation claims."""
    spec = TEST_SPEC

    def embed(self, texts, input_type="document"):
        vectors = []
        for value in texts:
            lower = value.lower()
            vector = [0.0] * 8
            if "ax-17" in lower or "ax17" in lower or "alarm e42" in lower and "bx-9" not in lower:
                vector[0] += 1.0
            if "bx-9" in lower or "bx9" in lower or "cavitation" in lower or "vapor bubbles" in lower or "gravel-like" in lower:
                vector[1] += 1.0
            if "ct-4" in lower or "ct4" in lower or "t17" in lower or "输送带" in value:
                vector[2] += 1.0
            if "e42" in lower:
                vector[3] += 0.4
            if "reset" in lower or "pressed" in lower or "seconds" in lower or "3 秒" in value:
                vector[4] += 1.0
            if "cavitation" in lower or "vapor bubbles" in lower or "gravel-like" in lower:
                vector[5] += 1.0
            if "t17" in lower or "跑偏" in value:
                vector[6] += 1.0
            if "unknown" in lower or "bearing replacement" in lower or "oil grade" in lower:
                vector[7] += 1.0
            if not any(vector):
                vector[7] = 1.0
            vectors.append(vector)
        return vectors


def test_config():
    config = copy.deepcopy(BASE_CONFIG)
    config["embedding"] = dict(TEST_SPEC.__dict__)
    config["retrieval"] = dict(config["retrieval"])
    config["retrieval"].update(vector_weight=0.7, keyword_weight=0.3, min_final_score=0.35)
    return config


class RagHybridM91BTest(unittest.TestCase):
    def build(self, directory):
        config = test_config()
        database = pathlib.Path(directory) / "index.sqlite3"
        first = RAG.build_index(config, database, FixtureProvider(), token_counter=lambda text: len(text.split()))
        return config, database, first

    def test_multi_document_repeat_build_and_stable_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            config, database, first = self.build(directory)
            second_db = pathlib.Path(directory) / "second.sqlite3"
            second = RAG.build_index(config, second_db, FixtureProvider(), token_counter=lambda text: len(text.split()))
            self.assertEqual(first["documents"], second["documents"])
            self.assertEqual(first["chunks"], second["chunks"])
            self.assertEqual([item["document_id"] for item in first["documents"]], ["AX17-MANUAL-001", "BX9-MANUAL-001", "CT4-MANUAL-001"])
            connection = sqlite3.connect(database)
            try:
                self.assertEqual(connection.execute("SELECT count(*) FROM documents").fetchone()[0], 3)
                citations = [json.loads(row[0]) for row in connection.execute("SELECT citation_json FROM chunks ORDER BY source_order,ordinal")]
            finally:
                connection.close()
            self.assertTrue(all(not pathlib.Path(item["source"]).is_absolute() for item in citations))
            self.assertEqual(len({item["chunk_id"] for item in citations}), len(citations))

    def test_vector_hybrid_order_and_scores(self):
        with tempfile.TemporaryDirectory() as directory:
            config, database, _ = self.build(directory)
            result = RAG.query_index(database, "What condition causes vapor bubbles and unstable pump pressure?", 2, FixtureProvider(), config["retrieval"])
            self.assertTrue(result["answerable"])
            self.assertEqual(result["results"][0]["chunk_id"], "BX9-MANUAL-001#cavitation-warning")
            self.assertGreater(result["results"][0]["vector_score"], 0.9)
            self.assertIn("keyword_score", result["results"][0])
            self.assertIn("final_score", result["results"][0])
            vector_only = dict(config["retrieval"], kind="vector", vector_weight=1.0, keyword_weight=0.0)
            vector_result = RAG.query_index(database, "What condition causes vapor bubbles and unstable pump pressure?", 2, FixtureProvider(), vector_only)
            self.assertEqual(vector_result["mode"], "vector")
            self.assertEqual(vector_result["results"][0]["chunk_id"], "BX9-MANUAL-001#cavitation-warning")
            self.assertEqual(vector_result["results"][0]["keyword_score"], 0.0)

    def test_no_hit_gate_returns_empty_results_and_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            config, database, _ = self.build(directory)
            config["retrieval"] = dict(config["retrieval"], min_final_score=0.99)
            result = RAG.query_index(database, "What hydraulic oil grade is approved for AX-17?", 3, FixtureProvider(), config["retrieval"])
            self.assertFalse(result["answerable"])
            self.assertEqual(result["results"], [])
            self.assertEqual(result["citations"], [])
            self.assertIsNotNone(result["top_candidate_score"])

    def test_duplicate_identity_order_and_hash_are_rejected(self):
        config = test_config()
        duplicate_id = copy.deepcopy(config)
        duplicate_id["sources"][1]["document_id"] = duplicate_id["sources"][0]["document_id"]
        with self.assertRaisesRegex(RAG.ContractError, "duplicate configured document_id"):
            RAG.load_documents(duplicate_id)
        with self.assertRaises(RAG.ContractError):
            RAG.load_documents(dict(config, sources=list(reversed(config["sources"]))))
        bad_hash = copy.deepcopy(config)
        bad_hash["sources"][1]["content_sha256"] = "0" * 64
        with self.assertRaises(RAG.ContractError):
            RAG.load_documents(bad_hash)
        duplicate_hash = copy.deepcopy(config)
        duplicate_hash["sources"][1]["content_sha256"] = duplicate_hash["sources"][0]["content_sha256"]
        with self.assertRaisesRegex(RAG.ContractError, "duplicate document content hash"):
            RAG.load_documents(duplicate_hash)
        unsafe = copy.deepcopy(config)
        unsafe["sources"][0]["source_path"] = "../secret.md"
        with self.assertRaises(RAG.ContractError):
            RAG.load_documents(unsafe)

    def test_dimension_and_corrupt_index_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            config, database, _ = self.build(directory)
            wrong_provider = FixtureProvider()
            wrong_provider.spec = RAG.EmbeddingSpec(**dict(TEST_SPEC.__dict__, dimension=7))
            with self.assertRaises(RAG.ContractError):
                RAG.query_index(database, "alarm E42", 1, wrong_provider, config["retrieval"])
            connection = sqlite3.connect(database)
            connection.execute("UPDATE chunk_embeddings SET vector = X'00' WHERE chunk_id = (SELECT chunk_id FROM chunks LIMIT 1)")
            connection.commit(); connection.close()
            with self.assertRaises(RAG.ContractError):
                RAG.query_index(database, "alarm E42", 1, FixtureProvider(), config["retrieval"])

    def test_real_provider_reports_missing_asset_without_network(self):
        config = copy.deepcopy(BASE_CONFIG)
        for key in ("repository", "revision", "license", "model_size_bytes", "model_sha256", "xet_hash"):
            config["embedding"][key] = None
        with mock.patch("socket.create_connection", side_effect=AssertionError("network attempted")) as connection:
            with self.assertRaises(RAG.ProviderUnavailable) as error:
                RAG.provider_from_config(config)
        connection.assert_not_called()
        self.assertIn("unfrozen GGUF asset metadata", str(error.exception))

    def test_llama_cpp_provider_freezes_cli_and_instruction_fingerprint(self):
        spec = RAG.EmbeddingSpec(
            provider="llama-cpp-gguf", binary_path="third_party/llama.cpp-omni/build-jetson-release/bin/llama-embedding",
            model_id="Qwen/Qwen3-Embedding-0.6B", repository="Qwen/fixture", revision="fixture-revision", license="apache-2.0",
            model_path="models/embedding/Qwen3-Embedding-0.6B-Q8_0.gguf", artifact_path="Qwen3-Embedding-0.6B-Q8_0.gguf",
            model_size_bytes=pathlib.Path("/bin/true").stat().st_size, model_sha256="b" * 64, xet_hash="c" * 64,
            dimension=1024, dtype="float32", normalization="l2", batch_size=8,
            quantization="Q8_0", pooling="last", query_template="Instruct: industrial retrieval\nQuery: {text}", document_template="{text}",
        )
        captured = {}
        def run(command, **_kwargs):
            captured["command"] = command
            captured["input"] = pathlib.Path(command[command.index("--file") + 1]).read_text()
            return SimpleNamespace(returncode=0, stdout=json.dumps([[1.0] + [0.0] * 1023]), stderr="")
        with mock.patch.object(RAG, "safe_repo_file", return_value=pathlib.Path("/bin/true")), mock.patch.object(RAG, "sha256_file", return_value="b" * 64), mock.patch("os.access", return_value=True), mock.patch.object(RAG.subprocess, "run", side_effect=run):
            provider = RAG.LlamaCppGgufProvider(spec)
            vector = provider.embed(["pump alarm"], "query")[0]
        self.assertEqual(len(vector), 1024)
        self.assertEqual(captured["input"], "Instruct: industrial retrieval\nQuery: pump alarm")
        self.assertEqual(captured["command"][captured["command"].index("--pooling") + 1], "last")
        self.assertEqual(captured["command"][captured["command"].index("--embd-normalize") + 1], "2")
        changed = RAG.EmbeddingSpec(**dict(spec.__dict__, query_template="Instruct: changed\nQuery: {text}"))
        self.assertNotEqual(spec.fingerprint, changed.fingerprint)

    def test_quality_set_is_fixed_and_covers_required_boundaries(self):
        combined = CALIBRATION + EVALUATION
        categories = {item["category"] for item in QUALITY + combined}
        self.assertTrue({"multi-document-routing", "synonym-rewrite", "exact-fault-code", "similar-device-distractor", "chinese-boundary", "english-boundary", "explicit-no-answer"} <= categories)
        self.assertEqual(len(combined), 24)
        self.assertFalse({item["id"] for item in CALIBRATION} & {item["id"] for item in EVALUATION})
        self.assertGreaterEqual(sum(not item["answerable"] for item in combined) / len(combined), 0.25)

    def test_done_quality_gate_is_explicit_and_fails_closed(self):
        passing = {
            "recall_at_1": 0.75, "recall_at_3": 0.875, "mrr": 0.8,
            "no_answer_correct_rejection_rate": 0.75, "false_positive_count": 1,
        }
        self.assertTrue(EVALUATOR.quality_gate_result(passing)["passed"])
        for key, value in (
            ("recall_at_1", 0.749), ("recall_at_3", 0.874), ("mrr", 0.799),
            ("no_answer_correct_rejection_rate", 0.749), ("false_positive_count", 2),
        ):
            failing = dict(passing, **{key: value})
            self.assertFalse(EVALUATOR.quality_gate_result(failing)["passed"], key)


if __name__ == "__main__":
    unittest.main()
