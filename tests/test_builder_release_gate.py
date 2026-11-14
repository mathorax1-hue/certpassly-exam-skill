"""B5 strict package preflight: external HMAC, original PDF bytes, keys."""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

try:
    import fitz
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

if HAS_PDF:
    from certpassly.media_prep.manifest import entries_hash, package_integrity_hash, receipt_hmac
    from certpassly.media_prep.errors import PrivacyViolationError
    from certpassly.media_prep.privacy_gate import verify_release_candidate


@unittest.skipUnless(HAS_PDF, "requires PyMuPDF")
class StrictPrivateReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="strict-synthetic-")
        root = Path(self.temp.name)
        self.pdf = root / "source.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Synthetic source — no original exam content")
        doc.save(str(self.pdf))
        doc.close()
        raw = self.pdf.read_bytes()
        self.source_sha = hashlib.sha256(raw).hexdigest()
        self.manifest = root / "manifest.json"
        self.receipt = root / "trusted-source.json"
        self.zip = root / "draft.zip"
        self.key = "synthetic-test-only-hmac-0123456789"
        self.data = {
            "schema_version": "image-manifest-v1",
            "exam_code": "SYNTHETIC-ONLY",
            "source_pdf_sha256": self.source_sha,
            "source_pdf_bytes": len(raw),
            "generated_by": "synthetic-b5-test",
            "questions": [], "reviewer_only_assets": [],
            "counts": {"eligible": 0, "blocked": 0},
            "integrity": {},
        }
        self.data["integrity"]["entries_sha256"] = entries_hash([])
        self.data["integrity"]["package_integrity_sha256"] = package_integrity_hash(self.data)
        self.data["integrity"]["receipt_sha256_hmac"] = receipt_hmac(
            self.key.encode(), package_integrity_hash(self.data))
        self.manifest.write_text(json.dumps(self.data), encoding="utf-8")
        self.receipt.write_text(json.dumps({"pdf_files": [
            {"name": "synthetic.pdf", "sha256": self.source_sha, "bytes": len(raw)}]}),
            encoding="utf-8")
        with zipfile.ZipFile(self.zip, "w") as z:
            z.writestr("import/questions.json", '{"questions": []}')

    def tearDown(self):
        self.temp.cleanup()

    def _run(self):
        with patch.dict(os.environ, {"CERTPASSLY_MANIFEST_KEY": self.key}):
            return verify_release_candidate(
                str(self.manifest), str(self.zip),
                source_pdf=str(self.pdf), source_receipt=str(self.receipt))

    def test_valid_synthetic_receipts_pass_technical_only(self):
        report = self._run()
        self.assertTrue(report["passed"], report["problems"])
        self.assertEqual(report["technical_privacy_preflight"], "PASS")
        self.assertEqual(report["site_ui_status"], "UNTESTED")
        self.assertEqual(report["human_approval_status"], "NOT_APPROVED")

    def test_changed_original_pdf_refused_even_with_old_manifest_and_receipt(self):
        self.pdf.write_bytes(self.pdf.read_bytes() + b"changed bytes")
        with self.assertRaises(PrivacyViolationError):
            self._run()

    def test_missing_external_source_receipt_refused(self):
        with patch.dict(os.environ, {"CERTPASSLY_MANIFEST_KEY": self.key}):
            with self.assertRaises(PrivacyViolationError):
                verify_release_candidate(str(self.manifest), str(self.zip),
                                         source_pdf=str(self.pdf), source_receipt="")

    def test_wrong_external_hmac_key_refused(self):
        with patch.dict(os.environ, {"CERTPASSLY_MANIFEST_KEY": "wrong-key"}):
            report = verify_release_candidate(str(self.manifest), str(self.zip),
                     source_pdf=str(self.pdf), source_receipt=str(self.receipt))
        self.assertFalse(report["passed"])
        self.assertTrue(any(p["reason"] == "RECEIPT_HMAC_MISMATCH"
                            for p in report["problems"]))

    def test_scoring_key_refused_by_direct_library(self):
        with zipfile.ZipFile(self.zip, "w") as z:
            z.writestr("import/questions.json", '{"correct_option_ids": ["A"]}')
        report = self._run()
        self.assertFalse(report["passed"])
        self.assertTrue(report["flags"])


if __name__ == "__main__":
    unittest.main()
