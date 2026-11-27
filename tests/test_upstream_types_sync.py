"""Tests for ORDER-005 Phase 2: the 32-type sync and the reviewer-graded hold.

The pipeline type list is synced to the site's 32 types (new audio_response
and long_answer, both reviewer-graded and blocked). Four staging types
(multi_select_matrix, text_cloze, short_text, numeric) are promoted to
publishable; active_screen stays staging. Reviewer-graded types
(code_answer, lab_task, simulation_ui, terminal_task, audio_response,
long_answer) are never auto-built from a PDF: a stem carrying one of their
markers is held with that reason before any matching rule can assign a
different type. All fixtures here are synthetic; no real exam text is used.

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
QTYPES = _load("qtypes") if UP is not None else None
CHECK_BANK = _load("check_bank") if UP is not None else None
VALIDATE = _load("validate_question_v2") if UP is not None else None


def _registry():
    return json.loads((UP / "reference" / "site-format" / "v2" / "question_types.json").read_text())


class RegistrySyncTests(unittest.TestCase):
    def setUp(self):
        if UP is None:
            self.skipTest("no upstream checkout")

    def test_counts_are_32_20_3_9(self):
        reg = _registry()
        self.assertEqual(reg["counts"], {"types": 32, "publishable": 20, "staging": 3, "blocked": 9})
        self.assertEqual(len(reg["lists"]["all"]), 32)
        self.assertEqual(len(reg["lists"]["publishable"]), 20)
        self.assertEqual(len(reg["lists"]["staging"]), 3)
        self.assertEqual(len(reg["lists"]["blocked"]), 9)

    def test_four_types_promoted_to_publishable(self):
        reg = _registry()
        for typ in ("multi_select_matrix", "text_cloze", "short_text", "numeric"):
            self.assertTrue(reg["types"][typ]["publishable"], typ)
            self.assertTrue(reg["types"][typ]["enabled"], typ)
            self.assertIn(typ, reg["lists"]["publishable"])
            self.assertNotIn(typ, reg["lists"]["staging"])

    def test_two_new_types_are_blocked_reviewer_graded(self):
        reg = _registry()
        for typ in ("audio_response", "long_answer"):
            entry = reg["types"][typ]
            self.assertEqual(entry["family"], "constructed")
            self.assertFalse(entry["enabled"])
            self.assertFalse(entry["publishable"])
            self.assertFalse(entry["auto_grade"])
            self.assertFalse(entry["uses_options"])
            self.assertIn(typ, reg["lists"]["blocked"])
            self.assertIn(typ, reg["lists"]["all"])

    def test_active_screen_stays_staging(self):
        reg = _registry()
        self.assertFalse(reg["types"]["active_screen"]["publishable"])
        self.assertIn("active_screen", reg["lists"]["staging"])
        self.assertEqual(reg["lists"]["staging"],
                         ["active_screen", "multimedia_stimulus", "testlet"])

    def test_note_names_32_keys(self):
        reg = _registry()
        self.assertIn("32 keys", reg["source_path_note"])


class ReviewerHoldTests(unittest.TestCase):
    def setUp(self):
        if QTYPES is None:
            self.skipTest("no upstream checkout")
        self.rules = QTYPES.load_rules()

    def _item(self, stem, options=None):
        return {"question_key": "qtest", "stem": stem,
                "options": options or {}, "answer_raw": "A" if options else "",
                "source_text": stem}

    def test_lab_with_options_holds_instead_of_single_choice(self):
        item = self._item("LAB - Sign in to the lab and create a user account.",
                          {"a": "Create it", "b": "Delete it", "c": "Reset it"})
        r = QTYPES.classify_detailed(item, rules=self.rules)
        self.assertTrue(r["held"])
        self.assertEqual(r["type"], "lab_task")
        self.assertIn("reviewer-graded type lab_task", r["reason"])

    def test_lab_without_options_holds(self):
        item = self._item("LAB - Simulation: sign in to the lab and set up the network.")
        r = QTYPES.classify_detailed(item, rules=self.rules)
        self.assertTrue(r["held"])
        self.assertEqual(r["type"], "lab_task")

    def test_code_with_options_holds(self):
        item = self._item("Write the code that sorts the list.",
                          {"a": "Use sort()", "b": "Use reverse()"})
        r = QTYPES.classify_detailed(item, rules=self.rules)
        self.assertTrue(r["held"])
        self.assertEqual(r["type"], "code_answer")
        self.assertIn("reviewer-graded type code_answer", r["reason"])

    def test_simulation_holds(self):
        item = self._item("SIMULATION - A sharing rule has been deleted. What should be done?")
        r = QTYPES.classify_detailed(item, rules=self.rules)
        self.assertTrue(r["held"])
        self.assertEqual(r["type"], "simulation_ui")

    def test_terminal_holds(self):
        item = self._item("In the terminal, type the command that lists the files.",
                          {"a": "ls", "b": "cd"})
        r = QTYPES.classify_detailed(item, rules=self.rules)
        self.assertTrue(r["held"])
        self.assertEqual(r["type"], "terminal_task")

    def test_audio_holds(self):
        item = self._item("Record your answer to the question.")
        r = QTYPES.classify_detailed(item, rules=self.rules)
        self.assertTrue(r["held"])
        self.assertEqual(r["type"], "audio_response")

    def test_long_answer_holds(self):
        item = self._item("Write a long answer explaining the design.")
        r = QTYPES.classify_detailed(item, rules=self.rules)
        self.assertTrue(r["held"])
        self.assertEqual(r["type"], "long_answer")

    def test_plain_choice_question_still_exports(self):
        item = self._item("Which service stores objects in buckets?",
                          {"a": "Block storage", "b": "Object storage"})
        r = QTYPES.classify_detailed(item, rules=self.rules)
        self.assertFalse(r["held"])
        self.assertEqual(r["type"], "single_choice")

    def test_laboratory_word_is_not_a_lab_marker(self):
        item = self._item("Which laboratory result confirms the diagnosis?",
                          {"a": "Blood test", "b": "X-ray"})
        r = QTYPES.classify_detailed(item, rules=self.rules)
        self.assertNotEqual(r["type"], "lab_task")


class BankAndCheckerTests(unittest.TestCase):
    def setUp(self):
        if CHECK_BANK is None or VALIDATE is None:
            self.skipTest("no upstream checkout")

    def test_check_bank_knows_32_types(self):
        self.assertEqual(len(CHECK_BANK.DEFAULT_TYPES), 32)
        self.assertIn("audio_response", CHECK_BANK.DEFAULT_TYPES)
        self.assertIn("long_answer", CHECK_BANK.DEFAULT_TYPES)

    def test_checker_accepts_the_two_new_types(self):
        reg = _registry()
        for typ in ("audio_response", "long_answer"):
            errs = VALIDATE.check_registry(
                {"question_key": "qtest", "type": typ}, reg, "test.json")
            self.assertEqual(errs, [], typ)

    def test_checker_rejects_unknown_type_with_registry_count(self):
        reg = _registry()
        errs = VALIDATE.check_registry(
            {"question_key": "qtest", "type": "not_a_type"}, reg, "test.json")
        self.assertEqual(len(errs), 1)
        self.assertIn("32-key", errs[0])


if __name__ == "__main__":
    unittest.main()
