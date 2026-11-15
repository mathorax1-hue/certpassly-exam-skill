"""Contract tests for patching the one canonical upstream visual classifier."""
import tempfile
import unittest
from pathlib import Path
from scripts.patch_upstream_visual_classification import (
    EXPECTED_OLD, OLD_INIT, OLD_LINES, NEW, patch,
)

class VisualClassifierPatchTests(unittest.TestCase):
    def test_yes_no_headers_are_corrob_source_evidence(self):
        scope = {}
        exec(NEW, scope)
        classify = scope["kind_of"]
        self.assertEqual(classify("HOTSPOT", [
            {"text": "Statements"}, {"text": "Yes"}, {"text": "No"}
        ]), "yes_no")

    def test_answer_area_heading_alone_must_not_force_dropdown(self):
        scope = {}
        exec(NEW, scope)
        self.assertEqual(scope["kind_of"]("HOTSPOT Answer Area", [
            {"text": "Answer Area"}, {"text": "Control"}
        ]), "unknown")

    def test_dropdown_instruction_on_image_recognized(self):
        scope = {}
        exec(NEW, scope)
        self.assertEqual(scope["kind_of"]("HOTSPOT", [
            {"text": "Select the answer that correctly completes the sentence."}
        ]), "dropdown")

    def test_unrelated_choices_are_not_guessed(self):
        scope = {}
        exec(NEW, scope)
        self.assertEqual(scope["kind_of"]("Choose the correct one", [
            {"text": "A"}, {"text": "B"}
        ]), "unknown")

    def test_patch_idempotent_with_exact_original_contract(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/"analyze_visual.py"
            target.write_text(EXPECTED_OLD+"\n"+OLD_INIT+"\n"+OLD_LINES+"\n")
            self.assertEqual(patch(target), "patched")
            after=target.read_text()
            self.assertIn("d['kind'] = kind_of(r.get('stem') or '', L)", after)
            self.assertEqual(patch(target), "already_patched")
            self.assertEqual(target.read_text(), after)

    def test_unrecognized_upstream_does_not_get_patched(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/"analyze_visual.py"
            target.write_text("def kind_of(x): return 'single_choice'\n")
            with self.assertRaisesRegex(ValueError,"Refusing unsupported upstream"):
                patch(target)

if __name__ == "__main__":
    unittest.main()
