"""Synthetic negative and positive owner-marked dropdown evidence tests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from scripts.detect_owner_marked_dropdown import marked_rectangles, recover


class MarkedDropdownTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.question = self.root / "question.png"
        self.answer = self.root / "answer.png"
        q = np.full((145, 625, 3), 255, np.uint8)
        a = q.copy()
        cv2.rectangle(a, (30, 49), (165, 69), (0, 0, 0), 2)
        cv2.imwrite(str(self.question), q)
        cv2.imwrite(str(self.answer), a)

    def test_two_thresholds_detect_same_mark(self):
        image = cv2.imread(str(self.answer))
        a = marked_rectangles(image, 60)
        b = marked_rectangles(image, 130)
        self.assertEqual(len(a), 1)
        self.assertEqual(a, b)

    def test_unmarked_answer_must_hold(self):
        result = recover(self.question, self.question)
        self.assertEqual(result["status"], "HELD_UNCERTAIN_MARK")

    @patch("scripts.detect_owner_marked_dropdown.tesseract_text")
    def test_independently_confirmed_choice_is_a_candidate_not_release(self, ocr):
        ocr.side_effect = [
            "synthetic first option", "synthetic first option",
            "synthetic first option second option",
            "synthetic first option second option",
        ]
        result = recover(self.question, self.answer)
        self.assertEqual(result["status"], "OWNER_MARK_CANDIDATE_VERIFIED")
        self.assertFalse(result["release_approved"])
        self.assertEqual(result["selected_label"], "synthetic first option")

    @patch("scripts.detect_owner_marked_dropdown.tesseract_text")
    def test_disagreeing_answer_ocr_must_hold(self, ocr):
        ocr.side_effect = ["first", "second"]
        result = recover(self.question, self.answer)
        self.assertEqual(result["status"], "HELD_ANSWER_OCR_DISAGREEMENT")

    @patch("scripts.detect_owner_marked_dropdown.tesseract_text")
    def test_answer_not_found_in_question_source_must_hold(self, ocr):
        ocr.side_effect = ["chosen", "chosen", "different", "different"]
        result = recover(self.question, self.answer)
        self.assertEqual(result["status"], "HELD_SOURCE_OPTION_NOT_VERIFIED")


if __name__ == "__main__":
    unittest.main()
