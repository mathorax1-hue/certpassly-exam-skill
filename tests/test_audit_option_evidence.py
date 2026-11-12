"""Synthetic option and image-order audit tests. No real exam content."""
from __future__ import annotations
import copy
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_option_evidence.py"
spec = importlib.util.spec_from_file_location("audit_option_evidence", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SHA = "a" * 64


def example():
    def source():
        return {
            "url": "https://learn.microsoft.com/en-us/example",
            "sha256": SHA,
            "quote": "This is synthetic test evidence.",
            "capture_mode": "downloaded",
        }
    return {
        "exam_code": "SYN-100", "official_hosts": ["learn.microsoft.com"],
        "questions": [{
            "id": "q001",
            "options": [{"id": "A", "text": "Synthetic yes"},
                        {"id": "B", "text": "Synthetic no"}],
            "option_order": ["A", "B"],
            "selected_option_ids": ["A"],
            "option_reviews": [
                {"option_id": "A", "verdict": "supported", "rationale": "Synthetic support", "sources": [source()]},
                {"option_id": "B", "verdict": "contradicted", "rationale": "Synthetic refutation", "sources": [source()]},
            ],
        }]
    }


class DossierAuditTests(unittest.TestCase):
    def reasons(self, data):
        return [x["reason"] for x in mod.audit_dossier(data)["blockers"]]

    def test_complete_synthetic_structure_is_not_approved(self):
        r = mod.audit_dossier(example())
        self.assertEqual(r["status"], "structurally_documented_for_independent_review")
        self.assertFalse(r["human_review_approved"])
        self.assertFalse(r["release_approved"])

    def test_each_option_must_be_reviewed_in_order(self):
        d = example()
        d["questions"][0]["option_reviews"].reverse()
        self.assertIn("each option must be reviewed in original order", self.reasons(d))

    def test_missing_distractor_and_wrong_selected_key_are_blocked(self):
        d = example()
        d["questions"][0]["option_reviews"].pop()
        d["questions"][0]["selected_option_ids"] = ["B"]
        self.assertGreater(mod.audit_dossier(d)["blocker_count"], 0)

    def test_cannot_bypass_fake_approval_flags(self):
        d = example()
        d["questions"][0]["human_review_approved"] = True
        d["questions"][0]["release_approved"] = True
        r = mod.audit_dossier(d)
        self.assertFalse(r["human_review_approved"])
        self.assertFalse(r["release_approved"])

    def test_source_hash_and_allowlist_requirements(self):
        d = example()
        d["questions"][0]["option_reviews"][1]["sources"][0]["url"] = "https://learn.microsoft.com.attacker.test"
        d["questions"][0]["option_reviews"][0]["sources"][0]["sha256"] = "bad"
        reasons = self.reasons(d)
        self.assertTrue(any("unallowlisted source URL" in x for x in reasons))
        self.assertTrue(any("source SHA-256 missing" in x for x in reasons))

    def test_offline_source_and_uncertainty_block(self):
        d = example()
        d["questions"][0]["option_reviews"][0]["sources"][0]["capture_mode"] = "local_file_unverified_origin"
        d["questions"][0]["option_reviews"][1]["verdict"] = "uncertain"
        reasons = self.reasons(d)
        self.assertTrue(any("download provenance" in x for x in reasons))
        self.assertTrue(any("uncertainty" in x for x in reasons))

    def test_visual_rows_preserve_exact_order(self):
        d = example()
        d["questions"][0]["visual"] = {
            "question_prompt_sha256": SHA,
            "answer_reference_sha256": SHA,
            "original_row_order": ["r1", "r2"],
            "reviewed_row_order": ["r1", "r2"],
            "obscured_answer": False,
            "image_meaning_reviewed": True
        }
        self.assertEqual(mod.audit_dossier(d)["blocker_count"], 0)
        d["questions"][0]["visual"]["reviewed_row_order"].reverse()
        self.assertIn("visual row order not reviewed exactly", self.reasons(d))
        d["questions"][0]["visual"]["obscured_answer"] = True
        self.assertIn("obscured visual answers cannot be inferred", self.reasons(d))

    def test_duplicate_questions_and_options_fail(self):
        d = example()
        d["questions"].append(copy.deepcopy(d["questions"][0]))
        d["questions"][0]["options"][1]["id"] = "A"
        reasons = self.reasons(d)
        self.assertIn("duplicate question ID", reasons)
        self.assertIn("option IDs missing or duplicate", reasons)


if __name__ == "__main__":
    unittest.main()
