"""Synthetic tests for raw-exam workspace preparation. No real owner PDF text."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_exam_workspace.py"
spec = importlib.util.spec_from_file_location("prepare_exam_workspace", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class PrepareWorkspaceTests(unittest.TestCase):
    def test_copies_pdf_and_writes_rights(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw" / "SYN-100"
            (raw / "source").mkdir(parents=True)
            blob = b"%PDF-1.4 synthetic fixture " + (b"x" * 500)
            pdf = raw / "source" / "SYN-100.pdf"
            pdf.write_bytes(blob)
            digest = hashlib.sha256(blob).hexdigest()
            (raw / "manifest.json").write_text(json.dumps({
                "exam_code": "SYN-100",
                "vendor_slug": "example",
                "owner_rights_statement": "The owner affirmed permission to use the supplied PDFs on 2026-11-11.",
                "pdf_files": [{"name": "SYN-100.pdf", "sha256": digest, "bytes": len(blob)}],
            }), encoding="utf-8")
            ws = Path(tmp) / "ws"
            report = tool.prepare(raw, ws, "SYN-100", None)
            self.assertEqual(report["files"][0]["sha256"], digest)
            self.assertTrue((ws / "owner-files" / "SYN-100" / "SYN-100.pdf").is_file())
            yaml_text = (ws / "config" / "pipeline.yaml").read_text(encoding="utf-8")
            self.assertIn("owner affirmed permission", yaml_text)
            self.assertIn("brand: CertPassly", yaml_text)
            self.assertIn("disclaimer:", yaml_text)

    def test_copies_review_corrections(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw" / "SYN-100"
            (raw / "source").mkdir(parents=True)
            (raw / "review").mkdir()
            blob = b"%PDF-1.4 synthetic fixture " + (b"x" * 500)
            pdf = raw / "source" / "SYN-100.pdf"
            pdf.write_bytes(blob)
            digest = hashlib.sha256(blob).hexdigest()
            (raw / "manifest.json").write_text(json.dumps({
                "exam_code": "SYN-100",
                "vendor_slug": "example",
                "owner_rights_statement": "The owner affirmed permission to use the supplied PDFs on 2026-11-11.",
                "pdf_files": [{"name": "SYN-100.pdf", "sha256": digest, "bytes": len(blob)}],
            }), encoding="utf-8")
            (raw / "review" / "owner-corrections.json").write_text(json.dumps({
                "schema_version": 1,
                "exam_code": "SYN-100",
                "corrections": [],
            }), encoding="utf-8")
            ws = Path(tmp) / "ws"
            report = tool.prepare(raw, ws, "SYN-100", None)
            self.assertEqual(report["review_files"], ["owner-corrections.json"])
            dest = ws / "review" / "owner-corrections.json"
            self.assertTrue(dest.is_file())
            self.assertEqual(json.loads(dest.read_text())["corrections"], [])

    def test_copies_ai_reads_subdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw" / "SYN-100"
            (raw / "source").mkdir(parents=True)
            (raw / "review" / "ai-reads").mkdir(parents=True)
            blob = b"%PDF-1.4 synthetic fixture " + (b"x" * 500)
            (raw / "source" / "SYN-100.pdf").write_bytes(blob)
            digest = hashlib.sha256(blob).hexdigest()
            (raw / "manifest.json").write_text(json.dumps({
                "exam_code": "SYN-100",
                "vendor_slug": "example",
                "owner_rights_statement": "The owner affirmed permission to use the supplied PDFs on 2026-11-11.",
                "pdf_files": [{"name": "SYN-100.pdf", "sha256": digest, "bytes": len(blob)}],
            }), encoding="utf-8")
            (raw / "review" / "ai-reads.json").write_text(json.dumps({
                "schema_version": 1, "exam_code": "SYN-100", "items": []
            }), encoding="utf-8")
            (raw / "review" / "ai-reads" / "q001.json").write_text(json.dumps({
                "question_key": "q001", "transcribed_text": "sample",
                "confidence": 0.5, "source": "ai_vision", "image_sha256": ""
            }), encoding="utf-8")
            ws = Path(tmp) / "ws"
            report = tool.prepare(raw, ws, "SYN-100", None)
            self.assertIn("ai-reads.json", report["review_files"])
            self.assertIn("ai-reads/q001.json", report["review_files"])
            self.assertTrue((ws / "review" / "ai-reads.json").is_file())
            self.assertTrue((ws / "review" / "ai-reads" / "q001.json").is_file())

    def test_rejects_git_lfs_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw" / "SYN-100"
            (raw / "source").mkdir(parents=True)
            pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"ab" * 32 + b"\nsize 12\n"
            (raw / "source" / "SYN-100.pdf").write_bytes(pointer)
            (raw / "manifest.json").write_text(json.dumps({
                "exam_code": "SYN-100",
                "vendor_slug": "example",
                "owner_rights_statement": "The owner affirmed permission.",
                "pdf_files": [{"name": "SYN-100.pdf", "sha256": "00", "bytes": 12}],
            }), encoding="utf-8")
            with self.assertRaises(SystemExit):
                tool.prepare(raw, Path(tmp) / "ws", "SYN-100", None)


if __name__ == "__main__":
    unittest.main()
