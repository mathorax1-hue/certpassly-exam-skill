import copy
import json
import unittest
from pathlib import Path

from certpassly.evidence import audit_bank, audit_file

FIXTURES = Path(__file__).parent / "fixtures"


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.good = json.loads((FIXTURES / "structurally-complete-synthetic.json").read_text())

    def reasons(self, data):
        return [x["reason"] for x in audit_bank(data)["blockers"]]

    def test_valid_structure_is_not_called_released(self):
        report = audit_bank(self.good)
        self.assertEqual(report["status"], "evidence_ready_for_independent_gate")
        self.assertIn("not verify", report["warning"])
        self.assertEqual(report["blocker_count"], 0)

    def test_realistic_pending_review_is_blocked(self):
        report = audit_file(FIXTURES / "pending-review.json")
        self.assertEqual(report["status"], "blocked")
        self.assertGreaterEqual(report["blocker_count"], 4)

    def test_unverified_question_blocks(self):
        d = copy.deepcopy(self.good)
        d["questions"][0]["accuracy_status"] = "key_could_not_be_checked"
        self.assertIn("answer key not verified against current official documentation", self.reasons(d))

    def test_human_review_pending_blocks(self):
        d = copy.deepcopy(self.good)
        d["questions"][0]["human_review_required"] = True
        self.assertIn("independent question review pending", self.reasons(d))

    def test_reference_image_answer_not_checked_blocks(self):
        d = copy.deepcopy(self.good)
        d["media"][0]["answer_verified"] = False
        self.assertIn("visual answer reference not verified", self.reasons(d))

    def test_reviewer_image_leak_blocks(self):
        d = copy.deepcopy(self.good)
        d["media"][0]["in_learner_payload"] = True
        reasons = self.reasons(d)
        self.assertIn("reviewer-only asset exposed to learner", reasons)
        self.assertIn("answer-reference image exposed to learner", reasons)

    def test_unapproved_image_blocks(self):
        d = copy.deepcopy(self.good)
        d["media"][0]["approved_for_release"] = False
        self.assertIn("visual asset not approved", self.reasons(d))

    def test_official_url_must_not_be_fake_suffix(self):
        d = copy.deepcopy(self.good)
        d["questions"][0]["evidence"][0]["url"] = "https://learn.microsoft.com.attacker.example/"
        self.assertIn("no structurally valid official answer-support evidence", self.reasons(d))

    def test_source_sha_not_optional(self):
        d = copy.deepcopy(self.good)
        d["questions"][0]["evidence"][0]["saved_page_sha256"] = "abc"
        self.assertIn("no structurally valid official answer-support evidence", self.reasons(d))

    def test_duplicate_ids_block(self):
        d = copy.deepcopy(self.good)
        d["questions"].append(copy.deepcopy(d["questions"][0]))
        self.assertIn("duplicate question ID", self.reasons(d))

    def test_no_domain_allowlist_blocks(self):
        d = copy.deepcopy(self.good)
        d["official_domains"] = []
        self.assertIn("official_domains must include vendor-owned domain(s)", self.reasons(d))


if __name__ == "__main__":
    unittest.main()
