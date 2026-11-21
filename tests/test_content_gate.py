"""Synthetic tests for the phase-3 content gate."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_content_gate.py"
spec = importlib.util.spec_from_file_location("check_content_gate", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def site(explanation=None, status="owner_key"):
    body = explanation if explanation is not None else []
    return {
        "exam": {"exam_code": "SYN-100"},
        "questions": [{
            "question_key": "syn-q1",
            "type": "single_choice",
            "learner": {"stem": [{"type": "paragraph", "content": [{"text": "Synthetic stem"}]}]},
            "answer": {
                "answer_key": [0],
                "status": status,
                "explanation": body,
            },
        }],
    }


class ContentGateTests(unittest.TestCase):
    def _file(self, tmp: Path, doc) -> Path:
        p = tmp / "SYN-100.site-format.v2.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        return p

    def test_missing_authored_content_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = tool.check(self._file(Path(tmp), site([])))
        self.assertEqual(report["status"], "blocked_needs_content")
        self.assertFalse(report["authored_fields_present"])

    def test_clean_explanation_passes(self):
        expl = [{"type": "paragraph", "content": [{"text": "The official guide says option A is correct."}]}]
        with tempfile.TemporaryDirectory() as tmp:
            report = tool.check(self._file(Path(tmp), site(expl)))
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["flag_count"], 0)

    def test_flags_dash_emoji_seller_and_review_markup(self):
        cases = [
            "This uses an em dash \u2014 here.",
            "Nice job \U0001F44D",
            "Bought from Innovior ITTech last year.",
            "See <!-- writing-review:start --> notes",
        ]
        for text in cases:
            expl = [{"type": "paragraph", "content": [{"text": text}]}]
            with tempfile.TemporaryDirectory() as tmp, self.subTest(text=text[:20]):
                report = tool.check(self._file(Path(tmp), site(expl)))
                self.assertEqual(report["status"], "blocked_violations")
                self.assertGreater(report["flag_count"], 0)

    def test_does_not_flag_seller_name_only_in_stem(self):
        doc = site([])
        doc["questions"][0]["learner"]["stem"][0]["content"][0]["text"] = "Innovior ITTech appears only in the stem"
        with tempfile.TemporaryDirectory() as tmp:
            report = tool.check(self._file(Path(tmp), doc))
        self.assertEqual(report["status"], "blocked_needs_content")
        self.assertEqual(report["flag_count"], 0)

    def test_cli_nonzero_when_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._file(Path(tmp), site([]))
            out = Path(tmp) / "gate.json"
            rc = tool.main(["--site-file", str(path), "--output", str(out)])
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
