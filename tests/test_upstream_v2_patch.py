"""Patch script safety contract; full hotfix tested against pinned checkout in CI."""
import unittest
from scripts.patch_upstream_question_v2 import replace_once, patch_validator, patch_migrator

class PatchBoundaryTests(unittest.TestCase):
    def test_missing_patch_anchor_blocks(self):
        with self.assertRaises(ValueError):
            patch_validator("not the pinned source")
        with self.assertRaises(ValueError):
            patch_migrator("not the pinned source")
    def test_duplicate_anchor_blocks(self):
        with self.assertRaises(ValueError):
            replace_once("xx", "x", "y", "duplicate")
    def test_exact_single_anchor(self):
        self.assertEqual(replace_once("ABC", "B", "x", "single"), "AxC")

if __name__ == "__main__":
    unittest.main()
