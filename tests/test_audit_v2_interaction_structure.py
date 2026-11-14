import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_v2_interaction_structure.py"
spec = importlib.util.spec_from_file_location("audit_v2_interaction_structure", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

def doc(kind, interaction):
    return {"question_key": "q001", "version": 1, "type": kind, "learner":
            {"stem": {"format": "html", "text": "<p>Prompt</p>"},
             "interaction": interaction}}

class InteractionStructureTests(unittest.TestCase):
    def test_choice(self):
        q = doc("single_choice", {"options":
            [{"id": "a", "text": "First"}, {"id": "b", "text": "Second"}],
            "choose_n": 1})
        self.assertEqual(tool.audit_one(q, "q001.v1.json")["errors"], [])

    def test_matrix(self):
        q = doc("yes_no_matrix", {"rows": [{"id": "r1", "text": "Statement"}],
            "columns": [{"id": "yes", "text": "Yes"}, {"id": "no", "text": "No"}]})
        self.assertEqual(tool.audit_one(q, "q001.v1.json")["errors"], [])

    def test_dropdown(self):
        q = doc("inline_dropdown", {"prompt_with_slots": "Select {{blank1}}",
            "slots": [{"id": "blank1", "input": "dropdown", "choices":
                [{"id": "c1", "text": "One"}, {"id": "c2", "text": "Two"}]}]})
        self.assertEqual(tool.audit_one(q, "q001.v1.json")["errors"], [])
        q["learner"]["interaction"]["prompt_with_slots"] = "Select {{wrong}}"
        self.assertIn("slot references do not match slot definitions",
                      tool.audit_one(q, "q001.v1.json")["errors"])

    def test_leak_and_unsafe_html(self):
        q = doc("single_choice", {"options":
            [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}], "choose_n": 1})
        q["learner"]["answer_key"] = {"correct": "a"}
        q["learner"]["stem"]["text"] = "<script>alert(1)</script>"
        q["learner"]["media"] = [{"href": "/media/q001-answer-area.jpg"}]
        problems = tool.audit_one(q, "q001.v1.json")["errors"]
        self.assertIn("answer material embedded in learner object", problems)
        self.assertIn("unsafe HTML detected", problems)
        self.assertIn("reviewer/answer media leaked to learner", problems)

    def test_invalid_slot_does_not_crash(self):
        q = doc("inline_dropdown", {"prompt_with_slots": "Select {{blank1}}",
            "slots": [{"id": None, "input": "dropdown",
                       "choices": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]}]})
        self.assertTrue(tool.audit_one(q, "q001.v1.json")["errors"])

    def test_directory_never_self_approves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "q001.v1.json").write_text(json.dumps(doc("single_choice",
                {"options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                 "choose_n": 1})), encoding="utf-8")
            report = tool.audit_directory(folder, expected=1)
            self.assertTrue(report["automated_structure_pass"])
            self.assertFalse(report["source_fidelity_verified"])
            self.assertFalse(report["importer_tested"])

if __name__ == "__main__":
    unittest.main()
