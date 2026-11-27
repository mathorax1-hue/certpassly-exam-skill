"""Tests for upstream patch v1.3.1-fid-4-coverage-words (all OCR words count).

The coverage source counts every OCR word, whatever its confidence, so a
real word the OCR read at low confidence no longer makes the export look
as if it added a word. The confidence gate stays exactly as strict: a
question still fails if any word is below 90. All fixtures here are
synthetic; no real exam text is used.

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


def _im(words):
    text = " ".join(w["text"] for w in words)
    return {"file": "page.jpg", "words": words,
            "passes": {"p0": {"text": text}, "p1": {"text": text}}}


def _ocr_item(words):
    return {"images": [_im(words)], "agree": True}


def _result():
    return {"type": "inline_dropdown", "matched_rules": [{"id": "inline_dropdown"}]}


def _question(stem_text):
    return {"type": "inline_dropdown",
            "learner": {"stem": [{"type": "paragraph", "content": [
                {"text": stem_text}]}]}}


@unittest.skipUnless(FID is not None, "needs a patched upstream checkout")
class CoverageWordsTests(unittest.TestCase):
    def test_low_confidence_word_in_export_is_not_extra(self):
        # "extra" was read at 45, so the old min-word filter kept it out of
        # the source and the export looked as if it had added the word.
        item = {"question_key": "qtest", "source_text": "select the answer"}
        ocr = _ocr_item([_w("select"), _w("extra", 45.0)])
        out = FID.evaluate(item, _question("select the answer extra"),
                           _result(), ocr, {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertNotIn("extra", out["extra_words"], out)
        # The confidence gate is unchanged: the item still fails on the word.
        self.assertFalse(out["ok"], out)
        self.assertIn("extra (45.0)", out["reason"], out)

    def test_low_confidence_word_not_in_export_is_missing(self):
        # A low-confidence word the export does not contain is a missing
        # word. The item is held on the confidence gate for the same word,
        # so this adds a reason but never changes an export outcome.
        item = {"question_key": "qtest", "source_text": "pick the word"}
        ocr = _ocr_item([_w("pick"), _w("ghost", 30.0)])
        out = FID.evaluate(item, None, _result(), ocr,
                           {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertIn("ghost", out["missing_words"], out)
        self.assertIn("ghost (30.0)", out["reason"], out)

    def test_low_confidence_word_in_coverage_images_is_not_extra(self):
        # The earlier read kept as coverage_images counts the same way.
        item = {"question_key": "qtest", "source_text": "select the answer"}
        ocr = {"images": [_im([_w("select")])], "agree": True,
               "coverage_images": [_im([_w("extra", 45.0)])]}
        out = FID.evaluate(item, _question("select the answer extra"),
                           _result(), ocr, {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertNotIn("extra", out["extra_words"], out)


if __name__ == "__main__":
    unittest.main()
