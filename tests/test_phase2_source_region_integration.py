"""Phase 2 integrated source region OCR: fail-closed synthetic contract tests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from scripts.phase2_source_region_ocr import extract, text_row_subregions, deduplicate_source_regions, light_ui_rectangles, localized_text_region
from scripts.patch_phase2_upstream_extractor import (
    IMPORT_ANCHOR, SETUP_ANCHOR, QUESTION_ANCHOR, FINISH_ANCHOR,
    patch as patch_upstream,
)


class RegionSourceTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.file = Path(self.t.name) / "private-image.png"
        a = np.full((180, 650, 3), 255, dtype=np.uint8)
        self.assertTrue(cv2.imwrite(str(self.file), a))
        self.specs = [{"id": "psm3", "psm": 3}, {"id": "psm6", "psm": 6}]
        self.cfg = {"fidelity": {"min_word_confidence": 90,
                                 "min_overall_confidence": 95}}
        self.roi = [{"kind": "enclosed_text_control", "bbox": [40, 30, 350, 110]}]

    @patch("scripts.phase2_source_region_ocr.regions")
    def test_two_independent_strict_passes_create_candidate_not_release(self, r):
        r.return_value = self.roi
        def ocr(path, cfg, spec):
            self.assertTrue(Path(path).is_file())
            return {"id": spec["id"], "text": "Independent source words",
                    "words": [{"text": "Independent"}],
                    "min_confidence": 95.0, "mean_confidence": 97.0}
        results = extract(str(self.file), self.file.name, ocr, self.specs, self.cfg)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["usable_as_verified_source"])
        self.assertFalse(results[0]["auto_approved_for_release"])
        self.assertEqual([p["id"] for p in results[0]["passes"]], ["psm3", "psm6"])
        self.assertEqual(results[0]["bbox_pixels"], [40, 30, 350, 110])

    @patch("scripts.phase2_source_region_ocr.regions")
    def test_ocr_disagreement_does_not_certify(self, r):
        r.return_value = self.roi
        def ocr(path, cfg, spec):
            return {"id": spec["id"], "text": spec["id"], "words": [1],
                    "min_confidence": 99.0, "mean_confidence": 99.0}
        result = extract(str(self.file), self.file.name, ocr, self.specs, self.cfg)[0]
        self.assertFalse(result["two_pass_agreement"])
        self.assertFalse(result["usable_as_verified_source"])

    @patch("scripts.phase2_source_region_ocr.regions")
    def test_confidence_below_original_threshold_cannot_certify(self, r):
        r.return_value = self.roi
        def ocr(path, cfg, spec):
            return {"id": spec["id"], "text": "source words", "words": [1],
                    "min_confidence": 89.9, "mean_confidence": 98.0}
        result = extract(str(self.file), self.file.name, ocr, self.specs, self.cfg)[0]
        self.assertTrue(result["two_pass_agreement"])
        self.assertFalse(result["confidence_pass"])
        self.assertFalse(result["usable_as_verified_source"])

    @patch("scripts.phase2_source_region_ocr.regions")
    def test_empty_output_is_not_agreement(self, r):
        r.return_value = self.roi
        def ocr(path, cfg, spec):
            return {"id": spec["id"], "text": "", "words": [],
                    "min_confidence": None, "mean_confidence": None}
        result = extract(str(self.file), self.file.name, ocr, self.specs, self.cfg)[0]
        self.assertFalse(result["usable_as_verified_source"])

    @patch("scripts.phase2_source_region_ocr.regions")
    def test_invalid_coordinate_refused(self, r):
        r.return_value = [{"kind": "enclosed_text_control",
                           "bbox": [-1, 0, 300, 50]}]
        self.assertEqual(extract(str(self.file), self.file.name,
                                 lambda *_: None, self.specs, self.cfg), [])

    def test_multi_line_control_yields_source_text_bands(self):
        image = np.full((250, 520, 3), 255, np.uint8)
        for y, text in [(70, "Alpha statement"), (114, "Beta option"),
                        (158, "Gamma choice")]:
            cv2.putText(image, text, (28, y),
                        cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 0, 0), 2)
        bands = text_row_subregions(
            image, {"kind": "enclosed_text_control",
                    "bbox": [15, 35, 490, 200]})
        self.assertEqual(len(bands), 3)
        # Source text band must not crop off leading characters again.
        self.assertEqual(bands[0]["bbox"][0], 15)
        self.assertEqual(bands[0]["bbox"][2], 490)
        self.assertTrue(all(x["kind"]=="enclosed_text_control_text_band" for x in bands))
        self.assertTrue(all(0<=x["bbox"][1]<x["bbox"][3]<=250 for x in bands))

    def test_no_text_cannot_create_source_words_or_fake_answer(self):
        blank = np.full((200, 440, 3), 255, np.uint8)
        self.assertEqual(text_row_subregions(blank, {
            "kind": "matrix_statement_column", "bbox": [5, 5, 430, 185]
        }), [])

    @patch("scripts.phase2_source_region_ocr.regions")
    def test_unboxed_source_words_are_not_silently_lost(self, detected):
        detected.return_value = []
        picture = np.full((240, 600, 3), 255, np.uint8)
        for y, words in ((75, "First statement"), (120, "Second statement"),
                         (165, "Third statement")):
            cv2.putText(picture, words, (35, y),
                        cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 0, 0), 2)
        self.assertTrue(cv2.imwrite(str(self.file), picture))
        def ocr(path, cfg, spec):
            return {"id": spec["id"], "text": "source evidence only",
                    "words": [1], "min_confidence": 96,
                    "mean_confidence": 97}
        results = extract(str(self.file), self.file.name, ocr, self.specs, self.cfg)
        self.assertGreaterEqual(len(results), 2)
        self.assertTrue(all(x["kind"].startswith("unboxed_source_text_text_band")
                            for x in results))
        self.assertTrue(all(not x["auto_approved_for_release"] for x in results))

    def test_nested_source_panels_deduplicate_without_losing_distinct_boxes(self):
        boxes = [{"kind": "enclosed_text_control", "bbox": x} for x in [
            [66, 207, 320, 317], [66, 207, 320, 319],
            [70, 209, 316, 317], [334, 207, 488, 317],
            [334, 207, 488, 319], [338, 209, 484, 317],
        ]]
        dedup = deduplicate_source_regions(boxes)
        self.assertEqual(len(dedup), 2)
        self.assertTrue(all(x["bbox"][2]-x["bbox"][0] > 140 for x in dedup))

    @patch("scripts.phase2_source_region_ocr.regions")
    @patch("scripts.phase2_source_region_ocr.text_row_subregions")
    def test_busy_panel_budget_preserves_child_text_regions(self, bands, parents):
        parents.return_value = [
            {"kind": "enclosed_text_control", "bbox": [5, 5, 450, 100]},
            {"kind": "enclosed_text_control", "bbox": [5, 100, 450, 170]},
        ]
        bands.side_effect = lambda image, parent, **kw: [
            {"kind": "enclosed_text_control_text_band",
             "bbox": [20, parent["bbox"][1]+10+i*12,
                      430, parent["bbox"][1]+20+i*12]}
            for i in range(3)]
        def ocr(path, cfg, spec):
            return {"id": spec["id"], "text": "source words",
                    "words": [1], "min_confidence": 96,
                    "mean_confidence": 97}
        found = extract(str(self.file), self.file.name, ocr,
                        self.specs, self.cfg, max_regions=5)
        self.assertEqual(len(found), 5)
        self.assertEqual(sum(x["kind"].endswith("_text_band")
                             for x in found), 3)
        self.assertTrue(all(not x["auto_approved_for_release"] for x in found))

    def test_low_contrast_admin_rows_extracted_from_original_style_screenshot(self):
        image = np.full((360, 338, 3), 240, np.uint8)
        for y, label in [(80, "Agent insights"),
                         (140, "App insights"), (200, "Change history")]:
            cv2.rectangle(image, (36, y), (298, y+29), (145, 145, 145), 1)
            cv2.putText(image, label, (50, y+21),
                        cv2.FONT_HERSHEY_SIMPLEX, .48, (30, 30, 30), 1)
        found = light_ui_rectangles(image)
        self.assertGreaterEqual(len(found), 3)
        self.assertTrue(all(r["kind"] == "light_ui_text_control" for r in found))
        self.assertTrue(all(r["bbox"][0] >= 36 and
                            r["bbox"][2] <= 299 for r in found))

    def test_blank_ui_does_not_invent_controls(self):
        blank = np.full((360, 338, 3), 255, np.uint8)
        self.assertEqual(light_ui_rectangles(blank), [])

    def test_dropdown_text_localization_excludes_original_vertical_rules(self):
        image = np.full((140, 650, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (155, 20), (450, 120), (0, 0, 0), 2)
        cv2.putText(image, "Data Catalog", (170, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, .60, (0, 0, 0), 2)
        original = {"kind": "unboxed_source_text_text_band",
                    "bbox": [0, 50, 650, 83]}
        result = localized_text_region(image, original)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["bbox"][0], 164)
        self.assertLess(result["bbox"][2], 450)
        self.assertGreater(result["bbox"][2]-result["bbox"][0], 40)

    def test_blank_ink_band_is_not_source_text(self):
        image = np.full((140, 650, 3), 255, np.uint8)
        self.assertIsNone(localized_text_region(image, {
            "kind": "unboxed_source_text_text_band",
            "bbox": [0, 50, 650, 83]
        }))

    @patch("scripts.phase2_source_region_ocr.regions")
    @patch("scripts.phase2_source_region_ocr.light_ui_rectangles")
    @patch("scripts.phase2_source_region_ocr.text_row_subregions")
    def test_original_source_regions_cannot_be_evicted_by_new_ui_boxes(
            self, bands, light, original):
        original.return_value = [{"kind": "matrix_statement_column",
                                  "bbox": [0, 0, 400, 130]}]
        light.return_value = [
            {"kind": "light_ui_text_control",
             "bbox": [5+i*3, 5+i*3, 350, 65+i*3]}
            for i in range(18)]
        bands.return_value = []
        def ocr(path, cfg, spec):
            return {"id": spec["id"], "text": "retained source statement",
                    "words": [1], "min_confidence": 96,
                    "mean_confidence": 97}
        result = extract(str(self.file), self.file.name, ocr, self.specs,
                         self.cfg, max_regions=5)
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]["kind"], "matrix_statement_column")
        self.assertTrue(result[0]["usable_as_verified_source"])

    def test_canonical_patcher_idempotent_and_source_preserving(self):
        root = Path(self.t.name)
        (root / "pipeline/scripts").mkdir(parents=True)
        (root / "skill").mkdir()
        canonical = root / "pipeline/scripts/ocr_extract.py"
        canonical.write_text("\n".join([
            IMPORT_ANCHOR, "def process_item():", SETUP_ANCHOR,
            "    for fn in qimg:", QUESTION_ANCHOR,
            "def finish():", FINISH_ANCHOR,
        ]))
        for name in ("phase2_source_region_ocr.py", "segment_ui_ocr_regions.py"):
            (root / "skill" / name).write_text("# synthetic helper\n")
        patch_upstream(root / "pipeline", root / "skill")
        before = canonical.read_text()
        self.assertIn("rec['source_region_candidates'] = region_candidates", before)
        patch_upstream(root / "pipeline", root / "skill")
        self.assertEqual(before, canonical.read_text())

    def test_canonical_patch_fails_on_mismatched_upstream(self):
        root = Path(self.t.name)
        (root / "pipeline/scripts").mkdir(parents=True)
        (root / "skill").mkdir()
        (root / "pipeline/scripts/ocr_extract.py").write_text("new, unrelated converter")
        for name in ("phase2_source_region_ocr.py", "segment_ui_ocr_regions.py"):
            (root / "skill" / name).write_text("# test\n")
        with self.assertRaisesRegex(ValueError, "Pinned canonical upstream mismatch"):
            patch_upstream(root / "pipeline", root / "skill")


if __name__ == "__main__":
    unittest.main()
