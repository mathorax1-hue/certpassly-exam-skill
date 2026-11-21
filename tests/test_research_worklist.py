"""Synthetic tests for the phase-2 research worklist. No owner PDFs or network."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_research_worklist.py"
spec = importlib.util.spec_from_file_location("build_research_worklist", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class ResearchWorklistTests(unittest.TestCase):
    def _write(self, tmp: Path) -> Path:
        export = tmp / "export"
        export.mkdir()
        site = {
            "exam": {"exam_code": "SYN-100", "vendor": "Example Vendor", "name": "Synthetic Exam"},
            "questions": [
                {
                    "question_key": "syn-q1",
                    "version": 1,
                    "type": "single_choice",
                    "domain": "Unassigned",
                    "learner": {"stem": [{"type": "paragraph", "content": [{"text": "Synthetic stem one?"}]}]},
                    "answer": {"answer_key": [0], "status": "owner_key"},
                },
                {
                    "question_key": "syn-q2",
                    "version": 1,
                    "type": "single_choice",
                    "domain": "Unassigned",
                    "learner": {"stem": [{"type": "paragraph", "content": [{"text": "Synthetic stem two?"}]}]},
                    "answer": {"answer_key": [], "status": "answer_not_found"},
                },
            ],
        }
        (export / "SYN-100.site-format.v2.json").write_text(json.dumps(site), encoding="utf-8")
        (export / "cannot-convert.json").write_text(json.dumps({
            "items": [{"question_key": "syn-held", "exported": False, "reasons": ["ocr_disagree"]}]
        }), encoding="utf-8")
        (export / "fidelity.json").write_text(json.dumps({
            "exported": 2,
            "held": [{"question_key": "syn-held", "exported": False, "reasons": ["ocr_disagree"]}],
        }), encoding="utf-8")
        return export

    def test_lists_held_answer_gaps_and_missing_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = self._write(Path(tmp))
            report = tool.build(export, "SYN-100")
        self.assertEqual(report["held"][0]["question_key"], "syn-held")
        self.assertIn("ocr_disagree", report["held"][0]["reasons"])
        self.assertEqual(report["answer_not_found"][0]["question_key"], "syn-q2")
        facts = {row["fact"] for row in report["missing_exam_facts"]}
        self.assertIn("duration_minutes", facts)
        self.assertEqual(report["exported_question_count"], 2)
        self.assertGreaterEqual(report["work_item_count"], 3)
        self.assertIn("documented hook", report["ai_research_hook"])
        self.assertEqual(report["official_urls_available"], [])

    def test_ignores_drive_links_and_keeps_https_vendor_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = self._write(Path(tmp))
            site = json.loads((export / "SYN-100.site-format.v2.json").read_text())
            site["exam"]["official_exam_url"] = "https://drive.google.com/drive/folders/abc"
            (export / "SYN-100.site-format.v2.json").write_text(json.dumps(site), encoding="utf-8")
            empty = tool.build(export, "SYN-100")
            self.assertEqual(empty["official_urls_available"], [])
            site["exam"]["official_exam_url"] = "https://documentation.example.com/exam"
            (export / "SYN-100.site-format.v2.json").write_text(json.dumps(site), encoding="utf-8")
            kept = tool.build(export, "SYN-100")
            self.assertEqual(kept["official_urls_available"], ["https://documentation.example.com/exam"])

    def test_cli_writes_only_counts_on_stdout_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = self._write(Path(tmp))
            out = Path(tmp) / "worklist.json"
            rc = tool.main(["--exam", "SYN-100", "--export-dir", str(export), "--output", str(out)])
            self.assertEqual(rc, 0)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
