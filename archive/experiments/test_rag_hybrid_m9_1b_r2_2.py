import copy,json,pathlib,sys,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
from rag_hybrid_m9_1b import EmbeddingSpec
import rag_hybrid_m9_1b_r2_2 as R
SPEC=EmbeddingSpec(provider="sentence-transformers-local",model_path="models/test-embedding",artifact_path="fixture.bin",model_sha256="a"*64,dimension=4,dtype="float32",normalization="l2",batch_size=4)
class P:
 spec=SPEC
 def embed(self,texts,input_type="document"):
  out=[]
  for t in texts:
   x=t.lower(); v=[float("ax-17" in x),float("bx-9" in x),float("ct-4" in x or "输送" in t),float("e42" in x or "t17" in x)];out.append(v if any(v) else [0,0,0,1])
  return out
def cfg():
 c=json.loads((ROOT/"configs/rag-hybrid-m9.1b-r2.1.json").read_text());c["embedding"]=dict(SPEC.__dict__);c["retrieval"]["admission"]={"minimum_vector_score":0,"minimum_keyword_coverage":0,"minimum_margin":0};return c
class T(unittest.TestCase):
 def build(self):
  d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);db=pathlib.Path(d.name)/"x.db";R.build_index(cfg(),db,P());return db
 def test_generic_words_do_not_pass(self):
  self.assertEqual(R.concept_evidence("hydraulic pump maintenance check", "Technical Specifications", "hydraulic pump",set(),set())["coverage"],0)
 def test_synonym_chinese_and_missing_fact(self):
  db=self.build();r=R.query_index(db,"At what service interval is AX-17 inspection due?",3,P(),cfg()["retrieval"]);self.assertTrue(r["answerable"])
  z=R.query_index(db,"CT-4 维护检查周期是多少小时？",3,P(),cfg()["retrieval"]);self.assertTrue(z["answerable"])
  n=R.query_index(db,"What lubricant viscosity is AX-17 approved for?",3,P(),cfg()["retrieval"]);self.assertFalse(n["answerable"]);self.assertIn("missing_fact_family_evidence",n["admission"]["reasons"])
 def test_cross_device_code_and_metadata(self):
  db=self.build();r=R.query_index(db,"What does E42 mean on CT-4?",3,P(),cfg()["retrieval"]);self.assertFalse(r["answerable"])
  import sqlite3;c=sqlite3.connect(db);m=dict(c.execute("select key,value from index_metadata"));c.close();self.assertEqual(m["algorithm_version"],R.ALGORITHM_VERSION);self.assertEqual(m["concept_lexicon_version"],R.LEXICON_VERSION)
if __name__=="__main__":unittest.main()
