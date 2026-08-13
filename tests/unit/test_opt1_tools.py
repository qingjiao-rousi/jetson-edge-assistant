import importlib.util, json, pathlib, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[2]
def load(name):
 s=importlib.util.spec_from_file_location(name,ROOT/"scripts"/(name+".py")); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
class Opt1ToolsTest(unittest.TestCase):
 def test_prompt_generator_requires_real_assets(self):
  m=load("generate_opt1_prompts")
  with self.assertRaises(FileNotFoundError): m.generate(256,pathlib.Path("/no/tokenizer"),pathlib.Path("/no/model"),pathlib.Path("/tmp/p"))
 def test_matrix_rejects_short_pairs(self):
  m=load("audit_opt1_matrix")
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/"x.jsonl"; p.write_text(json.dumps({"sample_index":1})+"\n")
   with self.assertRaises(ValueError): m.rows(p)
if __name__=="__main__": unittest.main()
