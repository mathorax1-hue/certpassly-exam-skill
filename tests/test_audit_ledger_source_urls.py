#!/usr/bin/env python3
"""Wholly synthetic adversarial tests for audit_ledger_source_urls.

Every fixture below is fabricated synthetic data. No real exam content, real
vendor pages, or private evidence appears in this file.
"""
from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
audit_ledger_source_urls = importlib.import_module("audit_ledger_source_urls")

HOST = "learn.example-vendor.test"


def make_page(tmp: Path, name: str, body: str) -> str:
    html = f"<html><body><main>{body}</main></body></html>"
    (tmp / (name + ".html")).write_text(html, encoding="utf-8")
    return name + ".html"


def sha_of(tmp: Path, name: str) -> tuple[str, int]:
    import hashlib
    path = tmp / name
    if not path.exists():
        return "0" * 64, 0
    blob = path.read_bytes()
    return hashlib.sha256(blob).hexdigest(), len(blob)


def make_receipt(tmp: Path, name: str, url: str, page: str, quote: str,
                 mode: str = "downloaded", sha: str | None = None,
                 bytes_: int | None = None) -> None:
    real_sha, real_bytes = sha_of(tmp, page)
    record = {
        "source_url": url,
        "sha256": sha or real_sha,
        "bytes": bytes_ if bytes_ is not None else real_bytes,
        "captured_at_utc": "2026-01-01T00:00:00+00:00",
        "content_type": "text/html",
        "capture_mode": mode,
        "quote": quote,
        "official_domain_allowlist": [HOST],
        "answer_correctness_approved": False,
        "human_review_approved": False,
        "saved_content_path": page,
    }
    (tmp / (name + ".source.json")).write_text(json.dumps(record), encoding="utf-8")


def make_ledger(*records) -> dict:
    return {"total_questions": len(records),
            "entries": list(records)}


def run(tmp: Path, ledger: dict, linkage: dict | None = None):
    return audit_ledger_source_urls.audit(
        ledger, tmp, linkage, [HOST])


