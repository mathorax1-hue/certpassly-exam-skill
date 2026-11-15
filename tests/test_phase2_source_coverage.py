"""Phase 2 source-coverage verifier: fail-closed synthetic contract tests.

The verifier must never count candidate-only OCR as coverage, never verify a
word whose reading failed the unchanged two-pass gates, and must record
specific evidence for every uncovered word.
"""
import re
import unittest

import cv2
import numpy as np

from scripts.verify_phase2_source_coverage import (
    assert_canonical_gates, verify_question)


class StubFidelity:
    """Canonical fidelity semantics without the private pipeline checkout."""

    @staticmethod
    def token_set(text, cfg=None):
        return set(re.findall(r"[a-z0-9]+", (text or "").lower()))

    @staticmethod
    def source_pdf_text(item, cfg, deny=None):
        return item.get("source_text") or ""

    @staticmethod
    def make_deny(cfg=None):
        return None


PASS_SPECS = [{"id": "psm3", "psm": 3, "scale": 2, "preprocess": "none"},
              {"id": "psm6", "psm": 6, "scale": 2, "preprocess": "threshold"}]
CFG = {"fidelity": {"min_word_confidence": 90,
                    "min_overall_confidence": 95,
                    "require_pass_agreement": True}}
TEMPLATE_REGEXES = [re.compile(r"^answer area$", re.I)]


def ocr_result(text, lo, mean):
    return {"id": "pass", "text": text,
            "words": [{"text": w} for w in text.split()],
            "min_confidence": lo, "mean_confidence": mean}


def region_candidate(kind="unboxed_source_text_text_band",
                     bbox=(10, 10, 150, 35), text="SharePoint",
                     strict=True, prescale=2, agree=True,
                     psm3=(96.0, 97.0), psm6=(95.0, 96.0)):
    return {
        "kind": kind, "bbox_pixels": list(bbox),
        "source_file": "p-1_1.png", "ocr_prescale": prescale,
        "ocr_text_candidate": text,
        "two_pass_agreement": agree,
        "confidence_pass": strict,
        "usable_as_verified_source": strict,
        "auto_approved_for_release": False,
        "passes": [
            {"id": "psm3", "min_confidence": psm3[0],
             "mean_confidence": psm3[1], "word_count": 1},
            {"id": "psm6", "min_confidence": psm6[0],
             "mean_confidence": psm6[1], "word_count": 1},
        ],
    }


def make_image(h=100, w=200):
    return np.full((h, w, 3), 255, np.uint8)


def question_item(text="SharePoint", conf=91.5, candidates=None,
                  x=0.05, y=0.1, x1=0.55, y1=0.35):
    """Held question with one question image whose OCR reads `text`."""
    item = {"question_images": ["p-1_1.png"], "source_text": ""}
    ocr_item = {"images": [{
        "file": "p-1_1.png", "role": "question",
        "words": [{"text": text, "conf": conf}],
        "lines": [{"t": text, "x": x, "y": y, "x1": x1, "y1": y1}],
        "passes": {"psm3": {"text": text}, "psm6": {"text": text}},
        "source_region_candidates": candidates or [],
    }]}
    return item, ocr_item


