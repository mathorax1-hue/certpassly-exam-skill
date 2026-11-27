"""Tests for upstream patch v1.3.1-p002-rect-count (P-002).

A hotspot region with the wrong number of coordinates for its shape is
not measurable and is skipped, the same as too few. A rect needs exactly
4 numbers, a circle exactly 3, a polygon an even count of at least 6.
Nothing is padded or trimmed. All fixtures here are synthetic; no real
exam text is used.

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
    if env and Path(env, "scripts", "export_question_v2.py").is_file():
        return Path(env)
    vend = ROOT / "vendor" / "certpassly-exam-pipeline"
    if (vend / "scripts" / "export_question_v2.py").is_file():
        return vend
    return None


def _load(name):
    up = _upstream_dir()
    if up is None:
        return None
    sys.path.insert(0, str(up / "scripts"))
    spec = importlib.util.spec_from_file_location(name, up / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


EX = _load("export_question_v2")


def _regions(coords, shape="rect"):
    return {"regions": [
        {"id": "h1", "label": "x", "shape": shape, "coords": coords},
    ]}


@unittest.skipUnless(EX is not None, "no upstream checkout")
class RectCountTests(unittest.TestCase):
    def test_rect_too_few_is_skipped_not_padded(self):
        self.assertEqual(EX.hotspot_regions(_regions([0.1, 0.2])), [])

    def test_rect_too_many_is_skipped_not_trimmed(self):
        self.assertEqual(
            EX.hotspot_regions(_regions([0.1, 0.2, 0.3, 0.4, 0.5])), [])

    def test_rect_exactly_four_passes(self):
        got = EX.hotspot_regions(_regions([0.1, 0.2, 0.3, 0.4]))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["coords"], [0.1, 0.2, 0.3, 0.4])

    def test_circle_too_few_is_skipped(self):
        self.assertEqual(
            EX.hotspot_regions(_regions([0.1, 0.2], shape="circle")), [])

    def test_circle_too_many_is_skipped(self):
        self.assertEqual(
            EX.hotspot_regions(_regions([0.1, 0.2, 0.3, 0.4],
                                        shape="circle")), [])

    def test_circle_exactly_three_passes(self):
        got = EX.hotspot_regions(_regions([0.1, 0.2, 0.3], shape="circle"))
        self.assertEqual(len(got), 1)

    def test_polygon_odd_count_is_skipped(self):
        self.assertEqual(
            EX.hotspot_regions(
                _regions([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
                         shape="polygon")), [])

    def test_polygon_even_count_of_six_passes(self):
        got = EX.hotspot_regions(
            _regions([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], shape="polygon"))
        self.assertEqual(len(got), 1)

    def test_polygon_too_few_is_skipped(self):
        self.assertEqual(
            EX.hotspot_regions(_regions([0.1, 0.2, 0.3, 0.4],
                                        shape="polygon")), [])


if __name__ == "__main__":
    unittest.main()
