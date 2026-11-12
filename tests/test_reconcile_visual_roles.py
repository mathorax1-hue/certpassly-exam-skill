"""Synthetic active/superseded image reconciliation tests."""
from __future__ import annotations
import copy
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_visual_roles.py"
spec = importlib.util.spec_from_file_location("reconcile_visual_roles", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SHA = "a" * 64


def fixture():
    return {
        "exam_code": "SYN-100",
        "active_questions": [
            {"id": "q001", "expected_roles": ["question_prompt", "answer_reference"]},
            {"id": "q002", "expected_roles": ["question_prompt"]}
        ],
        "images": [
            {"id": "img1", "owner_question": "q001", "role": "question_prompt",
             "sha256": SHA, "owner_state": "active", "learner_visible": True},
            {"id": "img2", "owner_question": "q001", "role": "answer_reference",
             "sha256": SHA, "owner_state": "active", "learner_visible": False,
             "visual_answer_verified": True, "reviewer_only": True},
            {"id": "img3", "owner_question": "q002", "role": "question_prompt",
             "sha256": SHA, "owner_state": "active", "learner_visible": True},
            {"id": "old", "owner_question": "q999", "role": "answer_reference",
             "sha256": SHA, "owner_state": "superseded", "learner_visible": False}
        ]
    }


class RoleReconciliationTests(unittest.TestCase):
    def reasons(self, d):
        return [e["reason"] for e in mod.reconcile(d)["errors"]]

    def test_synthetic_roles_consistent_but_no_truth_approval(self):
        r = mod.reconcile(fixture())
        self.assertEqual(r["status"], "role_metadata_consistent_pending_independent_review")
        self.assertEqual(r["active_image_count"], 3)
        self.assertEqual(r["superseded_image_count"], 1)
        self.assertFalse(r["pixel_integrity_verified_by_this_tool"])
        self.assertFalse(r["answer_truth_verified_by_this_tool"])

    def test_missing_question_role_blocks(self):
        d = fixture()
        d["images"].pop(1)
        self.assertIn("expected active image role not found: answer_reference", self.reasons(d))

    def test_incorrect_active_owner_blocks(self):
        d = fixture()
        d["images"][0]["owner_question"] = "q999"
        self.assertIn("image owner is not an active question", self.reasons(d))

    def test_superseded_images_are_not_active(self):
        d = fixture()
        d["images"][3]["learner_visible"] = True
        r = mod.reconcile(d)
        self.assertEqual(r["active_image_count"], 3)
        self.assertEqual(r["superseded_image_count"], 1)
        self.assertIn("superseded image exposed to learner", self.reasons(d))

    def test_answer_reference_cannot_leak(self):
        d = fixture()
        d["images"][1]["learner_visible"] = True
        reasons = self.reasons(d)
        self.assertIn("answer-reference image exposed to learner", reasons)
        self.assertIn("reviewer-only image exposed to learner", reasons)

    def test_uncertain_answer_and_duplicate_asset_blocks(self):
        d = fixture()
        d["images"][1]["visual_answer_verified"] = False
        d["images"][1]["id"] = "img1"
        reasons = self.reasons(d)
        self.assertIn("visual answer meaning review still pending", reasons)
        self.assertIn("duplicate image ID", reasons)


if __name__ == "__main__":
    unittest.main()
