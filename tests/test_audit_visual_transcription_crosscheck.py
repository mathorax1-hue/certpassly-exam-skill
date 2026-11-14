import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_visual_transcription_crosscheck.py"
spec = importlib.util.spec_from_file_location("audit_visual_transcription_crosscheck", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class TranscriptionTests(unittest.TestCase):
    def doc(self, folder, kind="inline_dropdown", choices=None, prompt="Choose {{blank1}}"):
        value = {"question_key":"q001","version":1,"type":kind,
                 "learner":{"interaction":{"prompt_with_slots":prompt,"slots":[{"id":"blank1","input":"dropdown",
                    "choices":[{"id":"c1","text":"Alpha"},{"id":"c2","text":"Beta"}] if choices is None else choices}]}}}
        Path(folder, "q001.v1.json").write_text(json.dumps(value), encoding="utf-8")

    def test_exact_choices_and_template_consistent_but_not_pdf_approved(self):
        with tempfile.TemporaryDirectory() as d:
            self.doc(d)
            r=audit.inspect({"q001":{"blanks":[["Alpha","Beta"]],"template":"Choose {{blank1}}"}},["q001"],d)
            self.assertEqual(r["ledger_consistent"],1)
            self.assertFalse(r["original_pdf_independently_verified"])
            self.assertEqual(r["status"],"SOURCE_VISUAL_REVIEW_REQUIRED")

    def test_missing_transcription_must_not_pass(self):
        with tempfile.TemporaryDirectory() as d:
            self.doc(d)
            r=audit.inspect({},["q001"],d)
            self.assertEqual(r["review_required"],1)

    def test_modified_option_flags(self):
        with tempfile.TemporaryDirectory() as d:
            self.doc(d)
            r=audit.inspect({"q001":{"blanks":[["Alpha","Gamma"]],"template":"Choose {{blank1}}"}},["q001"],d)
            self.assertIn("dropdown_choice_text_or_count_differ",r["results"][0]["problems"])

    def test_prompt_change_flags(self):
        with tempfile.TemporaryDirectory() as d:
            self.doc(d)
            r=audit.inspect({"q001":{"blanks":[["Alpha","Beta"]],"template":"Choose {{other}}"}},["q001"],d)
            self.assertIn("prompt_template_differ",r["results"][0]["problems"])

    def test_exhibit_always_needs_visual_review(self):
        with tempfile.TemporaryDirectory() as d:
            self.doc(d)
            r=audit.inspect({"q001":{"blanks":[["Alpha","Beta"]],"template":"Choose {{blank1}}","exhibit":"graphic"}},["q001"],d)
            self.assertIn("exhibit_needs_independent_visual_review",r["results"][0]["problems"])

    def test_invalid_key_stops_path_traversal(self):
        r=audit.inspect({},["../secret"],".")
        self.assertEqual(r["results"][0]["status"],"INVALID_KEY")

if __name__ == "__main__":
    unittest.main()