class TestAuditLedgerSourceUrls(unittest.TestCase):
    def test_all_verified_with_shared_url_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            p2 = make_page(tmp, "synthetic-b", "Synthetic beta quota text")
            make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text")
            make_receipt(tmp, "synthetic-b", f"https://{HOST}/b", p2, "Synthetic beta quota text")
            ledger = make_ledger(
                {"question_key": "synthetic1", "source_urls": [f"https://{HOST}/a", f"https://{HOST}/b"]},
                {"question_key": "synthetic2", "source_urls": [f"https://{HOST}/b"]},
            )
            report = run(tmp, ledger)
            self.assertEqual(report["status"], "all_url_instances_byte_verified")
            self.assertEqual(report["counts"]["url_instances"], 3)
            self.assertEqual(report["counts"]["unique_ledger_urls"], 2)
            self.assertEqual(report["counts"]["records_with_source_urls"], 2)
            # one shared URL across two records is legitimate many-to-one reuse
            self.assertEqual(report["counts"]["shared_urls"], {f"https://{HOST}/b": ["synthetic1", "synthetic2"]})

    def test_second_url_of_record_missing_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text")
            ledger = make_ledger(
                {"question_key": "synthetic1",
                 "source_urls": [f"https://{HOST}/a", f"https://{HOST}/missing"],
                 "source_snapshot_sha256": sha_of(tmp, p1)[0]},  # single-hash shortcut must NOT suffice
            )
            report = run(tmp, ledger)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("no byte-verified receipt" in b["reason"] for b in report["blockers"]))

    def test_wrong_saved_file_sha_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            fake = "f" * 64
            make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text", sha=fake)
            ledger = make_ledger({"question_key": "synthetic1", "source_urls": [f"https://{HOST}/a"]})
            report = run(tmp, ledger)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("SHA-256 mismatch" in b["reason"] for b in report["blockers"]))

    def test_missing_page_file_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", "gone.html", "quote")
            ledger = make_ledger({"question_key": "synthetic1", "source_urls": [f"https://{HOST}/a"]})
            report = run(tmp, ledger)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("saved page missing" in b["reason"] for b in report["blockers"]))

    def test_quote_drift_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "quote absent from the page")
            ledger = make_ledger({"question_key": "synthetic1", "source_urls": [f"https://{HOST}/a"]})
            report = run(tmp, ledger)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("proof quote absent" in b["reason"] for b in report["blockers"]))

    def test_offline_capture_mode_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text",
                         mode="local_file_unverified_origin")
            ledger = make_ledger({"question_key": "synthetic1", "source_urls": [f"https://{HOST}/a"]})
            report = run(tmp, ledger)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("capture_mode" in b["reason"] for b in report["blockers"]))

    def test_undocumented_redirect_fails_and_documented_redirect_passes(self):
        ledger = make_ledger({"question_key": "synthetic1",
                              "source_urls": [f"https://{HOST}/old"]})
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            make_receipt(tmp, "synthetic-a", f"https://{HOST}/new", p1, "Synthetic alpha quota text")
            report = run(tmp, ledger)
            self.assertEqual(report["status"], "blocked")  # no linkage: redirect is unexplained
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            make_receipt(tmp, "synthetic-a", f"https://{HOST}/new", p1, "Synthetic alpha quota text")
            linkage = {"records": [{"question_key": "synthetic1", "url_links": [
                {"ledger_url": f"https://{HOST}/old", "final_redirected_url": f"https://{HOST}/new"}]}]}
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "all_url_instances_byte_verified")
            self.assertEqual(report["counts"]["redirected_instances"], 1)

    def test_duplicate_receipts_for_one_url_fail(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            p2 = make_page(tmp, "synthetic-b", "Synthetic beta quota text")
            make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text")
            make_receipt(tmp, "synthetic-b", f"https://{HOST}/a", p2, "Synthetic beta quota text")
            ledger = make_ledger({"question_key": "synthetic1", "source_urls": [f"https://{HOST}/a"]})
            report = run(tmp, ledger)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("duplicate receipt" in b["reason"] for b in report["blockers"]))

    def test_orphan_evidence_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            p2 = make_page(tmp, "synthetic-orphan", "Synthetic orphan quota text")
            make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text")
            make_receipt(tmp, "synthetic-orphan", f"https://{HOST}/orphan", p2, "Synthetic orphan quota text")
            ledger = make_ledger({"question_key": "synthetic1", "source_urls": [f"https://{HOST}/a"]})
            report = run(tmp, ledger)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("not referenced by any ledger URL" in b["reason"] for b in report["blockers"]))

    def test_non_allowlisted_host_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            make_receipt(tmp, "synthetic-a", f"https://evil-{HOST}/a", p1, "Synthetic alpha quota text")
            ledger = make_ledger({"question_key": "synthetic1", "source_urls": [f"https://evil-{HOST}/a"]})
            report = run(tmp, ledger)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("allowlist" in b["reason"] for b in report["blockers"]))

    def test_byte_length_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text", bytes_=1)
            ledger = make_ledger({"question_key": "synthetic1", "source_urls": [f"https://{HOST}/a"]})
            report = run(tmp, ledger)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("byte length mismatch" in b["reason"] for b in report["blockers"]))

    def test_records_without_urls_are_out_of_scope(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger = make_ledger({"question_key": "synthetic1", "source_urls": []},
                                 {"question_key": "synthetic2"})
            report = run(tmp, ledger)
            self.assertEqual(report["status"], "all_url_instances_byte_verified")
            self.assertEqual(report["counts"]["records_with_source_urls"], 0)

    def test_invalid_ledger_shapes(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self.assertEqual(run(tmp, {"entries": "nope"})["status"], "invalid")
            self.assertEqual(run(tmp, {})["status"], "invalid")


if __name__ == "__main__":
    unittest.main()
