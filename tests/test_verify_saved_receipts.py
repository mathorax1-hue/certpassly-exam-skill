"""No-network synthetic validation of stored source evidence snapshots."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import capture_official_source as capture

spec = importlib.util.spec_from_file_location("verify_saved_receipts", SCRIPTS / "verify_saved_receipts.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
URL = "https://learn.microsoft.com/synthetic"
HOST = ["learn.microsoft.com"]
BLOB = b"<html><body>Synthetic proof quote</body></html>"


def make(folder, mode="downloaded"):
    r = capture.receipt_from_bytes(URL, BLOB, "Synthetic proof quote", HOST, mode=mode)
    return capture.save_private_capture(folder, "sample", BLOB, r)


class ReceiptVerifierTests(unittest.TestCase):
    def test_clean_local_bytes_not_promoted(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            make(folder)
            report = mod.verify_receipts(folder, HOST)
            self.assertEqual(report["status"], "stored_source_integrity_consistent_pending_semantic_review")
            self.assertEqual(report["integrity_checked"], 1)
            self.assertFalse(report["answer_correctness_verified"])
            self.assertFalse(report["release_approved"])

    def test_modified_bytes_block(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            make(folder)
            (folder / "sample.html").write_text("TAMPERED", encoding="utf-8")
            self.assertTrue(any("SHA-256 mismatch" in e["reason"]
                                for e in mod.verify_receipts(folder, HOST)["errors"]))

    def test_modified_quote_block(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            p = make(folder)
            d = json.loads(p.read_text())
            d["quote"] = "Quote not in bytes"
            p.write_text(json.dumps(d))
            self.assertTrue(any("proof quote absent" in e["reason"]
                                for e in mod.verify_receipts(folder, HOST)["errors"]))

    def test_unknown_official_domain_block(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            make(folder)
            self.assertEqual(mod.verify_receipts(folder, ["attacker.test"])["status"], "blocked")

    def test_offline_source_origin_does_not_claim_live_capture(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            make(folder, "local_file_unverified_origin")
            self.assertTrue(any("unverified" in e["reason"]
                                for e in mod.verify_receipts(folder, HOST)["errors"]))

    def test_path_escape_block(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t)
            p = make(folder)
            d = json.loads(p.read_text())
            d["saved_content_path"] = "../private-secret.txt"
            p.write_text(json.dumps(d))
            self.assertTrue(any("invalid saved content filename" in e["reason"]
                                for e in mod.verify_receipts(folder, HOST)["errors"]))

    def test_missing_receipts_block(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(mod.verify_receipts(Path(t), HOST)["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
