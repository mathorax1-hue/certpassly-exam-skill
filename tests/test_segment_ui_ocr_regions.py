"""Synthetic tests for OCR region isolation. No private PDF/image content."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from scripts.segment_ui_ocr_regions import process, regions


class UIRegionTests(unittest.TestCase):
    def test_dropdown_box_detected_without_guessing_answer(self):
        image = np.full((290, 985, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (516, 98), (974, 245), (0, 0, 0), 2)
        cv2.putText(image, "Example choice", (525, 132),
                    cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1)
        found = [r for r in regions(image) if r["kind"] == "enclosed_text_control"]
        self.assertEqual(len(found), 1)
        x1, y1, x2, y2 = found[0]["bbox"]
        self.assertGreater(x1, 516)
        self.assertGreater(y1, 98)
        self.assertLess(x2, 974)
        self.assertLess(y2, 245)

    def test_matrix_statement_column_without_answer_inference(self):
        image = np.full((240, 973, 3), 255, dtype=np.uint8)
        for x in (830, 954):
            for y in (93, 156, 219):
                cv2.circle(image, (x, y), 7, (120, 120, 120), 2)
        for y in (93, 156, 219):
            cv2.putText(image, "Example statement", (50, y),
                        cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 0, 0), 1)
        found = [r for r in regions(image) if r["kind"] == "matrix_statement_column"]
        self.assertEqual(len(found), 1)
        self.assertLess(found[0]["bbox"][2], 830)
        self.assertNotIn("answer_key", json.dumps(found))

    def test_empty_image_has_no_invented_regions(self):
        image = np.full((220, 450, 3), 255, dtype=np.uint8)
        self.assertEqual(regions(image), [])

    def test_private_crop_hash_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "synthetic.png"
            image = np.full((290, 985, 3), 255, dtype=np.uint8)
            cv2.rectangle(image, (516, 98), (974, 245), (0, 0, 0), 2)
            cv2.imwrite(str(source), image)
            report = process(source, root / "private")
            self.assertEqual(report["source_image_sha256"],
                             hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(len(report["regions"]), 1)
            self.assertEqual(report["status"],
                             "PRIVATE_DIAGNOSTIC_ONLY_NOT_SOURCE_APPROVAL")
            row = report["regions"][0]
            crop = root / "private" / row["file"]
            self.assertEqual(row["sha256"],
                             hashlib.sha256(crop.read_bytes()).hexdigest())
            self.assertNotIn("answer", json.dumps(row))


if __name__ == "__main__":
    unittest.main()
