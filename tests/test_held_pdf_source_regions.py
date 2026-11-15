"""Synthetic source-PDF geometry tests; no owner material or answer keys."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import fitz
import numpy as np

from scripts.audit_held_pdf_source_regions import audit


class HeldSourceAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.pdf = root / "synthetic.pdf"
        self.held = root / "held.json"
        image = np.full((290, 985, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (516, 98), (974, 245), (0, 0, 0), 2)
        ok, encoded = cv2.imencode(".png", image)
        self.assertTrue(ok)
        doc = fitz.open()
        page = doc.new_page(width=610, height=820)
        page.insert_text((30, 55), "QUESTION 1")
        page.insert_image(fitz.Rect(30, 70, 520, 214), stream=encoded.tobytes())
        page.insert_text((30, 255), "QUESTION 2")
        page.insert_image(fitz.Rect(30, 270, 520, 414), stream=encoded.tobytes())
        doc.save(str(self.pdf))
        self.good_hash = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        self.held.write_text(json.dumps([
            {"question_key": "q001", "suggested_type": "inline_dropdown"},
            {"question_key": "q002", "suggested_type": "yes_no_matrix"}]))

    def test_each_question_source_image_is_separately_assigned(self):
        result = audit(self.pdf, self.held, self.good_hash)
        self.assertEqual(result["held_count"], 2)
        self.assertEqual(result["held_with_source_images"], 2)
        self.assertEqual(result["pdf_question_markers"], 2)
        self.assertEqual([x["source_image_count"] for x in result["questions"]], [1, 1])
        self.assertEqual(result["questions"][0]["source_images"][0]["pdf_page"], 1)
        self.assertTrue(all(q["original_held"] and not q["publishable"]
                            for q in result["questions"]))

    @patch("scripts.audit_held_pdf_source_regions.subprocess.run")
    def test_ocr_word_tokenizer_records_actual_words(self, mocked):
        mocked.side_effect = [
            SimpleNamespace(stdout=b"Two actual words"),
            SimpleNamespace(stdout=b"Two actual words"),
        ]
        report = audit(self.pdf, self.held, self.good_hash, ocr=True, max_ocr=1)
        self.assertEqual(report["ocr_regions_tested"], 1)
        self.assertEqual(report["ocr_regions_with_pass_agreement"], 1)
        record = next(region for q in report["questions"]
                      for im in q["source_images"] for region in im["candidates"]
                      if "ocr_pass_agreement" in region)
        self.assertEqual(record["ocr_word_counts"], [3, 3])
        self.assertFalse(record["ocr_empty_output"])

    @patch("scripts.audit_held_pdf_source_regions.subprocess.run")
    def test_empty_ocr_cannot_be_counted_as_agreement(self, mocked):
        mocked.return_value = SimpleNamespace(stdout=b"")
        report = audit(self.pdf, self.held, self.good_hash, ocr=True, max_ocr=1)
        self.assertEqual(report["ocr_regions_tested"], 1)
        self.assertEqual(report["ocr_regions_with_pass_agreement"], 0)
        record = next(region for q in report["questions"]
                      for im in q["source_images"] for region in im["candidates"]
                      if "ocr_pass_agreement" in region)
        self.assertTrue(record["ocr_empty_output"])
        self.assertFalse(record["ocr_pass_agreement"])

    def test_source_hash_tampering_refused(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            audit(self.pdf, self.held, "0" * 64)

    def test_duplicate_held_keys_refused(self):
        self.held.write_text(json.dumps([
            {"question_key": "q001"}, {"question_key": "q001"}]))
        with self.assertRaisesRegex(ValueError, "unique"):
            audit(self.pdf, self.held, self.good_hash)

    def test_report_does_not_contain_question_or_answer_text(self):
        report = audit(self.pdf, self.held, self.good_hash)
        text = json.dumps(report)
        self.assertNotIn("QUESTION 1", text)
        self.assertNotIn("answer_key", text)
        self.assertIn("HELD_DIAGNOSTIC_ONLY", text)


if __name__ == "__main__":
    unittest.main()
