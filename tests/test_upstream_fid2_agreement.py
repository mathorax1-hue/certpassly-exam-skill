"""Tests for upstream patch v1.3.1-fid-2-agreement (sorted-token agreement).

Two OCR passes agree when they read the same multiset of words. Reading
order is never compared, because different page modes read columns in a
different order, but a repeated word in one pass and not the other is still
a disagreement. The 90 word and 95 overall thresholds are unchanged, and a
stored agree flag still applies when an image has fewer than two passes to
recompute from. All fixtures here are synthetic; no real exam text is used.

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


def _load(name, filename):
    up = _upstream_dir()
    if up is None:
        return None
    os.environ["CERTPASSLY_SKILL_ROOT"] = str(up)
    sys.path.insert(0, str(up / "scripts"))
    spec = importlib.util.spec_from_file_location(name, up / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


FID = _load("fidelity", "fidelity.py")
OCR = _load("ocr_extract", "ocr_extract.py")
CFG = {"ocr": {"min_word_confidence": 90, "min_overall_confidence": 95,
               "require_pass_agreement": True}}


def _w(text, conf=96.0):
    return {"text": text, "conf": conf}


def _im(pass_texts, stored_agree=None):
    words = [_w(t) for t in pass_texts[0].split()]
    passes = {"p%d" % n: {"text": t} for n, t in enumerate(pass_texts)}
    im = {"file": "page.jpg", "words": words, "passes": passes}
    if stored_agree is not None:
        im["agree"] = stored_agree
    return im


@unittest.skipUnless(FID is not None, "needs a patched upstream checkout")
class SortedAgreementTests(unittest.TestCase):
    def test_same_words_different_order_agrees(self):
        # The stored flags say disagree (order-sensitive old data), but the
        # passes read the same words, so the gate must pass.
        item = {"images": [_im(["alpha beta gamma delta",
                                 "delta gamma beta alpha"], stored_agree=False)],
                "agree": False}
        out = FID.check_image_ocr(item, CFG)
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["agree"], out)

    def test_repeated_word_still_disagrees(self):
        # Same words except one pass reads "beta" twice: multiset differs.
        item = {"images": [_im(["alpha beta gamma delta",
                                 "delta gamma beta beta alpha"], stored_agree=False)],
                "agree": False}
        out = FID.check_image_ocr(item, CFG)
        self.assertFalse(out["ok"], out)
        self.assertIn("page.jpg", out["reason"], out)

    def test_different_words_still_disagree(self):
        item = {"images": [_im(["alpha beta gamma delta",
                                 "alpha beta gamma epsilon"], stored_agree=False)],
                "agree": False}
        out = FID.check_image_ocr(item, CFG)
        self.assertFalse(out["ok"], out)
        self.assertIn("page.jpg", out["reason"], out)

    def test_low_word_still_holds_when_order_agrees(self):
        # Order agrees, but a real word is below 90: thresholds unchanged.
        words = [_w("alpha"), _w("beta"), _w("gamma", 88.0), _w("delta")]
        im = {"file": "page.jpg", "words": words,
              "passes": {"p0": {"text": "alpha beta gamma delta"},
                         "p1": {"text": "delta gamma beta alpha"}}}
        out = FID.check_image_ocr({"images": [im], "agree": True}, CFG)
        self.assertFalse(out["ok"], out)
        self.assertIn("gamma", out["reason"], out)

    def test_single_pass_stored_flag_still_applies(self):
        # One pass only, nothing to recompute from: the stored flag holds.
        im = {"file": "page.jpg", "words": [_w("alpha"), _w("beta")],
              "passes": {"p0": {"text": "alpha beta"}}, "agree": False}
        out = FID.check_image_ocr({"images": [im], "agree": False}, CFG)
        self.assertFalse(out["ok"], out)
        self.assertIn("page.jpg", out["reason"], out)

    def test_item_flag_ignored_when_every_image_recomputes(self):
        # Both images recompute to agree; the stale stored item flag must
        # not add an "item" disagreement.
        item = {"images": [_im(["alpha beta", "beta alpha"], stored_agree=False),
                           _im(["one two three", "three two one"], stored_agree=False)],
                "agree": False}
        out = FID.check_image_ocr(item, CFG)
        self.assertTrue(out["ok"], out)
        self.assertNotIn("item", out["reason"] or "", out)


@unittest.skipUnless(OCR is not None, "needs a patched upstream checkout")
class NormTextTests(unittest.TestCase):
    def test_norm_is_order_free_multiset(self):
        self.assertEqual(OCR._norm_ocr_text("Alpha beta gamma"),
                         OCR._norm_ocr_text("gamma Alpha beta"))
        self.assertNotEqual(OCR._norm_ocr_text("alpha beta gamma"),
                            OCR._norm_ocr_text("alpha beta beta gamma"))


if __name__ == "__main__":
    unittest.main()
