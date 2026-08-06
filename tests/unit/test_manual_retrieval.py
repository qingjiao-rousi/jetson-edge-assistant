import unittest
from app.retrieval import engine as R
class T(unittest.TestCase):
 def test_word_boundary_and_phrase(self):self.assertFalse(R.has_phrase("controller","roller"));self.assertTrue(R.has_phrase("inspect every 500 operating hours","operating hours"))
 def test_longest_phrase_wins(self):self.assertEqual(R.english_matches("fluid temperature",("temperature","fluid temperature")),["fluid temperature"])
 def test_fluid_temperature_and_oil_core(self):
  self.assertEqual(R.evidence("fluid temperature", "", "fluid only",set(),set())["core_aligned"],False)
  self.assertTrue(R.evidence("hydraulic fluid viscosity grade", "", "approved hydraulic fluid grade",set(),set())["core_aligned"])
 def test_core_specification_blocks_roller_false_positive(self):
  e=R.evidence("roller specification", "Belt Tracking", "Check roller alignment",set(),set())
  self.assertFalse(e["core_aligned"]);self.assertEqual({x["family"] for x in e["matched_families"]},{"tracking"})
 def test_chinese_maintenance_aligns_to_english_source(self):
  self.assertTrue(R.evidence("CT-4 保养和张力检查周期", "Maintenance Schedule", "Inspect belt tension every 300 operating hours",set(),set())["core_aligned"])
if __name__=="__main__":unittest.main()
