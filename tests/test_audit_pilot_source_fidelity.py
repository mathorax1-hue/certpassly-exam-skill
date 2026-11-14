import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_pilot_source_fidelity.py"
spec = importlib.util.spec_from_file_location("audit_pilot_source_fidelity", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class SourceFidelityAuditTests(unittest.TestCase):
    def test_whitespace_only_is_not_a_change(self):
        old = {"q001": {"stem": "A   B", "options": ["One"], "answer_raw": ""}}
        new = {"q001": {"stem": "A B", "options": ["One"], "answer_raw": ""}}
        self.assertEqual(audit.compare_split(old, new), [])

    def test_reports_field_level_hashes_without_private_text(self):
        old = {"q001": {"stem": "PRIVATE OWNER TEXT", "options": ["A"], "answer_raw": "A"}}
        new = {"q001": {"stem": "DIFFERENT PRIVATE TEXT", "options": ["B"], "answer_raw": "B"}}
        diffs = audit.compare_split(old, new)
        self.assertEqual({x["field"] for x in diffs}, {"stem", "options", "answer_raw"})
        self.assertTrue(all("PRIVATE" not in json.dumps(x) for x in diffs))
        self.assertFalse(next(x for x in diffs if x["field"] == "answer_raw")["technical_blocked"])

    def test_missing_question_is_blocking(self):
        out = audit.compare_split({"q001": {}}, {})
        self.assertEqual(out[0]["status"], "missing_in_fresh")
        self.assertTrue(out[0]["technical_blocked"])

    def test_v2_inventory_stem_and_media_leak(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / "q001.v1.json").write_text(json.dumps({
                "question_key": "q001", "learner": {"stem": {"format": "html", "text": "Prompt"},
                "interaction": {"options": [{"id": "a", "text": "A"}]}}}), encoding="utf-8")
            (folder / "q002.v1.json").write_text(json.dumps({
                "question_key": "q002", "learner": {"stem": {"text": "Prompt"},
                "media": [{"href": "/media/q002-answer-area.jpg"}]}}), encoding="utf-8")
            result = audit.audit_v2(folder)
            self.assertEqual(result["total"], 2)
            self.assertEqual(len(result["structural_errors"]), 1)
            self.assertEqual(result["structural_errors"][0]["question_key"], "q002")

    def test_blocked_question_is_never_autocleared(self):
        old = {"q001": {"stem": "same", "options": [], "answer_raw": ""}}
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "q001.v1.json"
            f.write_text(json.dumps({"question_key": "q001", "learner":
                {"stem": {"format": "html", "text": "same"}}}), encoding="utf-8")
            r = audit.build_report(old, old, d, ["q001"], expected=1)
            self.assertFalse(r["technical_eligible_all"])
            self.assertEqual(r["status"], "BLOCKED_SOURCE_VERIFICATION")


    def test_documented_supersession_not_mislabeled_as_extraction_bug(self):
        archived_bank = {"questions": [{"question_key": "q001",
            "owner_question_replaced": "q001",
            "created_source": "owner_file slot q001 SUPERSEDED; original",
            "original_editorial_id": "cp-ab900-q001-r1"}]}
        replacements = audit.documented_replacements(archived_bank)
        self.assertEqual(replacements, {"q001": "cp-ab900-q001-r1"})
        old = {"q001": {"stem": "original PDF text", "options": [], "answer_raw": ""}}
        new = {"q001": {"stem": "new editorial content", "options": [], "answer_raw": ""}}
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "q001.v1.json"
            file.write_text(json.dumps({"question_key": "q001",
                "learner": {"stem": {"text": "new editorial content"}}}), encoding="utf-8")
            report = audit.build_report(old, new, d, [], expected=1,
                                        replacements=replacements)
            self.assertEqual(report["documented_replacement_question_count"], 1)
            self.assertEqual(report["unexplained_difference_question_count"], 0)
            self.assertTrue(report["technical_eligible_all"])
            self.assertFalse(report["source_fidelity_independently_verified"])

    def test_replacement_without_provenance_is_not_auto_classified(self):
        bank = {"questions": [{"question_key": "q001",
            "owner_question_replaced": "q001", "original_editorial_id": "x"}]}
        self.assertEqual(audit.documented_replacements(bank), {})

if __name__ == "__main__":
    unittest.main()
