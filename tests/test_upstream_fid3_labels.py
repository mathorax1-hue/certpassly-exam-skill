"""Tests for upstream patch v1.3.1-fid-3-labels (UI label strip).

The coverage source drops the exact UI label words (Answer Area,
Statements) and, for a yes/no grid, the Yes and No column headers, but
only when the answer-area layout was read, and only for label words the
export does not contain, so a real question word that matches a label
word is never hidden and no extra word can appear. All fixtures here are
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


def _ocr_item(words):
    text = " ".join(w["text"] for w in words)
    im = {"file": "page.jpg", "words": words,
          "passes": {"p0": {"text": text}, "p1": {"text": text}}}
    return {"images": [im], "agree": True}


def _result():
    return {"type": "inline_dropdown", "matched_rules": [{"id": "inline_dropdown"}]}


@unittest.skipUnless(FID is not None, "needs a patched upstream checkout")
class LabelStripTests(unittest.TestCase):
    def test_answer_area_stripped_from_pdf_source_when_layout_read(self):
        item = {"question_key": "qtest",
                "source_text": "pick the right word Answer Area"}
        out = FID.evaluate(item, None, _result(), _ocr_item([_w("pick")]),
                           {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertNotIn("answer", out["missing_words"], out)
        self.assertNotIn("area", out["missing_words"], out)
        self.assertIn("pick", out["missing_words"], out)

    def test_answer_area_kept_when_no_layout(self):
        item = {"question_key": "qtest",
                "source_text": "pick the right word Answer Area"}
        out = FID.evaluate(item, None, _result(), _ocr_item([_w("pick")]),
                           {}, _cfg())
        self.assertIn("answer", out["missing_words"], out)
        self.assertIn("area", out["missing_words"], out)

    def test_answer_area_stripped_from_ocr_source_when_layout_read(self):
        item = {"question_key": "qtest", "source_text": "pick the right word"}
        ocr = _ocr_item([_w("pick"), _w("Answer"), _w("Area")])
        out = FID.evaluate(item, None, _result(), ocr,
                           {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertNotIn("answer", out["missing_words"], out)
        self.assertNotIn("area", out["missing_words"], out)
        self.assertIn("pick", out["missing_words"], out)

    def test_statements_stripped_when_layout_read(self):
        item = {"question_key": "qtest",
                "source_text": "Statements pick the word"}
        out = FID.evaluate(item, None, _result(), _ocr_item([_w("pick")]),
                           {"area": {"kind": "yes_no_grid"}}, _cfg())
        self.assertNotIn("statements", out["missing_words"], out)
        self.assertIn("pick", out["missing_words"], out)

    def test_yes_no_stripped_only_for_yes_no_grid(self):
        item = {"question_key": "qtest",
                "source_text": "Yes No pick the word"}
        grid = FID.evaluate(item, None, _result(), _ocr_item([_w("pick")]),
                            {"area": {"kind": "yes_no_grid"}}, _cfg())
        self.assertNotIn("yes", grid["missing_words"], grid)
        self.assertNotIn("no", grid["missing_words"], grid)
        drop = FID.evaluate(item, None, _result(), _ocr_item([_w("pick")]),
                            {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertIn("yes", drop["missing_words"], drop)
        self.assertIn("no", drop["missing_words"], drop)

    def test_real_answer_word_in_export_is_never_stripped(self):
        # The stem itself uses the word "answer", so it must stay in the
        # source: stripping it would turn it into a false extra word.
        item = {"question_key": "qtest",
                "source_text": "select the answer Answer Area"}
        question = {"type": "inline_dropdown",
                    "learner": {"stem": [{"type": "paragraph", "content": [
                        {"text": "select the answer"}]}]}}
        out = FID.evaluate(item, question, _result(), _ocr_item([_w("select")]),
                           {"area": {"kind": "dropdown_lists"}}, _cfg())
        self.assertEqual(out["missing_words"], [], out)
        self.assertEqual(out["extra_words"], [], out)


if __name__ == "__main__":
    unittest.main()
