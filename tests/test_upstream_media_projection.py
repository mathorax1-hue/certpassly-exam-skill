"""B4 projected upstream response schema -> answer-free media contract.

All examples are synthesized, even when the real upstream payload shape is
used. This is NOT a real-site renderer or factual answer correctness test.
"""
from __future__ import annotations
import json
import unittest

from certpassly.media_prep.media_layout import project_upstream_question
from tests.test_media_layout_contract import layout, registry, PUBLISHABLE, NONPUBLISHABLE, DISABLED


def upstream_question(typ):
    sample = layout(typ)
    controls = sample["controls"]
    family = registry()["types"][typ]["family"]
    content = {}
    shape_map = {}
    if family == "matrix":
        content["rows"] = controls["rows"]
        content["columns"] = controls["columns"]
    elif family == "cloze":
        content["blanks"] = [{"id": r["id"], "label": "Synthetic blank"}
                             for r in controls["blanks"]]
        shape_map["blanks"] = {r["id"]: r["rect"] for r in controls["blanks"]}
    elif family in ("association", "interaction"):
        content["left"] = controls["draggable_items"]
        content["right"] = [{"id": r["id"], "text": "Synthetic target"}
                            for r in controls["drop_zones"]]
        shape_map["drop_zones"] = {r["id"]: r["rect"] for r in controls["drop_zones"]}
    elif family == "image_regions":
        content["regions"] = [{"id": r["id"], "label": "Synthetic region",
                               "normalized_coordinates": r["rect"]}
                              for r in controls["hotspots"]]
    elif family == "sequence":
        content["items"] = controls["items"]
    elif family == "selection":
        content["options"] = [{"id": "A", "text": "Synthetic answer A"},
                              {"id": "B", "text": "Synthetic answer B"}]
    q = {"question_key": sample["question_id"],
         "question_type": typ, "response_schema": {"type": typ, "content": content},
         "answer_key": {"correct_option_ids": ["A"]},
         "answer_raw": "A",
         "selected_option": "A",
         "hidden_correct_answer": "SYNTHETIC_SECRET_NEVER_EXPORT"}
    if family == "container":
        q["shared_stimulus_id"] = sample["shared_stimulus_id"]
        q["child_question_ids"] = sample["child_question_ids"]
    return q, sample["source"], sample["media"], shape_map


class UpstreamMediaProjectionTests(unittest.TestCase):
    def test_16_publishable_types_project_without_any_answer_keys(self):
        for typ in sorted(PUBLISHABLE):
            with self.subTest(type_key=typ):
                q, source, media, geometry = upstream_question(typ)
                projected = project_upstream_question(q, source=source,
                                  media=media, registry=registry(), geometry=geometry)
                self.assertEqual(projected["verification"]["status"], "PASS",
                                 projected["verification"]["reasons"])
                self.assertEqual(projected["site_ui_status"], "UNTESTED")
                serialized = json.dumps(projected)
                for forbidden in ("SYNTHETIC_SECRET_NEVER_EXPORT",
                                  "correct_option_ids", "answer_key",
                                  "selected_option", "answer_raw"):
                    self.assertNotIn(forbidden, serialized)
                self.assertEqual(projected["layout"]["type_key"], typ)

    def test_14_other_types_remain_blocked(self):
        for typ in sorted(set(NONPUBLISHABLE) | set(DISABLED)):
            with self.subTest(type_key=typ):
                q, source, media, geometry = upstream_question(typ)
                rep = project_upstream_question(q, source=source, media=media,
                                                registry=registry(), geometry=geometry)
                self.assertEqual(rep["verification"]["status"], "BLOCKED")

    def test_missing_interaction_geometry_blocks_without_fabricating_pixels(self):
        for typ in ("drag_drop", "inline_dropdown", "matching"):
            with self.subTest(type_key=typ):
                q, source, media, _ = upstream_question(typ)
                rep = project_upstream_question(q, source=source, media=media,
                                                registry=registry(), geometry={})
                self.assertEqual(rep["verification"]["status"], "BLOCKED")
                self.assertTrue(rep["verification"]["reasons"])

    def test_question_type_response_schema_disagreement_raises(self):
        q, source, media, geom = upstream_question("drag_drop")
        q["response_schema"]["type"] = "single_choice"
        with self.assertRaises(ValueError):
            project_upstream_question(q, source=source, media=media,
                                      registry=registry(), geometry=geom)

    def test_answer_region_coordinates_follow_stable_id(self):
        q, source, media, geom = upstream_question("hotspot_multi")
        q["response_schema"]["content"]["regions"] = [
            {"id": "h2", "normalized_coordinates": [0.3, 0.4, 0.6, 0.8]},
            {"id": "h1", "normalized_coordinates": [0.1, 0.1, 0.2, 0.2]},
        ]
        rep = project_upstream_question(q, source=source, media=media,
                                        registry=registry(), geometry={})
        self.assertEqual(rep["verification"]["status"], "PASS")
        self.assertEqual({x["id"]: x["rect"] for x in rep["layout"]["controls"]["hotspots"]},
                         {"h2": [0.3, 0.4, 0.6, 0.8], "h1": [0.1, 0.1, 0.2, 0.2]})

    def test_unknown_question_type_not_coerced_to_single_choice(self):
        q, source, media, geom = upstream_question("single_choice")
        q["question_type"] = "unknown_type"
        q["response_schema"]["type"] = "unknown_type"
        with self.assertRaises(ValueError):
            project_upstream_question(q, source=source, media=media,
                                      registry=registry(), geometry=geom)


if __name__ == "__main__":
    unittest.main()
