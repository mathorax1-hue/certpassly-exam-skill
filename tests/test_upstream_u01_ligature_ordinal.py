"""Tests for upstream patch v1.3.1-u01-ligature-ordinal.

The ligature repair must not turn an ordinal suffix into a word ("2nd" into
"2find"): a lowercase token right after a digit is an ordinal, not a word
missing a leading ligature. All fixtures here are synthetic; no real exam
text is used.

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
REPAIR = _load("text_repair") if UP is not None else None


class LigatureOrdinalTests(unittest.TestCase):
    def setUp(self):
        if REPAIR is None:
            self.skipTest("no upstream checkout")

    def test_ordinal_suffixes_are_left_alone(self):
        for text in ("either the 2nd or the 3rd parameter",
                     "the 1st and 2nd options",
                     "the 4th item and the 5th"):
            fixed, changes = REPAIR.repair(text)
            self.assertEqual(fixed, text, text)
            self.assertEqual(changes, [], text)

    def test_real_ligature_repairs_still_work(self):
        fixed, changes = REPAIR.repair("the rst of the files")
        self.assertEqual(fixed, "the first of the files")
        self.assertEqual(changes, [("rst", "first")])
        fixed, changes = REPAIR.repair("ngerprint scanner")
        self.assertEqual(fixed, "fingerprint scanner")
        self.assertEqual(changes, [("ngerprint", "fingerprint")])

    def test_nd_is_not_turned_into_find(self):
        fixed, changes = REPAIR.repair("have in either the 2nd or the 3rd parameter?")
        self.assertNotIn("2find", fixed)
        self.assertEqual(fixed, "have in either the 2nd or the 3rd parameter?")


if __name__ == "__main__":
    unittest.main()
