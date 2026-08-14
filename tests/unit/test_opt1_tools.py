import importlib.util,json,pathlib,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[2]
def load(name):
 s=importlib.util.spec_from_file_location(name,ROOT/"scripts"/(name+".py"));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def row(index,prompt,hit=0,text="same"):
 return {"sample_index":index,"client_http_status":200,"error":None,"text":text,"prompt_tokens":prompt,"output_tokens":2,"finish_reason":"stop","metrics":{"cache_hit_tokens":hit,"cache_miss_tokens":prompt-hit,"prefill_ms":1,"ttft_ms":2,"total_ms":3,"decode_tokens_per_second":4}}
def write_pair(directory,prompt,hot_hits,text="same"):
 paths=[]
 for mode,hits in (("disabled",[0]*30),("single-hot",hot_hits)):
  p=directory/f"run-{mode}.jsonl";p.write_text("\n".join(json.dumps(row(i,prompt,hits[i-1],text)) for i in range(1,31)))
  p.with_suffix("").with_name(p.with_suffix("").name+"-environment.txt").write_text("batch_tokens=512\n")
  paths.append(p)
 return paths
class Opt1ToolsTest(unittest.TestCase):
 def test_prompt_generator_requires_real_assets(self):
  with self.assertRaises(FileNotFoundError):load("generate_opt1_prompts").generate(256,pathlib.Path("/no/tokenizer"),pathlib.Path("/no/model"),pathlib.Path("/tmp/p"))
 def test_below_batch_zero_hit_is_expected_no_reuse(self):
  with tempfile.TemporaryDirectory() as td:
   d,h=write_pair(pathlib.Path(td),264,[0]*30);r=load("audit_opt1_matrix").audit(d,h)
   self.assertEqual(r["classification"],"PASS_EXPECTED_NO_REUSE");self.assertEqual(r["hit_statistics"]["zero_hit_requests"],30)
 def test_eligible_prompt_without_hit_fails(self):
  with tempfile.TemporaryDirectory() as td:
   d,h=write_pair(pathlib.Path(td),520,[0]*30);r=load("audit_opt1_matrix").audit(d,h)
   self.assertEqual(r["classification"],"FAIL");self.assertEqual(r["failures"][0]["rule"],"eligible_prompt_has_no_reuse")
 def test_cross_mode_output_mismatch_fails(self):
  with tempfile.TemporaryDirectory() as td:
   d,h=write_pair(pathlib.Path(td),520,[512]*30);data=[json.loads(x) for x in h.read_text().splitlines()];data[5]["text"]="different";h.write_text("\n".join(json.dumps(x) for x in data));r=load("audit_opt1_matrix").audit(d,h)
   self.assertEqual(r["classification"],"FAIL");self.assertEqual(r["failures"][0]["index"],6);self.assertEqual(r["failures"][0]["rule"],"text_mismatch")
 def test_soak_disabled_rejects_hit(self):
  raw={"status":"UNREVIEWED_RAW_RESULT","worktree_clean":True,"clock_locked":True,"mode":"disabled","warmup":{"client_http_status":200,"error":None},"requests":[{"text_sha256":"a","response":row(1,520,1)}],"telemetry":{}}
  self.assertIn("disabled_nonzero_hit",load("audit_opt1_soak").audit(raw)["fail_reasons"])
if __name__=="__main__":unittest.main()
