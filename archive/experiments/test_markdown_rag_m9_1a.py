import importlib.util, json, pathlib, sqlite3, tempfile, unittest
from unittest import mock

ROOT=pathlib.Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
BUILD=load("rag_build",ROOT/"scripts/build_markdown_rag_index.py")
QUERY=load("rag_query",ROOT/"scripts/query_markdown_rag.py")
SOURCE=ROOT/"knowledge/manuals/ax17-equipment-manual.md"
QUESTIONS=json.loads((ROOT/"tests/fixtures/rag-m9.1a/questions.json").read_text())["questions"]

class MarkdownRagTest(unittest.TestCase):
    def test_heading_parser_and_stable_ids(self):
        document,chunks=BUILD.parse_manual(SOURCE)
        self.assertEqual(document["document_id"],"AX17-MANUAL-001")
        self.assertEqual([chunk["chunk_id"] for chunk in chunks],["AX17-MANUAL-001#technical-specifications","AX17-MANUAL-001#alarm-e42","AX17-MANUAL-001#maintenance-schedule","AX17-MANUAL-001#reset-procedure"])
        self.assertEqual([chunk["ordinal"] for chunk in chunks],[1,2,3,4])
        self.assertNotIn(str(ROOT),document["source_path"])

    def test_repeat_build_and_queries(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(BUILD,"token_count",side_effect=lambda _b,_m,text:len(text.split())):
            first=pathlib.Path(directory)/"first.sqlite3";second=pathlib.Path(directory)/"second.sqlite3"
            a=BUILD.build_index(SOURCE,first,pathlib.Path("tokenizer"),pathlib.Path("model"));b=BUILD.build_index(SOURCE,second,pathlib.Path("tokenizer"),pathlib.Path("model"))
            self.assertEqual(a["document"],b["document"]);self.assertEqual(a["chunks"],b["chunks"])
            for item in QUESTIONS:
                result=QUERY.query_index(first,item["query"],1)
                if item["expected_chunk_id"] is None:self.assertFalse(result["answerable"]);self.assertEqual(result["results"],[]);self.assertEqual(result["citations"],[])
                else:self.assertTrue(result["answerable"]);self.assertEqual(result["results"][0]["chunk_id"],item["expected_chunk_id"])
            connection=sqlite3.connect(first)
            try:
                paths=[row[0] for row in connection.execute("SELECT source_path FROM documents")]
                citations=[row[0] for row in connection.execute("SELECT citation_json FROM chunks")]
                chunk_ids={row[0] for row in connection.execute("SELECT chunk_id FROM chunks")}
            finally:connection.close()
            self.assertTrue(all(not pathlib.Path(path).is_absolute() for path in paths))
            for raw in citations:
                citation=json.loads(raw);self.assertEqual(citation["document_id"],"AX17-MANUAL-001");self.assertIn(citation["chunk_id"],chunk_ids);self.assertEqual(citation["source"],SOURCE.name)

if __name__=="__main__":unittest.main()
