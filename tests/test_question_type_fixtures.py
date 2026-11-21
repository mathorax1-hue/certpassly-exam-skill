"""Question-type regression set: one TEST-ONLY fixture per publishable type.

Unit checks run everywhere (stdlib only). The end-to-end check runs the PDF
through the pinned upstream pipeline and is skipped unless CERTPASSLY_UPSTREAM
points at a patched upstream checkout and tesseract is installed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "question-types"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner = _load("run_question_type_fixtures", ROOT / "scripts" / "run_question_type_fixtures.py")
promote = _load("promote_ready_exam", ROOT / "scripts" / "promote_ready_exam.py")
TRUTH = json.loads((FIX / "truth.json").read_text(encoding="utf-8"))


class FixtureTruthTests(unittest.TestCase):
    def test_fixture_is_marked_test_only(self):
        self.assertTrue(TRUTH["test_only"])
        self.assertTrue(TRUTH["never_promote"])
        self.assertEqual(TRUTH["exam_code"], "QTYPE-FIXTURE")
        self.assertTrue((FIX / "make_fixtures.py").is_file())

    def test_every_publishable_type_has_a_fixture(self):
        types = {q["type"] for q in TRUTH["questions"] if not q.get("held")}
        self.assertEqual(sorted(set(runner.PUBLISHABLE) - types), [])

    def test_every_staging_type_has_a_fixture_marked_draft_only(self):
        types = {q["type"] for q in TRUTH["questions"] if not q.get("held")}
        self.assertEqual(sorted(set(runner.STAGING) - types), [])
        for q in TRUTH["questions"]:
            if q.get("type") in runner.STAGING and not q.get("held"):
                self.assertTrue(q.get("staging_draft_only"), q["question_key"])

    def test_blocked_and_partial_cases_are_expected_holds(self):
        held = [q for q in TRUTH["questions"] if q.get("held")]
        self.assertGreaterEqual(len(held), 6)
        for q in held:
            self.assertTrue(q.get("hold_reason_contains"))

    def test_grader_mirror_accepts_correct_and_rejects_wrong(self):
        for q in TRUTH["questions"]:
            if q.get("held"):
                continue
            with self.subTest(q=q["question_key"], type=q["type"]):
                key = q["answer_key"]
                self.assertTrue(runner.grade(q["type"], key, runner.correct_response(q["type"], key)))
                self.assertFalse(runner.grade(q["type"], key, runner.wrong_response(q["type"], key)))

    def test_ordering_response_is_item_to_position(self):
        self.assertEqual(runner.correct_response("ordering", [1, 2, 0]), {"1": 1, "2": 2, "0": 3})
        self.assertFalse(runner.grade("ordering", [1, 2, 0], ["1", "2", "0"]))

    def test_promotion_refuses_the_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site.json"
            site.write_text(json.dumps({"exam": {"exam_code": "QTYPE-FIXTURE"}, "questions": []}), encoding="utf-8")
            self.assertTrue(promote.is_test_fixture("QTYPE-FIXTURE", site))
            self.assertTrue(promote.is_test_fixture("OTHER", site))
            self.assertFalse(promote.is_test_fixture("KCNA", None))

    def test_promotion_marks_staging_types_draft_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site.json"
            site.write_text(json.dumps({
                "exam": {"exam_code": "DEMO"},
                "questions": [
                    {"question_key": "q001", "type": "single_choice", "tags": []},
                    {"question_key": "q002", "type": "numeric", "tags": ["staging_draft_only"]},
                ],
            }), encoding="utf-8")
            rows = promote.staging_items(site)
            self.assertEqual([r["question_key"] for r in rows], ["q002"])
            self.assertEqual(rows[0]["publication"], "draft_only")


def _has_fixture_tools() -> bool:
    try:
        import PIL  # noqa: F401
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


@unittest.skipUnless(os.environ.get("CERTPASSLY_UPSTREAM") and shutil.which("tesseract") and _has_fixture_tools(),
                     "needs CERTPASSLY_UPSTREAM (patched upstream), tesseract, reportlab and Pillow")
class FixtureEndToEndTests(unittest.TestCase):
    def test_pdf_builds_every_type_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            rc = runner.main(["--upstream", os.environ["CERTPASSLY_UPSTREAM"], "--work", str(Path(tmp) / "w"),
                              "--report", str(report)])
            data = json.loads(report.read_text(encoding="utf-8"))
            bad = [c for c in data["checks"] if not c["ok"]]
            self.assertEqual(bad, [])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
