import importlib.util
from pathlib import Path
import unittest

S = Path(__file__).resolve().parents[1] / "scripts" / "restore_explicit_multi_select_count.py"
spec = importlib.util.spec_from_file_location("restore_explicit_multi_select_count", S)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def example(stem, kind="multiple_select", n=None):
    obj = {"question_key": "q001", "type": kind, "learner": {"stem":
        {"format": "html", "text": "<p>" + stem + "</p>"},
        "interaction": {"options": [{"id": "a", "text": "A"},
            {"id": "b", "text": "B"}, {"id": "c", "text": "C"}]}}}
    if n is not None:
        obj["learner"]["interaction"]["choose_n"] = n
    return obj

class CountRepairTests(unittest.TestCase):
    def test_clear_two_stem(self):
        obj = example("Which two statements are true?")
        obj["answer"] = {"answer_key": {"correct_option_ids": ["a", "b"]}}
        before = obj["answer"].copy()
        changed, why = mod.correct(obj)
        self.assertTrue(changed)
        self.assertEqual(obj["learner"]["interaction"]["choose_n"], 2)
        self.assertEqual(obj["learner"]["constraints"]["choose_n"], 2)
        self.assertEqual(obj["answer"], before)

    def test_what_are_two(self):
        obj = example("What are two reasons?")
        self.assertTrue(mod.correct(obj)[0])

    def test_vague_never_guess(self):
        obj = example("Select all options that apply")
        self.assertFalse(mod.correct(obj)[0])

    def test_preserve_existing_n(self):
        obj = example("Which two options?", n=3)
        self.assertFalse(mod.correct(obj)[0])
        self.assertEqual(obj["learner"]["interaction"]["choose_n"], 3)

    def test_other_type_not_changed(self):
        obj = example("Which two options?", kind="single_choice")
        self.assertFalse(mod.correct(obj)[0])

if __name__ == "__main__":
    unittest.main()
