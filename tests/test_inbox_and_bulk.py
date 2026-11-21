#!/usr/bin/env python3
"""Inbox ingest and bulk list/summary tests. PDFs and exams are synthetic."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inbox_ingest as I
import list_bulk_exams as L
import write_bulk_summary as S

MIN_PDF = b"%PDF-1.1\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<<>>\n%%EOF\n"
MIN_PDF_B = b"%PDF-1.1\n1 0 obj\n<< /Type /Catalog /New true >>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def write_pdf(path: Path, body: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inbox = self.root / "inbox"

    def test_new_exam_then_duplicate_skip_then_update(self):
        write_pdf(self.inbox / "TEST-UPDATE-B" / "v1.pdf", MIN_PDF)
        report = I.ingest_inbox(self.root, self.inbox)
        self.assertEqual(report["new_exams"], 1)
        self.assertEqual(report["updates"], 0)
        self.assertEqual(report["skipped_duplicate"], 0)
        sources = json.loads((self.root / "exams" / "TEST-UPDATE-B" / "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(sources["current_version"], 1)
        self.assertEqual(len(sources["sources"]), 1)
        self.assertEqual(sources["sources"][0]["status"], "active")
        self.assertTrue((self.root / "exams" / "TEST-UPDATE-B" / "source-versions" / "v1" / "v1.pdf").is_file())
        self.assertTrue(any((self.root / "exams" / "TEST-UPDATE-B" / "source").glob("*.pdf")))
        self.assertTrue((self.inbox / "TEST-UPDATE-B" / "ingested" / "v1.pdf").is_file())
        self.assertFalse((self.inbox / "TEST-UPDATE-B" / "v1.pdf").exists())

        # Same bytes again: skip, no new version, v1 kept.
        write_pdf(self.inbox / "TEST-UPDATE-B" / "v1-copy.pdf", MIN_PDF)
        report = I.ingest_inbox(self.root, self.inbox)
        self.assertEqual(report["new_exams"], 0)
        self.assertEqual(report["updates"], 0)
        self.assertEqual(report["skipped_duplicate"], 1)
        sources = json.loads((self.root / "exams" / "TEST-UPDATE-B" / "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(sources["current_version"], 1)
        self.assertEqual(len(sources["sources"]), 1)

        # New bytes: version 2, v1 superseded, not deleted.
        write_pdf(self.inbox / "TEST-UPDATE-B" / "v2.pdf", MIN_PDF_B)
        report = I.ingest_inbox(self.root, self.inbox)
        self.assertEqual(report["updates"], 1)
        sources = json.loads((self.root / "exams" / "TEST-UPDATE-B" / "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(sources["current_version"], 2)
        self.assertEqual(len(sources["sources"]), 2)
        by_v = {row["version"]: row for row in sources["sources"]}
        self.assertEqual(by_v[1]["status"], "superseded")
        self.assertEqual(by_v[2]["status"], "active")
        self.assertTrue((self.root / "exams" / "TEST-UPDATE-B" / "source-versions" / "v1" / "v1.pdf").is_file())
        self.assertTrue((self.root / "exams" / "TEST-UPDATE-B" / "source-versions" / "v2" / "v2.pdf").is_file())
        current = list((self.root / "exams" / "TEST-UPDATE-B" / "source").glob("*.pdf"))
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].name, "v2.pdf")

    def test_register_existing_source_once(self):
        exam = self.root / "exams" / "TEST-BULK-B"
        write_pdf(exam / "source" / "seed.pdf", MIN_PDF)
        first = I.register_existing_sources(self.root)
        self.assertEqual(first["registered"], 1)
        second = I.register_existing_sources(self.root)
        self.assertEqual(second["registered"], 0)
        self.assertEqual(second["skipped_duplicate"], 1)
        sources = json.loads((exam / "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(len(sources["sources"]), 1)

    def test_invalid_code_skipped(self):
        write_pdf(self.inbox / "not a code" / "x.pdf", MIN_PDF)
        report = I.ingest_inbox(self.root, self.inbox)
        self.assertEqual(report["skipped_invalid"], 1)
        self.assertEqual(report["pdfs_seen"], 0)

    def test_counts_only_stdout(self):
        write_pdf(self.inbox / "TEST-UPDATE-B" / "v1.pdf", MIN_PDF)
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            I.main(["--raw-root", str(self.root), "--inbox-root", str(self.inbox)])
        out = buf.getvalue()
        self.assertIn("new_exams=1", out)
        self.assertNotIn("v1.pdf", out)


class BulkListTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _exam_with_source(self, code: str, body: bytes, index_sha: str | None = None) -> Path:
        exam = self.root / "exams" / code
        write_pdf(exam / "source" / "seed.pdf", body)
        I.register_existing_sources(self.root)
        if index_sha is not None:
            (exam / "questions-index.json").write_text(json.dumps({
                "exam_code": code,
                "source_sha256": index_sha,
                "questions": [],
            }), encoding="utf-8")
        return exam

    def test_list_explicit_and_new_and_all(self):
        sha = hashlib.sha256(MIN_PDF).hexdigest()
        sha_b = hashlib.sha256(MIN_PDF_B).hexdigest()
        self._exam_with_source("EXAM-SAME", MIN_PDF, index_sha=sha)
        self._exam_with_source("EXAM-NEWSHA", MIN_PDF_B, index_sha=sha)
        self._exam_with_source("EXAM-NOINDEX", MIN_PDF, index_sha=None)
        self.assertEqual(L.list_exams(self.root, "EXAM-SAME,EXAM-NEWSHA"), ["EXAM-SAME", "EXAM-NEWSHA"])
        got = L.list_exams(self.root, "new")
        self.assertIn("EXAM-NEWSHA", got)
        self.assertIn("EXAM-NOINDEX", got)
        self.assertNotIn("EXAM-SAME", got)
        all_codes = L.list_exams(self.root, "all")
        self.assertEqual(all_codes, ["EXAM-NEWSHA", "EXAM-NOINDEX", "EXAM-SAME"])

    def test_inbox_update_is_selected_for_new(self):
        actions = [{"exam_code": "EXAM-SAME", "action": "update", "version": 2}]
        sha = hashlib.sha256(MIN_PDF).hexdigest()
        self._exam_with_source("EXAM-SAME", MIN_PDF, index_sha=sha)
        self.assertEqual(L.list_exams(self.root, "new", actions), ["EXAM-SAME"])


class BulkSummaryTests(unittest.TestCase):
    def test_table_marks_failed_and_counts(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        ok = root / "exams" / "EXAM-OK" / "runs" / "99" / "phase-reports"
        ok.mkdir(parents=True)
        (ok / "public-summary.json").write_text(json.dumps({
            "exported_question_count": 10,
            "held_count": 2,
            "promotion": "not_promoted",
        }), encoding="utf-8")
        (ok / "change-report.json").write_text(json.dumps({
            "counts": {"same": 8, "changed": 1, "new": 1, "retired": 0, "duplicate": 0},
        }), encoding="utf-8")
        # EXAM-FAIL has no run dir
        out = root / "reports" / "bulk" / "99"
        payload = S.write_summary.__wrapped__ if hasattr(S.write_summary, "__wrapped__") else None
        rows = [
            S.row_for_exam(root, "EXAM-OK", "99"),
            S.row_for_exam(root, "EXAM-FAIL", "99"),
        ]
        summary = S.write_summary(out / "summary.json", out / "summary.md", rows, "99")
        self.assertEqual(summary["failed_count"], 1)
        self.assertFalse(rows[0]["failed"])
        self.assertTrue(rows[1]["failed"])
        self.assertEqual(rows[0]["exported"], 10)
        self.assertEqual(rows[0]["changed"], 1)
        md = (out / "summary.md").read_text(encoding="utf-8")
        self.assertIn("EXAM-OK", md)
        self.assertIn("EXAM-FAIL", md)
        self.assertIn("| yes |", md)


if __name__ == "__main__":
    unittest.main()
