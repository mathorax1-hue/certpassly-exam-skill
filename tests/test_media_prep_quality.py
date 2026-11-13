"""Media-prep image-quality tests (matrix B; 10 scenarios, all synthetic).

Covers the operator order's quality matrix: native vs display geometry,
pixel-density goal at mobile/desktop widths, tiny images, blur, low contrast,
transparent PNG handling, histogram clipping advisory, extreme aspect ratio,
lossless/anti-alias output preservation, and Unicode filenames.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from media_prep_fixture import (HAS_IMAGE_DEPS, build_pdf,  # noqa: E402
                                build_full_workspace, clean_exhibit_png,
                                clipped_extremes_png, draw_exhibit,
                                extreme_aspect_png, low_contrast_exhibit_png,
                                png_bytes, transparent_exhibit_png,
                                blurry_exhibit_png, write_upstream_workspace)

if HAS_IMAGE_DEPS:
    from certpassly.media_prep import imageio, quality
    from certpassly.media_prep.config import load_config
    from certpassly.media_prep.source_inventory import build_inventory
    from certpassly.media_prep.selection import run_selection


def _assess(data, css_width=640, goal=2.0, profile_name="screenshot"):
    from certpassly.media_prep.config import DEFAULT_PROFILES
    img = imageio.SourceImage("t.png", data)
    return quality.assess(img, profile=dict(DEFAULT_PROFILES[profile_name]),
                          css_width=css_width, density_goal=goal)


@unittest.skipUnless(HAS_IMAGE_DEPS, "image extras not installed")
class QualityMatrixTests(unittest.TestCase):
    """10 distinct quality scenarios (hard gates + honest advisories)."""

    def test_b01_native_vs_display_geometry(self):
        """A 240px exhibit at a 640px CSS width fails the density floor."""
        small = png_bytes(240, 140, draw_exhibit)
        rep = _assess(small)
        self.assertFalse(rep["quality_ok"])
        self.assertTrue(any(i["reason"] == "SOURCE_IMAGE_LOW_RESOLUTION"
                            for i in rep["issues"]))

    def test_b02_pixel_density_goal_mobile_desktop(self):
        """900px at 640 CSS px = 1.4x: eligible floor met, below the 2x goal
        (advisory recorded); at 450 CSS px (mobile) the 2x goal is met."""
        data = clean_exhibit_png()
        wide = _assess(data, css_width=640, goal=2.0)
        self.assertTrue(wide["quality_ok"])
        self.assertFalse(wide["pixel_density"]["meets_goal"])
        self.assertTrue(any(a["reason"] == "BELOW_PIXEL_DENSITY_GOAL"
                            for a in wide["advisory"]))
        mobile = _assess(data, css_width=450, goal=2.0)
        self.assertTrue(mobile["quality_ok"])
        self.assertTrue(mobile["pixel_density"]["meets_goal"])
        self.assertFalse(any(a["reason"] == "BELOW_PIXEL_DENSITY_GOAL"
                             for a in mobile["advisory"]))

    def test_b03_tiny_image_fails(self):
        """A 20x20 image is degenerate and hard-fails."""
        tiny = png_bytes(20, 20, lambda d, w, h: d.rectangle([2, 2, 16, 16], fill=(0, 0, 0)))
        rep = _assess(tiny)
        self.assertFalse(rep["quality_ok"])
        self.assertTrue(any(i["reason"] == "SOURCE_IMAGE_TINY" for i in rep["issues"]))

    def test_b04_blur_fails_or_flags(self):
        rep = _assess(blurry_exhibit_png())
        self.assertFalse(rep["quality_ok"])
        self.assertTrue(any(i["reason"] == "SOURCE_IMAGE_BLURRY" for i in rep["issues"]))

    def test_b05_low_contrast_fails(self):
        rep = _assess(low_contrast_exhibit_png())
        self.assertFalse(rep["quality_ok"])
        self.assertTrue(any(i["reason"] == "SOURCE_IMAGE_LOW_CONTRAST"
                            for i in rep["issues"]))

    def test_b06_transparent_png_handled(self):
        """An RGBA exhibit with transparent background is flattened onto white
        before measurement (not silently near-white)."""
        img = imageio.SourceImage("t.png", transparent_exhibit_png())
        self.assertTrue(img.has_alpha)
        rep = quality.assess(img, profile=_screenshot_profile(), css_width=640, density_goal=2.0)
        self.assertTrue(rep["alpha_flattened_for_check"])
        self.assertTrue(rep["quality_ok"], rep["issues"])

    def test_b07_clipping_recorded_as_advisory(self):
        """A pure black/white image has essentially no midtones: recorded as a
        CLIPPED advisory (legitimate dark-text-on-white exhibits are NOT
        hard-failed for saturation)."""
        rep = _assess(clipped_extremes_png())
        clipped = [a for a in rep["advisory"] if a["reason"] == "SOURCE_IMAGE_CLIPPED"]
        self.assertTrue(clipped, rep["advisory"])

    def test_b08_extreme_aspect_fails(self):
        rep = _assess(extreme_aspect_png())
        self.assertFalse(rep["quality_ok"])
        self.assertTrue(any(i["reason"] == "SOURCE_IMAGE_ASPECT_EXTREME"
                            for i in rep["issues"]))

    def test_b09_lossless_output_preserved(self):
        """The written candidate keeps lossless pixels: PNG sources are copied
        byte-identically; JPEG sources are re-encoded ONCE to PNG (no repeated
        lossy generations)."""
        root = tempfile.mkdtemp(prefix="mp-lossless-")
        try:
            facts = build_full_workspace(os.path.join(root, "ws"))
            cfg = load_config(facts["config"])
            inv = build_inventory(cfg)
            ready = run_selection(cfg, inv)
            from certpassly.media_prep import manifest as mm
            from certpassly.media_prep.imageio import load_image
            media_src = os.path.join(cfg["upstream"]["out_dir"], "media", "src")
            # q002: lossless PNG -> byte-identical copy
            cand = ready["q002"]["clean_candidate"]
            src = load_image(os.path.join(media_src, cand["source_file"]))
            written = mm.write_clean_candidate(os.path.join(root, "clean"), "q002", src, cand)
            self.assertEqual(written["sha256"], src.sha256)
            # q007: JPEG source -> PNG (lossless container), same pixel size
            cand7 = ready["q007"]["clean_candidate"]
            src7 = load_image(os.path.join(media_src, cand7["source_file"]))
            self.assertFalse(cand7["lossless_source"])
            written7 = mm.write_clean_candidate(os.path.join(root, "clean"), "q007", src7, cand7)
            out7 = imageio.load_image(os.path.join(root, "clean", "q007.png"))
            self.assertEqual(out7.format, "png")
            self.assertEqual((out7.width, out7.height), (src7.width, src7.height))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_b10_unicode_filenames(self):
        """Media files with non-ASCII names are handled; the inventory records
        name_safe=false for them (they are re-named to qNNN.png on output)."""
        root = tempfile.mkdtemp(prefix="mp-uni-")
        try:
            media = {"p-401_\u00e9\u00e8\u4e2d\u6587.png": clean_exhibit_png()}
            split = {"q401": {"question_key": "q401", "source_number": 401,
                              "marker": "QUESTION n 401", "pages": [1],
                              "stem": "Synthetic unicode-name stem",
                              "options": {"a": "one"}, "answer_raw": "A",
                              "question_images": ["p-401_\u00e9\u00e8\u4e2d\u6587.png"],
                              "answer_images": [],
                              "layout_profile": "question_n_correct_answer"}}
            pdf = os.path.join(root, "uni.pdf")
            build_pdf(pdf, pages_spec=[{
                "text": [(60, 100, ["QUESTION 401", "Synthetic unicode-name stem",
                                    "Correct Answer: A"])],
                "images": [((60, 240, 552, 440), list(media.values())[0])]}])
            out = write_upstream_workspace(os.path.join(root, "out"), split, media)
            cfg = _cfg_for(root, pdf, out)
            cfg = load_config(cfg)
            inv = build_inventory(cfg)
            rec = inv["files"]["p-401_\u00e9\u00e8\u4e2d\u6587.png"]
            self.assertFalse(rec["name_safe"])
            ready = run_selection(cfg, inv)
            self.assertTrue(ready["q401"]["is_learner_eligible"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


def _screenshot_profile():
    from certpassly.media_prep.config import DEFAULT_PROFILES
    return dict(DEFAULT_PROFILES["screenshot"])


def _cfg_for(root, pdf, out_dir):
    import hashlib
    with open(pdf, "rb") as f:
        data = f.read()
    cfg = {
        "schema_version": "media-prep-v1", "exam_code": "SYN-QUAL",
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


if __name__ == "__main__":
    unittest.main()
