"""Media-prep source/processing tests (matrix A; 14 scenarios, all synthetic).

Covers the operator order's processing matrix: clean+marked pair selection,
marked-only blocking, byte-identical preservation, vector high-DPI render,
annotation omission, flattened-annotation honesty, rotated pages, multipage
items, multiple images, corrupt media, ambiguous roles, xref SHA mismatch,
typed-answer+marked-image reviewer isolation, and no-fake-superresolution.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from media_prep_fixture import (HAS_IMAGE_DEPS, build_full_workspace,  # noqa: E402
                                clean_exhibit_png, different_exhibit_png,
                                jpeg_bytes, draw_exhibit, draw_marked_exhibit,
                                png_bytes, build_pdf, write_upstream_workspace,
                                marked_exhibit_png, x_marked_exhibit_png,
                                underlined_exhibit_png, highlight_box_exhibit_png)

if HAS_IMAGE_DEPS:
    from certpassly.media_prep import imageio, marking
    from certpassly.media_prep.config import load_config
    from certpassly.media_prep.source_inventory import build_inventory
    from certpassly.media_prep.selection import run_selection


def _load(facts):
    cfg = load_config(facts["config"])
    inv = build_inventory(cfg)
    ready = run_selection(cfg, inv)
    return cfg, inv, ready


@unittest.skipUnless(HAS_IMAGE_DEPS, "image extras (PyMuPDF/Pillow/numpy/cv2) not installed")
class ProcessingMatrixTests(unittest.TestCase):
    """14 distinct source/processing scenarios on synthetic fixtures."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="mp-proc-")
        cls.facts = build_full_workspace(os.path.join(cls.root, "ws"))
        cls.cfg, cls.inv, cls.ready = _load(cls.facts)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def _q(self, qid):
        return self.ready[qid]

    def test_a01_clean_plus_marked_pair_chooses_clean(self):
        """q005: marked q image + clean registered answer copy -> Priority C clean member."""
        r = self._q("q005")
        self.assertTrue(r["is_learner_eligible"])
        self.assertEqual(r["clean_candidate"]["method"], "priority_c_paired_clean_member")
        self.assertEqual(r["clean_candidate"]["source_file"], "p-005_2.png")
        issues = json.dumps(r["issues"])
        self.assertIn("PAIR_ROLE_CORRECTION", issues)

    def test_a02_marked_only_blocks(self):
        """q003: only marked question images, no verifiable pair -> BLOCKED."""
        r = self._q("q003")
        self.assertFalse(r["is_learner_eligible"])
        self.assertTrue(any(b["reason"] == "MARKED_ONLY_REVIEW_REQUIRED"
                            for b in r["blocked_reasons"]))

    def test_a03_clean_embedded_raster_preserved_byte_identically(self):
        """q002: lossless PNG source is preserved byte-identically as the candidate."""
        r = self._q("q002")
        self.assertEqual(r["clean_candidate"]["method"], "priority_a_direct_clean_source")
        self.assertTrue(r["clean_candidate"]["lossless_source"])
        src_sha = r["clean_candidate"]["source_sha256"]
        # the candidate IS the source bytes for lossless inputs (no re-encode)
        self.assertEqual(self.inv["files"]["p-002_1.png"]["sha256"], src_sha)

    def test_a04_vector_rendered_true_high_resolution(self):
        """q008: vector exhibit rendered at 300 DPI with real added pixels."""
        r = self._q("q008")
        self.assertTrue(r["is_learner_eligible"])
        cand = r["clean_candidate"]
        self.assertEqual(cand["method"], "priority_b_annotation_free_render")
        self.assertEqual(cand["pixel_source"], "pdf_region_render")
        # 612x792pt page at 300dpi, /Rotate 90 -> landscape ~3300x2550 device
        # pixels (>> the 612x792 of a 72dpi render): real added pixels
        self.assertGreaterEqual(cand["width"], 3100)
        self.assertGreaterEqual(cand["height"], 2400)

    def test_a05_annotation_omitted_without_dropping_content(self):
        """q008: the square annotation (the 'key') is excluded, vector table text stays."""
        cand = self._q("q008")["clean_candidate"]
        self.assertTrue(cand["render"]["annotations_present"])
        self.assertGreaterEqual(len(cand["render"]["annotations_in_clip"]), 1)
        self.assertTrue(cand["render"]["removal_changed_visible_content"])

    def test_a06_flattened_annotation_stays_flagged(self):
        """A raster with FLATTENED marks on a page that also has annotations:
        rendering cannot clean it; the question must stay BLOCKED."""
        root = tempfile.mkdtemp(prefix="mp-flat-")
        try:
            media = {"p-101_1.png": marked_exhibit_png()}
            split = {"q101": {"question_key": "q101", "source_number": 101,
                              "marker": "QUESTION n 101", "pages": [1],
                              "stem": "Synthetic flattened-mark stem",
                              "options": {"a": "one", "b": "two"}, "answer_raw": "A",
                              "question_images": ["p-101_1.png"], "answer_images": [],
                              "layout_profile": "question_n_correct_answer"}}
            pdf = os.path.join(root, "flat.pdf")
            # page: marked raster embedded + a real highlight annotation over it
            build_pdf(pdf, pages_spec=[{
                "text": [(60, 100, ["QUESTION 101", "Synthetic flattened-mark stem",
                                    "Correct Answer: A"])],
                "images": [((60, 240, 552, 440), media["p-101_1.png"])],
                "annot": {"rect": [70, 250, 300, 290], "type": "highlight"}}])
            out = write_upstream_workspace(os.path.join(root, "out"), split, media)
            cfg = load_config(self._config_for(root, pdf, out))
            inv = build_inventory(cfg)
            ready = run_selection(cfg, inv)
            r = ready["q101"]
            self.assertFalse(r["is_learner_eligible"])
            self.assertTrue(any("PRIORITY_B_NOT_APPLICABLE" in json.dumps(i) for i in r["issues"]))
            self.assertTrue(any(b["reason"] in ("MARKED_ONLY_REVIEW_REQUIRED",
                                                "SOURCE_IMAGE_AMBIGUOUS")
                                for b in r["blocked_reasons"]))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_a07_rotated_page_crop_orientation(self):
        """All fixture pages are /Rotate 90 (portrait media box shown landscape);
        the render must match the DISPLAYED orientation (width/height ~ 792/612)."""
        cand = self._q("q008")["clean_candidate"]
        self.assertEqual(cand["render"]["page_rotation_deg"], 90)
        ratio = cand["width"] / cand["height"]
        self.assertAlmostEqual(ratio, 792 / 612, delta=0.05,
                               msg="render must be the displayed landscape orientation")

    def test_a08_multipage_item(self):
        """An item spanning two pages with its exhibit on the second still resolves."""
        root = tempfile.mkdtemp(prefix="mp-multi-")
        try:
            media = {"p-201_1.png": clean_exhibit_png()}
            split = {"q201": {"question_key": "q201", "source_number": 201,
                              "marker": "QUESTION n 201", "pages": [1, 2],
                              "stem": "Synthetic multipage stem",
                              "options": {}, "answer_raw": "",
                              "question_images": ["p-201_1.png"], "answer_images": [],
                              "layout_profile": "question_n_correct_answer"}}
            pdf = os.path.join(root, "multi.pdf")
            build_pdf(pdf, pages_spec=[
                {"text": [(60, 100, ["QUESTION 201", "Synthetic multipage stem"])]},
                {"images": [((60, 100, 552, 300), media["p-201_1.png"])],
                 "text": [(60, 400, ["Correct Answer: A"])]}])
            out = write_upstream_workspace(os.path.join(root, "out"), split, media)
            cfg = load_config(self._config_for(root, pdf, out))
            inv = build_inventory(cfg)
            ready = run_selection(cfg, inv)
            self.assertTrue(ready["q201"]["is_learner_eligible"])
            self.assertEqual(ready["q201"]["clean_candidate"]["method"],
                             "priority_a_direct_clean_source")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_a09_multiple_question_and_answer_images(self):
        """q012: two question images (clean + marked) -> the clean member is chosen."""
        r = self._q("q012")
        self.assertTrue(r["is_learner_eligible"])
        self.assertEqual(r["clean_candidate"]["source_file"], "p-012_1.png")
        roles = {d["source_file"]: d["verified_role"] for d in r["role_decisions"]}
        self.assertEqual(roles["p-012_1.png"], "question_clean_candidate")
        self.assertEqual(roles["p-012_2.png"], "answer_marked_reviewer_only")

    def test_a10_missing_or_corrupt_image(self):
        """q010: corrupt image bytes -> SOURCE_IMAGE_CORRUPT, never a crash."""
        r = self._q("q010")
        self.assertFalse(r["is_learner_eligible"])
        self.assertTrue(any(b["reason"] == "SOURCE_IMAGE_CORRUPT" for b in r["blocked_reasons"]))

    def test_a11_ambiguous_roles_block(self):
        """q006: upstream heuristic swap + no pair proof -> SOURCE_IMAGE_AMBIGUOUS."""
        r = self._q("q006")
        self.assertFalse(r["is_learner_eligible"])
        self.assertTrue(any(b["reason"] == "SOURCE_IMAGE_AMBIGUOUS" for b in r["blocked_reasons"]))

    def test_a12_source_asset_sha_mismatch(self):
        """A media file re-encoded so bytes/pixels no longer match any PDF xref
        loses provenance and cannot become a learner candidate."""
        root = tempfile.mkdtemp(prefix="mp-sha-")
        try:
            clean = clean_exhibit_png()
            media = {"p-301_1.png": clean}
            split = {"q301": {"question_key": "q301", "source_number": 301,
                              "marker": "QUESTION n 301", "pages": [1],
                              "stem": "Synthetic re-encoded stem",
                              "options": {"a": "one"}, "answer_raw": "A",
                              "question_images": ["p-301_1.png"], "answer_images": [],
                              "layout_profile": "question_n_correct_answer"}}
            pdf = os.path.join(root, "src.pdf")
            build_pdf(pdf, pages_spec=[{
                "text": [(60, 100, ["QUESTION 301", "Synthetic re-encoded stem",
                                    "Correct Answer: A"])],
                "images": [((60, 240, 552, 440), clean)]}])
            # swap the media file for a re-encoded copy (bytes differ from the xref)
            out = write_upstream_workspace(os.path.join(root, "out"), split, media)
            reencoded = jpeg_bytes(900, 420, draw_exhibit, quality=60)
            with open(os.path.join(out, "media", "src", "p-301_1.png"), "wb") as f:
                f.write(reencoded)
            cfg = load_config(self._config_for(root, pdf, out))
            inv = build_inventory(cfg)
            self.assertEqual(inv["files"]["p-301_1.png"]["xref_method"], "none")
            ready = run_selection(cfg, inv)
            r = ready["q301"]
            self.assertFalse(r["is_learner_eligible"])
            self.assertTrue(any(b["reason"] == "SOURCE_ASSET_SHA_MISMATCH"
                                for b in r["blocked_reasons"]))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_a13_typed_answer_with_marked_image_stays_reviewer_only(self):
        """q002: answer_raw is typed 'A' AND the answer image is marked; the image
        never becomes learner-eligible regardless of the typed key."""
        r = self._q("q002")
        roles = {d["source_file"]: d["verified_role"] for d in r["role_decisions"]}
        self.assertEqual(roles["p-002_2.png"], "answer_marked_reviewer_only")
        self.assertEqual(r["clean_candidate"]["source_file"], "p-002_1.png")
        self.assertNotEqual(r["clean_candidate"]["source_sha256"],
                            self.inv["files"]["p-002_2.png"]["sha256"])

    def test_a14_no_fake_superresolution(self):
        """Raster candidates keep native pixel dimensions; the embedded raster
        ceiling is recorded for renders; no candidate claims upscaled detail."""
        r2 = self._q("q002")
        self.assertEqual(r2["clean_candidate"]["width"], 900)
        self.assertEqual(r2["clean_candidate"]["height"], 420)
        r4 = self._q("q004")
        cand = r4["clean_candidate"]
        self.assertEqual(cand["width"], 240)  # tiny stays tiny - no upscale to pass
        # q007 (JPEG source): re-encoded to PNG at the SAME pixel size
        r7 = self._q("q007")
        self.assertEqual((r7["clean_candidate"]["width"], r7["clean_candidate"]["height"]),
                         (900, 420))

    def test_a15_vector_pen_mark_page_blocks(self):
        """A vector page that carries a DARK drawn ring (a vector pen mark)
        must NOT produce a learner image: the render shows pen-like shapes and
        vector-drawn marks cannot be proved absent (VECTOR_PEN_MARK_UNDETECTABLE
        handled conservatively)."""
        root = tempfile.mkdtemp(prefix="mp-vpen-")
        try:
            media = {}
            split = {"q501": {"question_key": "q501", "source_number": 501,
                              "marker": "QUESTION n 501", "pages": [1],
                              "stem": "Synthetic vector pen-mark stem with exhibit",
                              "options": {"a": "one"}, "answer_raw": "A",
                              "question_images": [], "answer_images": [],
                              "layout_profile": "question_n_correct_answer"}}
            pdf = os.path.join(root, "vpen.pdf")
            import fitz
            doc = fitz.open()
            page = doc.new_page(width=612, height=792)
            page.insert_text((60, 80), "QUESTION 501", fontsize=11, fontname="helv")
            page.insert_text((60, 96), "Synthetic vector pen-mark stem with exhibit",
                             fontsize=11, fontname="helv")
            # big light vector table (legitimate chrome)...
            y0 = 200
            for r in range(6):
                y = y0 + r * 40
                page.draw_line(fitz.Point(40, y), fitz.Point(570, y),
                               color=(0.55, 0.55, 0.62), width=1)
                page.insert_text((48, y + 16), f"Vector row {r + 1} statement",
                                 fontsize=10, fontname="helv")
            page.draw_rect(fitz.Rect(40, y0 - 20, 570, y0 + 240),
                           color=(0.55, 0.55, 0.62), width=1.2)
            # ...plus a DARK vector circle drawn around row 2 (the owner "key")
            page.draw_circle(fitz.Point(150, y0 + 60), 30, color=(0.05, 0.05, 0.05), width=3)
            doc.save(pdf, garbage=3, deflate=True)
            out = write_upstream_workspace(os.path.join(root, "out"), split, media)
            cfg = load_config(self._config_for(root, pdf, out))
            inv = build_inventory(cfg)
            ready = run_selection(cfg, inv)
            r = ready["q501"]
            self.assertFalse(r["is_learner_eligible"], 
                             "vector pen-mark page must block, not render")
            self.assertTrue(any("PRIORITY_B_NOT_APPLICABLE" in json.dumps(i)
                                for i in r["issues"]))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    # -- helpers -------------------------------------------------------------

    def _config_for(self, root, pdf, out_dir):
        import hashlib
        with open(pdf, "rb") as f:
            data = f.read()
        cfg = {
            "schema_version": "media-prep-v1", "exam_code": "SYN-PROC",
            "source": {"pdf": pdf, "expected_sha256": hashlib.sha256(data).hexdigest(),
                       "expected_bytes": len(data)},
            "upstream": {"repo": "msaqlainhaneef1/certpassly-exam-pipeline",
                         "commit": "13dea6bab662ab1c4bbf87017e912e519907c8bc",
                         "scripts_dir": None, "out_dir": out_dir, "run_extract": False},
            "output": {"clean_dir": os.path.join(root, "prepared", "clean"),
                       "private_dir": os.path.join(root, "prepared", "private"),
                       "manifest": os.path.join(root, "prepared", "image-manifest.json"),
                       "inventory": os.path.join(root, "prepared", "image-inventory.json")},
            "display": {"default_css_width": 640, "pixel_density_goal": 2.0},
            "quality_profiles": {}, "privacy": {"allow_external_urls": False,
                                                 "allowed_hosts": []}}
        path = os.path.join(root, "cfg.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return path


@unittest.skipUnless(HAS_IMAGE_DEPS, "image extras not installed")
class MarkDetectorUnitTests(unittest.TestCase):
    """Direct unit checks of the mark detector shape/color model."""

    def _detect(self, data):
        img = imageio.SourceImage("t.png", data)
        return marking.detect_marks(img.flattened_rgb())

    def test_ring_mark_detected(self):
        self.assertGreaterEqual(self._detect(marked_exhibit_png())["detected_mark_boxes"], 1)

    def test_x_mark_detected(self):
        self.assertGreaterEqual(self._detect(x_marked_exhibit_png())["detected_mark_boxes"], 1)

    def test_highlight_box_detected(self):
        self.assertGreaterEqual(self._detect(highlight_box_exhibit_png())["detected_mark_boxes"], 1)

    def test_underline_detected(self):
        self.assertGreaterEqual(self._detect(underlined_exhibit_png())["detected_mark_boxes"], 1)

    def test_clean_exhibit_not_marked(self):
        self.assertEqual(self._detect(clean_exhibit_png())["detected_mark_boxes"], 0)

    def test_clean_chart_with_gray_border_not_marked(self):
        """Mid-gray UI borders (header bands, chart frames) must not trip the detector."""
        self.assertEqual(self._detect(different_exhibit_png())["detected_mark_boxes"], 0)

    def test_colored_pen_box_detected(self):
        """A saturated-color pen box (red) is pen-like even though not dark."""
        def draw(d, w, h):
            from PIL import ImageDraw  # noqa: F401
            d.rectangle([40, 40, w - 40, h - 40], outline=(200, 20, 20), width=6)
        data = png_bytes(600, 300, draw)
        self.assertGreaterEqual(self._detect(data)["detected_mark_boxes"], 1)


if __name__ == "__main__":
    unittest.main()
