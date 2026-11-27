"""Tests for upstream patch v1.3.1-p003-drag-drop (P-003).

A drag_drop export keeps object slots (id, label, optional shape and
coords, with coords validated by the P-001 rule), keeps plain string
slots working, and copies prompt_template into learner.interaction.
Object slots and prompt_template round-trip and pass schema validation.
All fixtures here are synthetic; no real exam text is used.

Skipped unless a patched upstream checkout is available (CERTPASSLY_UPSTREAM
or skill/vendor/certpassly-exam-pipeline).
"""
import importlib.util
import json
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
FID = _load("fidelity")
VAL = _load("validate_question_v2")


def _item(slots, template="Drag {{s1}} and {{s2}} to the right boxes."):
    return {
        "question_key": "Q1", "question_type": "drag_drop",
        "answer_key_status": "owner_key",
        "answer_key": {"slots": {"s1": "a", "s2": "b"}},
        "prompt_text": "Drag each item to the right box.",
        "response_schema": {"content": {
            "prompt_template": template,
            "slots": slots,
        }},
    }


def _doc(question):
    return {
        "exam": {"vendor": "Example", "certification": "Example",
                 "exam_code": "EX-DD", "name": "Example",
                 "domains": [{"name": "Format examples", "weight": 100}]},
        "questions": [question],
    }


@unittest.skipUnless(EX is not None, "no upstream checkout")
class DragDropSlotsTests(unittest.TestCase):
    def test_object_slots_keep_id_label_shape_coords(self):
        out = EX.export_item(_item([
            {"id": "s1", "label": "Alpha", "shape": "rect",
             "coords": [0.1, 0.2, 0.3, 0.4]},
        ]))
        slots = out["learner"]["interaction"]["drag_slots"]
        self.assertEqual(slots, [
            {"id": "s1", "label": "Alpha", "shape": "rect",
             "coords": [0.1, 0.2, 0.3, 0.4]},
        ])

    def test_string_slots_still_work(self):
        out = EX.export_item(_item(["plain-string-slot"]))
        slots = out["learner"]["interaction"]["drag_slots"]
        self.assertEqual(slots, ["plain-string-slot"])

    def test_mixed_slots_round_trip(self):
        out = EX.export_item(_item([
            {"id": "s1", "label": "Alpha", "shape": "rect",
             "coords": [0.1, 0.2, 0.3, 0.4]},
            {"id": "s2", "label": "Beta"},
            "plain-string-slot",
        ]))
        slots = out["learner"]["interaction"]["drag_slots"]
        self.assertEqual(slots[0]["id"], "s1")
        self.assertEqual(slots[1], {"id": "s2", "label": "Beta"})
        self.assertEqual(slots[2], "plain-string-slot")

    def test_bad_slot_coords_are_dropped_but_slot_is_kept(self):
        out = EX.export_item(_item([
            {"id": "s3", "label": "Gamma", "shape": "rect",
             "coords": [2.0, 0.2, 0.3, 0.4]},
        ]))
        slots = out["learner"]["interaction"]["drag_slots"]
        self.assertEqual(slots, [
            {"id": "s3", "label": "Gamma", "shape": "rect"},
        ])

    def test_prompt_template_is_copied(self):
        out = EX.export_item(_item([
            {"id": "s1", "label": "Alpha"},
        ]))
        self.assertEqual(
            out["learner"]["interaction"]["prompt_template"],
            "Drag {{s1}} and {{s2}} to the right boxes.")

    def test_object_slots_pass_schema_validation(self):
        up = _upstream_dir()
        schema = json.loads(
            (up / "reference" / "site-format" / "v2"
             / "question.schema.json").read_text(encoding="utf-8"))
        registry = json.loads(
            (up / "reference" / "site-format" / "v2"
             / "question_types.json").read_text(encoding="utf-8"))
        question = EX.export_item(_item([
            {"id": "s1", "label": "Alpha", "shape": "rect",
             "coords": [0.1, 0.2, 0.3, 0.4]},
            {"id": "s2", "label": "Beta"},
            "plain-string-slot",
        ]))
        errs = VAL.validate_doc(_doc(question), schema, registry)
        self.assertEqual(errs, [])

    def test_fidelity_keeps_object_slot_labels_in_coverage_text(self):
        question = EX.export_item(_item([
            {"id": "s1", "label": "Alpha", "shape": "rect",
             "coords": [0.1, 0.2, 0.3, 0.4]},
        ]))
        text = FID.export_text(question)
        self.assertIn("Alpha", text)


if __name__ == "__main__":
    unittest.main()
