"""Synthetic tests only: no private owner questions, keys or artifacts."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_question_evidence.py"
spec = importlib.util.spec_from_file_location("audit_question_evidence", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample():
    return {
        "exam": "SYN-100", "total_questions": 2,
        "status": "FULL_RELEASE_BLOCKED", "full_answer_accuracy_verified": 0,
        "entries": [
            {"question_key": "q001", "source_urls": ["https://example.test/official"]},
            {"question_key": "q002", "release_approved": False},
        ],
        "potential_source_key_conflicts": ["q002"],
        "ai_source_supported_additional_20990101": {
            "cumulative_ai_supported": 1,
            "source_html_sha256_captured": False,
            "original_pdf_reinspected": False,
            "full_release_approved": 0,
        },
    }


class EvidenceAuditTest(unittest.TestCase):
    def test_draft_blocks_and_keeps_supported_distinct(self):
        r = module.audit(sample())
        self.assertEqual(r["status"], "blocked")
        self.assertEqual(r["ai_supported_checks_reported"], 1)
        self.assertEqual(r["fully_release_approved_records"], 0)
        self.assertIn("unresolved_source_key_conflicts", r["blockers"])
        self.assertIn("official_source_snapshots_unhashed", r["blockers"])

    def test_duplicate_question_key_is_invalid(self):
        d = sample()
        d["entries"][1]["question_key"] = "q001"
        self.assertIn("duplicate_key:q001", module.audit(d)["errors"])

    def test_missing_rows_fail_closed(self):
        d = sample()
        d["entries"].pop()
        self.assertEqual(module.audit(d)["status"], "invalid")

    def test_approval_without_review_is_invalid(self):
        d = sample()
        d["entries"][0]["release_approved"] = True
        self.assertIn("approval_without_signed_review:q001", module.audit(d)["errors"])

    def test_cli_saves_json_and_exits_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root)
            ledger = p / "ledger.json"
            out = p / "report.json"
            ledger.write_text(json.dumps(sample()), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(SCRIPT), str(ledger), "--output", str(out)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertEqual(json.loads(out.read_text())["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
