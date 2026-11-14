"""B4: 30-type registry compatibility and responsive image geometry tests.

Self-contained synthetic registry flags derived from the upstream v1 public
metadata (pinned upstream 13dea6b). Never a substitute for real site UI tests.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from certpassly.media_prep.media_layout import (
    css_rect, layout_fingerprint, load_type_registry, validate_layout,
)

PUBLISHABLE = {
    "single_choice": "selection", "multiple_select": "selection",
    "true_false": "selection", "image_based_choice": "selection",
    "scenario_standalone": "container", "yes_no_matrix": "matrix",
    "single_choice_matrix": "matrix", "inline_dropdown": "cloze",
    "multi_blank_dropdown": "cloze", "ordering": "sequence",
    "matching": "association", "categorization": "association",
    "drag_drop": "interaction", "hotspot_single": "image_regions",
    "hotspot_multi": "image_regions", "case_study_group": "container",
}
NONPUBLISHABLE = {
    "multi_select_matrix": "matrix", "text_cloze": "cloze",
    "active_screen": "image_regions", "short_text": "constructed",
    "numeric": "constructed", "multimedia_stimulus": "content",
    "testlet": "container",
}
DISABLED = {
    "sectioned_delivery": "delivery", "unscored_pretest": "delivery",
    "adaptive_delivery": "delivery", "simulation_ui": "performance",
    "terminal_task": "performance", "lab_task": "performance",
    "code_answer": "constructed",
}
SHA = "a" * 64


def registry():
    out = {}
    for key, family in PUBLISHABLE.items():
        out[key] = {"enabled": True, "publishable": True, "family": family}
    for key, family in NONPUBLISHABLE.items():
        out[key] = {"enabled": True, "publishable": False, "family": family}
    for key, family in DISABLED.items():
        out[key] = {"enabled": False, "publishable": False, "family": family}
    return {"types": out}


def layout(type_key):
    out = {
        "schema_version": "media-layout-v1",
        "question_id": "synthetic-q001", "type_key": type_key,
        "source": {"pdf_sha256": SHA, "page": 1, "rotation_deg": 0,
                   "crop": [0.1, 0.1, 0.9, 0.9]},
        "media": [], "controls": {},
    }
    family = registry()["types"][type_key]["family"]
    if family == "matrix":
        out["controls"] = {"rows": [{"id": "row-1"}], "columns": [{"id": "yes"}, {"id": "no"}]}
    elif family == "cloze":
        out["controls"] = {"blanks": [{"id": "slot-1", "rect": [0.2, 0.3, 0.5, 0.5]}]}
    elif family in ("interaction", "association"):
        out["controls"] = {"draggable_items": [{"id": "item-1"}],
                           "drop_zones": [{"id": "zone-1", "rect": [0.4, 0.4, 0.7, 0.6]}]}
    elif family == "sequence":
        out["controls"] = {"items": [{"id": "item-1"}, {"id": "item-2"}]}
    elif family == "image_regions":
        out["controls"] = {"hotspots": [{"id": "hot-1", "rect": [0.2, 0.2, 0.4, 0.4]}]}
    elif family == "container":
        out["shared_stimulus_id"] = "stimulus-1"
        out["child_question_ids"] = ["child-1"]
    if type_key in ("hotspot_single", "hotspot_multi"):
        out["media"] = [{"file": "media/synthetic.png", "sha256": SHA,
                         "source_sha256": SHA, "role": "interactive_background"}]
    return out


class MediaLayout30TypeTests(unittest.TestCase):
    def test_registry_exact_30_flags(self):
        r = registry()
        self.assertEqual(len(r["types"]), 30)
        self.assertEqual(len(PUBLISHABLE), 16)
        self.assertEqual(len(NONPUBLISHABLE), 7)
        self.assertEqual(len(DISABLED), 7)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "registry.json"
            p.write_text(json.dumps(r), encoding="utf-8")
            self.assertEqual(len(load_type_registry(p)["types"]), 30)

    def test_pinned_registry_rejects_swapped_publishability_flags(self):
        changed = registry()
        changed["types"]["single_choice"]["publishable"] = False
        changed["types"]["multi_select_matrix"]["publishable"] = True
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "modified-registry.json"
            p.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_type_registry(p)

    def test_all_16_publishable_types_have_synthetic_contract(self):
        r = registry()
        for typ in sorted(PUBLISHABLE):
            with self.subTest(typ=typ):
                report = validate_layout(layout(typ), r)
                self.assertEqual(report["status"], "PASS", report["reasons"])
                self.assertEqual(report["site_ui_status"], "UNTESTED")

    def test_all_14_unpublishable_or_disabled_types_block(self):
        r = registry()
        for typ in sorted(set(NONPUBLISHABLE) | set(DISABLED)):
            with self.subTest(typ=typ):
                report = validate_layout(layout(typ), r)
                self.assertEqual(report["status"], "BLOCKED")
                self.assertFalse(report["publishable_in_registry"])

    def test_unknown_type_fails_without_downgrade(self):
        case = layout("single_choice")
        case["type_key"] = "surprise_unknown"
        self.assertEqual(validate_layout(case, registry())["status"], "BLOCKED")

    def test_keys_and_selected_states_are_forbidden_recursively(self):
        for payload in ({"correct_option_ids": ["A"]}, {"selected_option": "A"},
                        {"nested": [{"answer_key": "A"}]}, {"correct_answers": ["A"]}):
            case = layout("single_choice")
            case["controls"] = payload
            self.assertEqual(validate_layout(case, registry())["status"], "BLOCKED")

    def test_geometry_missing_duplicate_clipped_invalid_blocks(self):
        base = layout("yes_no_matrix")
        base["controls"]["rows"] = [{"id": "r"}, {"id": "r"}]
        self.assertEqual(validate_layout(base, registry())["status"], "BLOCKED")
        for rect in ([0.1, 0.2, 1.1, 0.3], [0.5, 0.5, 0.2, 0.9],
                     [float("nan"), 0, 1, 1], [-0.1, 0, 1, 1]):
            x = layout("inline_dropdown")
            x["controls"]["blanks"][0]["rect"] = rect
            self.assertEqual(validate_layout(x, registry())["status"], "BLOCKED")

    def test_media_requires_source_sha_and_safe_local_path(self):
        for bad_path in ("../key.png", "/private/mark.jpg", "https://site/x.png", "img\\evil.png"):
            x = layout("hotspot_single")
            x["media"][0]["file"] = bad_path
            self.assertEqual(validate_layout(x, registry())["status"], "BLOCKED")
        x = layout("hotspot_single")
        x["media"][0]["source_sha256"] = ""
        self.assertEqual(validate_layout(x, registry())["status"], "BLOCKED")

    def test_rotations_and_responsive_scaling(self):
        src = [0.1, 0.2, 0.3, 0.4]
        for width in (320, 375, 768, 1024, 1440):
            for dpr in (1, 2):
                for zoom in (1, 2):
                    for rotation in (0, 90, 180, 270):
                        with self.subTest(width=width, dpr=dpr, zoom=zoom,
                                          rotation=rotation):
                            result = css_rect(src, width=width, height=500,
                                              dpr=dpr, zoom=zoom,
                                              rotation_deg=rotation)
                            self.assertEqual(len(result["css"]), 4)
                            x0, y0, x1, y1 = result["css"]
                            self.assertLess(x0, x1)
                            self.assertLess(y0, y1)
                            self.assertGreaterEqual(x0, 0)
                            self.assertLessEqual(x1, width * zoom)
                            self.assertAlmostEqual(result["device"][0], x0 * dpr, 3)

    def test_geometry_clockwise_rotation_equivalence(self):
        r = css_rect([0.1, 0.2, 0.3, 0.4], width=1000,
                     height=600, rotation_deg=90)
        self.assertEqual(r["css"], [600.0, 60.0, 800.0, 180.0])

    def test_fingerprint_repeatable_and_sensitive_to_change(self):
        x = layout("single_choice")
        self.assertEqual(layout_fingerprint(x), layout_fingerprint(copy.deepcopy(x)))
        changed = copy.deepcopy(x)
        changed["source"]["page"] = 2
        self.assertNotEqual(layout_fingerprint(x), layout_fingerprint(changed))


if __name__ == "__main__":
    unittest.main()
