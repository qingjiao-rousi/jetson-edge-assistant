import importlib.util, pathlib, sys, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"scripts"))
spec=importlib.util.spec_from_file_location("r23",ROOT/"scripts/evaluate_rag_hybrid_m9_1b_r2_3.py")
# The evaluator has a main guard; import it for its pure grid helpers.
mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod)
class T(unittest.TestCase):
 def test_margin_grid_is_exact_nonzero_and_complete(self):
  self.assertEqual(mod.MARGINS,(.0001,.0002,.00025,.0003,.0005,.001,.005));self.assertTrue(all(x>0 for x in mod.MARGINS))
 def test_candidate_count_preserves_vector_and_fact_grid(self):
  base={"kind":"hybrid-rrf","top_k":3,"rrf_k":60,"admission":{},"fact_evidence":{}}
  self.assertEqual(len(list(mod.candidates(base))),63)
if __name__=="__main__":unittest.main()
