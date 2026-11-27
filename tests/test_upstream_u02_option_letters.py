"""Tests for upstream patch v1.3.1-u02-option-letters.

The text-layer option splitter must recognise options G and H, not just A-F,
or they merge into option F. The OCR path already used A-H; the text-layer
splitter must match. All fixtures here are synthetic; no real exam text is
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


def _load(name):
    up = _upstream_dir()
    if up is None:
        return None
    os.environ["CERTPASSLY_SKILL_ROOT"] = str(up)
    sys.path.insert(0, str(up / "scripts"))
    spec = importlib.util.spec_from_file_location(name, up / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


UP = _upstream_dir()
EXTRACT = _load("extract_owner_pdf") if UP is not None else None
STRUCTS = _load("text_structures") if UP is not None else None


class OptionLetterTests(unittest.TestCase):
    def setUp(self):
        if EXTRACT is None or STRUCTS is None:
            self.skipTest("no upstream checkout")

    def _parse(self, lines):
        opts = {}
        for line in lines:
            for pat in EXTRACT.OPTION_PATTERNS:
                m = pat.match(line)
                if m:
                    opts[m.group(1).lower()] = (m.group(2) or "").strip()
                    break
        return opts

    def test_options_a_through_h_parse(self):
        lines = ["A. Validation rule", "B. Workflow rule", "C. Approval process",
                 "D. Sharing rule", "E. Apex triggers", "F. Escalation rule",
                 "G. Assignment rule", "H. Auto-response rule."]
        opts = self._parse(lines)
        self.assertEqual(len(opts), 8)
        self.assertEqual(opts["g"], "Assignment rule")
        self.assertEqual(opts["h"], "Auto-response rule.")
        self.assertEqual(opts["f"], "Escalation rule")

    def test_options_a_through_f_still_parse(self):
        lines = ["A. one", "B. two", "C. three", "D. four", "E. five", "F. six"]
        opts = self._parse(lines)
        self.assertEqual(len(opts), 6)

    def test_letter_regex_covers_g_and_h(self):
        self.assertTrue(STRUCTS.LETTERS.search("G"))
        self.assertTrue(STRUCTS.LETTERS.search("H"))
        self.assertEqual(STRUCTS.LETTERS.findall("ABGH"), ["A", "B", "G", "H"])


if __name__ == "__main__":
    unittest.main()
