import importlib.util,json,pathlib,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[2]
def load(name):
 s=importlib.util.spec_from_file_location(name,ROOT/"scripts"/(name+".py"));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def row(index,hit=0,text="same",status=200):
 return {"sample_index":index,"client_http_status":status,"error":None,"text":text,"prompt_tokens":709,"output_tokens":2,"finish_reason":"stop","metrics":{"cache_hit_tokens":hit,"cache_miss_tokens":709-hit,"prefill_ms":1,"ttft_ms":2,"total_ms":3,"decode_tokens_per_second":4}}
class Opt1ToolsTest(unittest.TestCase):
 def test_prompt_generator_requires_real_assets(self):
  with self.assertRaises(FileNotFoundError):load("generate_opt1_prompts").generate(256,pathlib.Path("/no/tokenizer"),pathlib.Path("/no/model"),pathlib.Path("/tmp/p"))
 def test_matrix_reports_failing_row(self):
  m=load("audit_opt1_matrix")
  with tempfile.TemporaryDirectory() as d:
   d=pathlib.Path(d);a=d/"d";b=d/"h";a.write_text("\n".join(json.dumps(row(i)) for i in range(1,31)));b.write_text("\n".join(json.dumps(row(i,0 if i==7 else 512)) for i in range(1,31)))
   r=m.audit(a,b);self.assertEqual(r["status"],"FAIL");self.assertEqual(r["failures"][0]["index"],7);self.assertEqual(r["failures"][0]["rule"],"hot_measurement_has_no_hit")
 def test_soak_rejects_dirty_dynamic_and_nondeterministic_output(self):
  raw={"status":"UNREVIEWED_RAW_RESULT","worktree_clean":False,"clock_locked":False,"mode":"single_hot_text","warmup":{"client_http_status":200,"error":None},"requests":[{"text_sha256":"a","response":row(1,512)},{"text_sha256":"b","response":row(2,512)}],"telemetry":{}}
  r=load("audit_opt1_soak").audit(raw);self.assertEqual(r["status"],"FAIL");self.assertIn("dirty_or_dynamic_clock",r["fail_reasons"]);self.assertIn("output_not_deterministic",r["fail_reasons"])
 def test_soak_disabled_rejects_hit(self):
  raw={"status":"UNREVIEWED_RAW_RESULT","worktree_clean":True,"clock_locked":True,"mode":"disabled","warmup":{"client_http_status":200,"error":None},"requests":[{"text_sha256":"a","response":row(1,1)}],"telemetry":{}}
  self.assertIn("disabled_nonzero_hit",load("audit_opt1_soak").audit(raw)["fail_reasons"])
if __name__=="__main__":unittest.main()
