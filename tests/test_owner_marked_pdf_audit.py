"""Synthetic complete-PDF source-key candidate audit tests."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import fitz
import numpy as np

from scripts.audit_owner_marked_dropdown_candidates import audit


class SourceMarkedKeyAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.pdf = root / "synthetic.pdf"
        self.held = root / "held.json"
        picture = np.full((180, 620, 3), 255, np.uint8)
        _, blob = cv2.imencode(".png", picture)
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((40, 90), "QUESTION 43", rotate=90)
        page.insert_image(fitz.Rect(105, 105, 250, 280), stream=blob.tobytes())
        page.insert_image(fitz.Rect(270, 105, 370, 280), stream=blob.tobytes())
        page.insert_text((400, 430), "QUESTION 44", rotate=90)
        page.insert_image(fitz.Rect(455, 455, 600, 655), stream=blob.tobytes())
        page.set_rotation(90)
        doc.save(str(self.pdf))
        self.source_sha = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        self.held.write_text(json.dumps([
            {"question_key": "q043"},
            {"question_key": "q044"},
        ]))

    @patch("scripts.audit_owner_marked_dropdown_candidates.recover")
    def test_unpaired_item_stays_unapproved(self, mocked):
        mocked.return_value = {"status": "OWNER_MARK_CANDIDATE_VERIFIED",
                               "selected_label": "synthetic",
                               "release_approved": False}
        result = audit(self.pdf, self.held, self.source_sha)
        self.assertEqual(result["held_count"], 2)
        self.assertEqual(result["candidate_count"], 1)
        records = {q["question_key"]: q for q in result["questions"]}
        self.assertEqual(records["q044"]["status"], "HELD_NOT_EXACTLY_TWO_IMAGES")
        self.assertFalse(records["q044"]["release_approved"])
        self.assertTrue(all(q["release_approved"] is False
                            for q in result["questions"]))
        self.assertTrue(result["all_held"])

    def test_changed_source_is_refused(self):
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            audit(self.pdf, self.held, "0" * 64)

    def test_duplicate_keys_are_refused(self):
        self.held.write_text(json.dumps([
            {"question_key": "q043"}, {"question_key": "q043"}]))
        with self.assertRaisesRegex(ValueError, "unique"):
            audit(self.pdf, self.held, self.source_sha)


if __name__ == "__main__":
    unittest.main()
