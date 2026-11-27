"""Tests for upstream patch v1.3.1-fid-1-fragments (fidelity fragment filter).

The patch drops OCR tokens that are not real words from the confidence gate:
pure punctuation or glyphs, or a strict substring of an adjacent word that
passed. A real one or two letter word that appears in the PDF text is never
dropped. The 90 word and 95 overall thresholds are unchanged for every word
that is kept. All fixtures here are synthetic; no real exam text is used.

Skipped unless a patched upstream checkout is available (CERTPASSLY_UPSTREAM
or skill/vendor/certpassly-exam-pipeline).
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _upstream_dir():
    env = os.environ.get("CERTPASSLY_UPSTREAM")
    if env and Path(env, "scripts", "fidelity.py").is_file():
        return Path(env)
    vend = ROOT / "vendor" / "certpassly-exam-pipeline"
    if (vend / "scripts" / "fidelity.py").is_file():
        return vend
    return None


def _load_fidelity():
    up = _upstream_dir()
    if up is None:
        return None
    os.environ["CERTPASSLY_SKILL_ROOT"] = str(up)
    sys.path.insert(0, str(up / "scripts"))
    spec = importlib.util.spec_from_file_location("fidelity", up / "scripts" / "fidelity.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fidelity"] = mod
    spec.loader.exec_module(mod)
    return mod


FID = _load_fidelity()
CFG = {"ocr": {"min_word_confidence": 90, "min_overall_confidence": 95,
               "require_pass_agreement": True}}


def _w(text, conf):
    return {"text": text, "conf": conf}


def _item(words, stored_min=None, stored_mean=None):
    im = {"file": "page.jpg", "words": words,
          "passes": {"psm3": {"text": " ".join(w["text"] for w in words)},
                     "psm6": {"text": " ".join(w["text"] for w in words)}}}
    if stored_min is not None:
        im["min_confidence"] = stored_min
    if stored_mean is not None:
        im["mean_confidence"] = stored_mean
    return {"images": [im], "agree": True}


@unittest.skipUnless(FID is not None, "needs a patched upstream checkout")
class FragmentFilterTests(unittest.TestCase):
    def test_pure_punctuation_low_word_is_dropped(self):
        # Every real word passes; the only low token is an underscore glyph.
        item = _item([_w("portal", 96.0), _w("_", 64.2), _w("settings", 95.0)])
        out = FID.check_image_ocr(item, CFG, source_tokens={"portal", "settings"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["low_words"], [])
        self.assertEqual(out["min_word_confidence"], 95.0)

    def test_glyph_tokens_are_dropped(self):
        item = _item([_w("portal", 96.0), _w("@", 84.7), _w("|", 67.7),
                      _w("settings", 95.0)])
        out = FID.check_image_ocr(item, CFG, source_tokens={"portal", "settings"})
        self.assertTrue(out["ok"], out)

    def test_fragment_of_adjacent_passed_word_is_dropped(self):
        # "confi" is a strict substring of the adjacent passed word "config".
        item = _item([_w("config", 96.0), _w("confi", 55.0), _w("settings", 95.0)])
        out = FID.check_image_ocr(item, CFG, source_tokens={"config", "settings"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["low_words"], [])

    def test_real_short_word_in_pdf_text_is_never_dropped(self):
        # "a" and "to" are real words in the PDF text, even at low confidence.
        item = _item([_w("go", 96.0), _w("a", 87.4), _w("portal", 95.0)])
        out = FID.check_image_ocr(item, CFG, source_tokens={"go", "a", "portal", "to"})
        self.assertFalse(out["ok"])
        self.assertEqual([w["text"] for w in out["low_words"]], ["a"])

    def test_real_word_below_threshold_still_holds(self):
        item = _item([_w("portal", 96.0), _w("Copilot", 88.0), _w("settings", 95.0)])
        out = FID.check_image_ocr(item, CFG, source_tokens={"portal", "copilot", "settings"})
        self.assertFalse(out["ok"])
        self.assertEqual([w["text"] for w in out["low_words"]], ["Copilot"])

    def test_fragment_of_word_not_in_pdf_text_is_kept_when_no_passed_neighbour(self):
        # "pa" is not a strict substring of either adjacent passed word.
        item = _item([_w("models", 95.7), _w("pa", 46.1), _w("common", 94.7)])
        out = FID.check_image_ocr(item, CFG, source_tokens={"models", "common"})
        self.assertFalse(out["ok"])
        self.assertEqual([w["text"] for w in out["low_words"]], ["pa"])

    def test_stored_min_from_dropped_fragment_does_not_reintroduce_failure(self):
        # The stored per-image minimum comes from the dropped glyph itself.
        item = _item([_w("portal", 96.0), _w("_", 64.2), _w("settings", 95.0)],
                     stored_min=64.2, stored_mean=95.6)
        out = FID.check_image_ocr(item, CFG, source_tokens={"portal", "settings"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["min_word_confidence"], 95.0)

    def test_dropped_fragment_does_not_drag_overall_below_threshold(self):
        # A glyph at 0.0 must not pull the overall mean below 95 when every
        # real word is at or above 95.
        item = _item([_w("portal", 96.0), _w("©", 0.0), _w("settings", 96.0)])
        out = FID.check_image_ocr(item, CFG, source_tokens={"portal", "settings"})
        self.assertTrue(out["ok"], out)
        self.assertGreaterEqual(out["overall_confidence"], 95)

    def test_without_pdf_tokens_short_token_is_not_substring_dropped(self):
        # No PDF token set: be conservative and keep a short token.
        item = _item([_w("config", 96.0), _w("co", 55.0), _w("settings", 95.0)])
        out = FID.check_image_ocr(item, CFG)
        self.assertFalse(out["ok"])
        self.assertEqual([w["text"] for w in out["low_words"]], ["co"])


if __name__ == "__main__":
    unittest.main()
