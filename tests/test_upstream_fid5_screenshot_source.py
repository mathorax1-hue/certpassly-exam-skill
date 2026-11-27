"""Tests for upstream patch v1.3.1-fid-5-screenshot-source (agreed OCR source).

When the page is a screenshot, the page image OCR is the only source of
the question words, so it counts only where both OCR passes agree on it:
a word one pass read and the other did not must not be reported as
missing. That is the case when the PDF text block is empty, and when no
question could be built at all. Otherwise every OCR word counts. All
fixtures here are synthetic; no real exam text is used.

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
class ScreenshotSourceTests(unittest.TestCase):
    def test_agreed_words_count_when_pdf_empty(self):
        # No PDF text and no built question: the agreed OCR words are the
        # source, so they are reported missing when the export lacks them.
        item = {"question_key": "qtest", "source_text": ""}
        ocr = _ocr_item(["alpha beta", "beta alpha"])
        out = FID.evaluate(item, None, _result(), ocr,
                           {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertIn("alpha", out["missing_words"], out)
        self.assertIn("beta", out["missing_words"], out)

    def test_one_pass_word_not_counted_when_pdf_empty(self):
        # "gamma" was read by one pass only, so it is not established and
        # must not be reported as missing.
        item = {"question_key": "qtest", "source_text": ""}
        ocr = _ocr_item(["alpha beta gamma", "alpha beta"])
        out = FID.evaluate(item, None, _result(), ocr,
                           {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertNotIn("gamma", out["missing_words"], out)
        self.assertIn("alpha", out["missing_words"], out)

    def test_one_pass_word_not_counted_when_no_question_built(self):
        # PDF text exists but no question could be built: the OCR source is
        # still the agreed words only.
        item = {"question_key": "qtest", "source_text": "pick the word"}
        ocr = _ocr_item(["pick the word ghost", "pick the word"])
        out = FID.evaluate(item, None, _result(), ocr,
                           {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertNotIn("ghost", out["missing_words"], out)
        self.assertIn("pick", out["missing_words"], out)

    def test_all_ocr_words_count_when_question_built(self):
        # A built question and PDF text: every OCR word counts, so a word
        # one pass read still stops the export looking as if it added it.
        item = {"question_key": "qtest", "source_text": "select the answer"}
        ocr = _ocr_item(["select extra", "select"], words=[_w("select"), _w("extra")])
        out = FID.evaluate(item, _question("select the answer extra"),
                           _result(), ocr, {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertNotIn("extra", out["extra_words"], out)


if __name__ == "__main__":
    unittest.main()