class SourceCoverageTests(unittest.TestCase):
    def verify(self, item, ocr_item, status="held", ocr_pass=None,
               image=None):
        baseline = {"upstream_status": status, "source_pages": [1, 2]}
        return verify_question(
            "q001", item, ocr_item, baseline, "unused-media", CFG,
            PASS_SPECS, StubFidelity, {}, None, TEMPLATE_REGEXES,
            ocr_pass or (lambda path, cfg, spec: ocr_result(
                "SharePoint", 96.0, 97.0)),
            image_loader=lambda fn: image if image is not None else make_image())

    def test_gate_assertions_fail_closed(self):
        with self.assertRaises(AssertionError):
            assert_canonical_gates(
                {"fidelity": {"min_word_confidence": 50,
                              "min_overall_confidence": 95,
                              "require_pass_agreement": True}}, PASS_SPECS)
        with self.assertRaises(AssertionError):
            assert_canonical_gates(
                {"fidelity": {"min_word_confidence": 90,
                              "min_overall_confidence": 90,
                              "require_pass_agreement": True}}, PASS_SPECS)
        with self.assertRaises(AssertionError):
            assert_canonical_gates(
                {"fidelity": {"min_word_confidence": 90,
                              "min_overall_confidence": 95,
                              "require_pass_agreement": False}}, PASS_SPECS)
        gate = assert_canonical_gates(CFG, PASS_SPECS)
        self.assertEqual(gate["min_word_confidence"], 90)

    def test_exported_text_only_question_is_complete(self):
        item = {"question_images": [], "source_text": "Which solution meets the goal"}
        ocr_item = {"images": []}
        rec = self.verify(item, ocr_item, status="exported")
        self.assertTrue(rec["source_record_complete"])
        self.assertEqual(rec["uncovered_token_count"], 0)
        self.assertIn("which", rec["verified_by_class"]["text_layer"])
        self.assertEqual(rec["region_attempt_count"], 0)

    def test_strict_region_record_verifies_word(self):
        item, ocr_item = question_item(
            candidates=[region_candidate(strict=True)])
        rec = self.verify(item, ocr_item, image=make_image())
        self.assertEqual(rec["uncovered_token_count"], 0)
        self.assertIn("sharepoint", rec["verified_by_class"]["strict_region"])
        self.assertEqual(rec["region_attempts"][0]["verdict"], "strict")
        self.assertEqual(rec["region_attempts"][0]["attempts"][0]["source"],
                         "canonical_converter_record")
        self.assertTrue(rec["source_record_complete"])

    def test_failed_region_and_line_battery_documents_deficiency(self):
        item, ocr_item = question_item(
            candidates=[region_candidate(strict=False, agree=True,
                                         psm3=(80.0, 85.0),
                                         psm6=(78.0, 83.0))])
        rec = self.verify(
            item, ocr_item,
            ocr_pass=lambda path, cfg, spec: ocr_result("SharePoint", 80.0, 85.0))
        # The word is NOT verified: candidate-only readings never cover.
        self.assertEqual(rec["verified_token_count"], 0)
        self.assertEqual(rec["uncovered_token_count"], 1)
        word = rec["uncovered_words"][0]
        self.assertEqual(word["token"], "sharepoint")
        self.assertEqual(word["evidence"],
                         "canonical_region_failed_and_line_battery_recorded")
        # The canonical region failure is preserved as evidence.
        self.assertEqual(word["containing_region_attempts"][0]
                         ["canonical_attempt"]["passes"]["psm3"]
                         ["mean_confidence"], 85.0)
        # The OCR line crop battery ran and is recorded.
        self.assertTrue(word["ocr_line_crop_attempts"])
        attempts = word["ocr_line_crop_attempts"][0]["attempts"]
        self.assertGreaterEqual(len(attempts), 1)
        self.assertTrue(all(not a.get("strict") for a in attempts))
        self.assertEqual(rec["ocr_line_batteries"][0]["verdict"],
                         "deficiency_documented")
        # Complete means every word verified or evidenced, not all verified.
        self.assertTrue(rec["source_record_complete"])
        self.assertFalse(rec["has_verified_evidence"])
        self.assertFalse(rec["source_fidelity_certified"])
        self.assertFalse(rec["release_approved"])

    def test_stronger_line_prescale_verifies_word(self):
        # Line bbox ~[6,6,114,39]: 33 px tall -> canonical prescale 2.
        item, ocr_item = question_item(
            x=0.05, y=0.1, x1=0.55, y1=0.35,
            candidates=[region_candidate(strict=False, bbox=(10, 10, 50, 35),
                                         psm3=(80.0, 85.0),
                                         psm6=(78.0, 83.0))])

        def ocr_pass(path, cfg, spec):
            h = cv2.imread(path).shape[0]
            if h >= 90:  # grown x3: passes both unchanged gates
                return ocr_result("SharePoint", 96.0, 97.0)
            return ocr_result("SharePoint", 80.0, 85.0)

        rec = self.verify(item, ocr_item, ocr_pass=ocr_pass, image=make_image())
        self.assertEqual(rec["uncovered_token_count"], 0)
        self.assertIn("sharepoint",
                      rec["verified_by_class"]["strict_ocr_line_crop"])
        self.assertEqual(rec["strict_verification_prescales"]["sharepoint"], 3)
        self.assertEqual(rec["ocr_line_batteries"][0]["verdict"], "strict")

    def test_border_trim_recovers_bordered_option_line(self):
        # A dark dropdown border sits directly at the OCR line box start,
        # exactly beside the option text (as Tesseract boxes it in the
        # original dropdown screenshots).
        image = np.full((60, 200, 3), 255, np.uint8)
        cv2.rectangle(image, (10, 5), (14, 45), (0, 0, 0), -1)
        cv2.putText(image, "Audit", (30, 35), cv2.FONT_HERSHEY_SIMPLEX,
                    .8, (0, 0, 0), 2)
        item, ocr_item = question_item(
            text="Audit", x=0.07, y=0.08, x1=0.55, y1=0.75,
            candidates=[region_candidate(strict=False, bbox=(10, 5, 76, 45),
                                         psm3=(80.0, 85.0),
                                         psm6=(78.0, 83.0))])

        def ocr_pass(path, cfg, spec):
            crop = cv2.imread(path)
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            # Strict only when no near-full-height dark column (the border
            # rule) remains inside the crop.
            column_dark = (gray < 60).mean(axis=0).max()
            if column_dark <= 0.8:
                return ocr_result("Audit", 96.0, 97.0)
            return ocr_result("| Audit", 65.0, 74.0)

        rec = self.verify(item, ocr_item, ocr_pass=ocr_pass, image=image)
        self.assertEqual(rec["uncovered_token_count"], 0)
        self.assertIn("audit", rec["verified_by_class"]["strict_ocr_line_crop"])
        strict_attempt = next(a for a in rec["ocr_line_batteries"][0]["attempts"]
                              if a.get("strict"))
        self.assertEqual(strict_attempt["variant"], "border_trim")

    def test_icon_skip_recovers_icon_prefixed_label(self):
        # A dense filled icon spanning the line height, with a clear gap,
        # precedes the label text (navigation-menu style).
        image = np.full((60, 200, 3), 255, np.uint8)
        cv2.rectangle(image, (20, 12), (38, 44), (0, 0, 0), -1)
        cv2.putText(image, "Reports", (60, 35), cv2.FONT_HERSHEY_SIMPLEX,
                    .8, (0, 0, 0), 2)
        item, ocr_item = question_item(
            text="Reports", x=0.1, y=0.22, x1=0.75, y1=0.7,
            candidates=[region_candidate(strict=False, bbox=(20, 15, 95, 42),
                                         psm3=(80.0, 85.0),
                                         psm6=(78.0, 83.0))])

        def ocr_pass(path, cfg, spec):
            crop = cv2.imread(path)
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            # Strict only when no near-full-height dark column (the solid
            # icon block) remains inside the crop; text strokes never reach
            # that column coverage.
            column_dark = (gray < 60).mean(axis=0).max()
            if column_dark <= 0.8:
                return ocr_result("Reports", 96.0, 97.0)
            return ocr_result("& Reports", 70.0, 78.0)

        rec = self.verify(item, ocr_item, ocr_pass=ocr_pass, image=image)
        self.assertEqual(rec["uncovered_token_count"], 0)
        strict_attempt = next(a for a in rec["ocr_line_batteries"][0]["attempts"]
                              if a.get("strict"))
        # The line box trimmed slightly first, then the icon was skipped.
        self.assertEqual(strict_attempt["variant"], "border_trim_icon_skip")
        self.assertIn("reports", rec["verified_by_class"]["strict_ocr_line_crop"])

    def test_sparse_glyph_skip_recovers_arrow_prefixed_stem(self):
        # A narrow sparse arrow glyph (dropdown arrow style) precedes the
        # text with a clear gap; the raw and trimmed boxes both fail.
        image = np.full((60, 200, 3), 255, np.uint8)
        cv2.putText(image, "v", (20, 32), cv2.FONT_HERSHEY_SIMPLEX,
                    .7, (0, 0, 0), 2)
        cv2.putText(image, "Settings", (44, 35), cv2.FONT_HERSHEY_SIMPLEX,
                    .8, (0, 0, 0), 2)
        item, ocr_item = question_item(
            text="Settings", x=0.09, y=0.22, x1=0.62, y1=0.7,
            candidates=[region_candidate(strict=False, bbox=(18, 15, 90, 42),
                                         psm3=(80.0, 85.0),
                                         psm6=(78.0, 83.0))])

        def ocr_pass(path, cfg, spec):
            crop = cv2.imread(path)
            # Strict only for the glyph-skipped crop: the raw and trimmed
            # line boxes keep the arrow and stay wider even after the
            # canonical 2x prescale of this 37 px tall line.
            if crop.shape[1] <= 170:
                return ocr_result("Settings", 96.0, 97.0)
            return ocr_result("v Settings", 62.0, 74.0)

        rec = self.verify(item, ocr_item, ocr_pass=ocr_pass, image=image)
        self.assertEqual(rec["uncovered_token_count"], 0)
        strict_attempt = next(a for a in rec["ocr_line_batteries"][0]["attempts"]
                              if a.get("strict"))
        self.assertIn(strict_attempt["variant"],
                      ("glyph_skip", "border_trim_glyph_skip"))
        self.assertIn("settings",
                      rec["verified_by_class"]["strict_ocr_line_crop"])

    def test_disagreeing_passes_never_verify(self):
        item, ocr_item = question_item(
            candidates=[region_candidate(strict=False, agree=False)])

        def ocr_pass(path, cfg, spec):
            text = "SharePoint" if spec["id"] == "psm3" else "SharePomt"
            return ocr_result(text, 96.0, 97.0)

        rec = self.verify(item, ocr_item, ocr_pass=ocr_pass)
        self.assertEqual(rec["verified_token_count"], 0)
        word = rec["uncovered_words"][0]
        self.assertEqual(word["token"], "sharepoint")

    def test_secondary_pass_only_token_is_evidenced(self):
        item, ocr_item = question_item(text="SharePoint")
        ocr_item["images"][0]["passes"]["psm6"] = {
            "text": "SharePoint SharePomt"}
        ocr_item["images"][0]["source_region_candidates"] = [
            region_candidate(strict=True)]
        rec = self.verify(item, ocr_item, image=make_image())
        # 'sharepomt' is a secondary-only best-effort token: uncovered but
        # evidenced (context recorded), so the record stays complete.
        self.assertIn("sharepomt",
                      [w["token"] for w in rec["uncovered_words"]])
        word = next(w for w in rec["uncovered_words"]
                    if w["token"] == "sharepomt")
        self.assertTrue(word["full_image_context"])
        self.assertTrue(word["full_image_context"][0]["secondary_pass_only"])
        self.assertTrue(rec["source_record_complete"])

    def test_template_labels_excluded_from_reference(self):
        item, ocr_item = question_item(text="Answer Area")
        item["question_images"] = []
        ocr_item["images"][0]["role"] = "answer"  # excluded: not learner source
        rec = self.verify(item, ocr_item)
        self.assertEqual(rec["reference_content_token_count"], 0)
        self.assertTrue(rec["source_record_complete"])

    def test_template_line_inside_question_image_excluded(self):
        item, ocr_item = question_item(text="Answer Area")
        ocr_item["images"][0]["lines"][0]["t"] = "Answer Area"
        ocr_item["images"][0]["words"] = [{"text": "Answer", "conf": 95},
                                          {"text": "Area", "conf": 95}]
        ocr_item["images"][0]["passes"] = {
            "psm3": {"text": "Answer Area"}, "psm6": {"text": "Answer Area"}}
        rec = self.verify(item, ocr_item)
        self.assertEqual(rec["reference_content_token_count"], 0)
        self.assertEqual(rec["template_label_tokens_excluded"],
                         ["answer", "area"])


if __name__ == "__main__":
    unittest.main()
