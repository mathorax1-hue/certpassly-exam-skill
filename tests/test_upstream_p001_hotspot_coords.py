"""Tests for upstream patch v1.3.1-p001-hotspot-coords (P-001).

A hotspot region whose coordinates are outside 0..1 is not measurable.
It is skipped, never clamped, and the exported item is marked unsure
(reviewer_needed). All fixtures here are synthetic; no real exam text
is used.

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


def _regions(coords_list, shape="rect"):
    return {"regions": [
        {"id": f"h{i + 1}", "label": f"region {i + 1}", "shape": shape,
         "coords": coords}
        for i, coords in enumerate(coords_list)
    ]}


def _item(regions):
    return {
        "question_key": "Q1", "question_type": "hotspot_single",
        "answer_key_status": "owner_key",
        "answer_key": {"region_ids": ["h1"]},
        "prompt_text": "Click the right region.",
        "response_schema": {"content": {"regions": regions}},
    }


@unittest.skipUnless(EX is not None, "no upstream checkout")
class HotspotCoordsTests(unittest.TestCase):
    def test_pixel_coords_give_no_region(self):
        got = EX.hotspot_regions(
            _regions([[100, 200, 150, 250]]))
        self.assertEqual(got, [])

    def test_negative_coord_gives_no_region(self):
        got = EX.hotspot_regions(
            _regions([[-0.1, 0.2, 0.3, 0.4]]))
        self.assertEqual(got, [])

    def test_good_coords_pass_through_unchanged(self):
        got = EX.hotspot_regions(
            _regions([[0.1, 0.2, 0.3, 0.4]]))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["coords"], [0.1, 0.2, 0.3, 0.4])

    def test_one_bad_region_does_not_drop_a_good_one(self):
        got = EX.hotspot_regions(_regions([
            [100, 200, 150, 250],
            [0.1, 0.2, 0.3, 0.4],
        ]))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["id"], "h2")

    def test_non_numeric_coord_gives_no_region(self):
        got = EX.hotspot_regions(
            _regions([["x", 0.2, 0.3, 0.4]]))
        self.assertEqual(got, [])

    def test_pixel_coords_item_has_no_region_and_is_unsure(self):
        out = EX.export_item(_item([
            {"id": "h1", "label": "x", "shape": "rect",
             "coords": [100, 200, 150, 250]},
        ]))
        self.assertNotIn("hotspot_regions",
                         out["learner"].get("interaction") or {})
        self.assertTrue(out["answer"]["reviewer_needed"])

    def test_good_coords_item_is_not_unsure(self):
        out = EX.export_item(_item([
            {"id": "h1", "label": "x", "shape": "rect",
             "coords": [0.1, 0.2, 0.3, 0.4]},
        ]))
        self.assertEqual(len(out["learner"]["interaction"]["hotspot_regions"]), 1)
        self.assertFalse(out["answer"]["reviewer_needed"])


if __name__ == "__main__":
    unittest.main()
