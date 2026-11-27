"""Tests for upstream patch v1.3.1-fid-6-single-pass-source.

A screenshot-only page whose words come from a single OCR pass has no
second read to confirm them, so it is held with reason single_pass_source
unless the page also has a PDF text layer that agrees with every word the
single pass read. All fixtures here are synthetic; no real exam text is
used.

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
    return mod, up


_LOADED = _load_fidelity()
FID, UP = _LOADED if _LOADED else (None, None)


def _cfg():
    cfg = FID.load_fidelity_config(str(UP))
    cfg["require_certain_key"] = False
    return cfg


def _w(text, conf=96.0):
    return {"text": text, "conf": conf}


def _im(pass_texts, words=None):
    if words is None:
        words = [_w(t) for t in pass_texts[0].split()]
    passes = {"p%d" % n: {"text": t} for n, t in enumerate(pass_texts)}
    return {"file": "page.jpg", "words": words, "passes": passes}


def _ocr_item(pass_texts, words=None):
    return {"images": [_im(pass_texts, words)], "agree": True}


def _result():
    return {"type": "inline_dropdown", "matched_rules": [{"id": "inline_dropdown"}]}


def _question(stem_text):
    return {"type": "inline_dropdown",
            "learner": {"stem": [{"type": "paragraph", "content": [
                {"text": stem_text}]}]}}


@unittest.skipUnless(FID is not None, "needs a patched upstream checkout")
class SinglePassSourceTests(unittest.TestCase):
    def test_single_pass_source_holds_when_pdf_empty(self):
        # No PDF text, one OCR pass, question built from the OCR words:
        # coverage is 100 percent and the OCR gate passes, so the only
        # reason to hold is the single pass.
        item = {"question_key": "qtest", "source_text": ""}
        ocr = _ocr_item(["alpha beta"])
        out = FID.evaluate(item, _question("alpha beta"), _result(), ocr,
                           {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertFalse(out["ok"], out)
        self.assertIn("single_pass_source", out["reason"], out)

    def test_two_pass_source_exports_when_pdf_empty(self):
        # Same setup with two agreeing passes: no single-pass hold. The
        # item still holds on its missing key, which is unrelated.
        item = {"question_key": "qtest", "source_text": ""}
        ocr = _ocr_item(["alpha beta", "beta alpha"])
        out = FID.evaluate(item, _question("alpha beta"), _result(), ocr,
                           {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertNotIn("single_pass_source", out["reason"], out)
        self.assertEqual(out["reason"], "every cloze blank must have a key; no text key and no pixel marks", out)

    def test_single_pass_accepted_when_pdf_layer_agrees(self):
        # No question built, but the PDF text layer reads the same words
        # the single pass read: the pass is corroborated, so there is no
        # single-pass hold (the item still holds on missing words).
        item = {"question_key": "qtest", "source_text": "alpha beta"}
        ocr = _ocr_item(["alpha beta"])
        out = FID.evaluate(item, None, _result(), ocr,
                           {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertNotIn("single_pass_source", out["reason"], out)

    def test_single_pass_holds_when_pdf_layer_disagrees(self):
        # No question built and the single pass read a word the PDF layer
        # does not have: the pass is not corroborated, so it holds.
        item = {"question_key": "qtest", "source_text": "alpha beta"}
        ocr = _ocr_item(["alpha beta gamma"])
        out = FID.evaluate(item, None, _result(), ocr,
                           {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertIn("single_pass_source", out["reason"], out)

    def test_single_pass_in_coverage_images_holds(self):
        # The main image has two passes, but an earlier coverage read has
        # one: its words are still single-pass source, so it holds.
        item = {"question_key": "qtest", "source_text": ""}
        ocr = _ocr_item(["alpha beta", "beta alpha"])
        ocr["coverage_images"] = [_im(["alpha beta"])]
        out = FID.evaluate(item, _question("alpha beta"), _result(), ocr,
                           {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertFalse(out["ok"], out)
        self.assertIn("single_pass_source", out["reason"], out)


if __name__ == "__main__":
    unittest.main()
