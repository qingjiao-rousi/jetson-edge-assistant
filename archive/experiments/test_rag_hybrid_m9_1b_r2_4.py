import pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"scripts"))
import rag_hybrid_m9_1b_r2_4 as R
class T(unittest.TestCase):
 def test_generic_terms_cannot_evidence(self):self.assertEqual(R.evidence("hydraulic pump maintenance check","Maintenance Schedule","Inspect pump",set(),set())["coverage"],0)
 def test_service_and_chinese_phrase_are_concepts(self):
  self.assertEqual(R.evidence("service interval inspection","Maintenance Schedule","inspection every 500 operating hours",set(),set())["coverage"],1)
  self.assertEqual(R.evidence("维护检查周期运行小时","Maintenance Schedule","Inspect belt tension every 300 operating hours",set(),set())["coverage"],1)
if __name__=="__main__":unittest.main()
