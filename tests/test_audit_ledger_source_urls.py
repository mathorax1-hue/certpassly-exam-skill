#!/usr/bin/env python3
"""Wholly synthetic adversarial tests for audit_ledger_source_urls.

Every fixture below is fabricated synthetic data. No real exam content, real
vendor pages, or private evidence appears in this file.

DEV-005 additions: per-record ledger evidence blocks (the ``blocks`` fixtures)
must be validated fail closed: missing blocks on URL-bearing records, wrong
count/order, forged or altered receipt/SHA/bytes/timestamps, cross-question
redirect substitution, wrong final targets, missing duplicate instances, blocks
on records without source_urls, orphan/unknown linkage mappings, missing
linkage records, shared-with inconsistencies, vacuous zero-URL success, and the
explicitly reduced assurance of the no-blocks read-only mode.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
audit_ledger_source_urls = importlib.import_module("audit_ledger_source_urls")

HOST = "learn.example-vendor.test"
FIELD = "official_source_evidence_20261112"


def make_page(tmp: Path, name: str, body: str) -> str:
    html = f"<html><body><main>{body}</main></body></html>"
    (tmp / (name + ".html")).write_text(html, encoding="utf-8")
    return name + ".html"


def sha_of(tmp: Path, name: str) -> tuple[str, int]:
    path = tmp / name
    if not path.exists():
        return "0" * 64, 0
    blob = path.read_bytes()
    return hashlib.sha256(blob).hexdigest(), len(blob)


def make_receipt(tmp: Path, name: str, url: str, page: str, quote: str,
                 mode: str = "downloaded", sha: str | None = None,
                 bytes_: int | None = None) -> dict:
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
    return {"receipt": name + ".source.json", "page": page, "sha256": record["sha256"],
            "bytes": record["bytes"], "captured_at_utc": record["captured_at_utc"],
            "capture_mode": "downloaded", "quote": quote, "url": url}


def make_ledger(*records) -> dict:
    return {"total_questions": len(records),
            "entries": list(records)}


def make_block_entry(url: str, rec: dict, redirected_to: str | None = None) -> dict:
    entry = {
        "url": url,
        "receipt": rec["receipt"],
        "page": rec["page"],
        "content_sha256": rec["sha256"],
        "bytes": rec["bytes"],
        "captured_at_utc": rec["captured_at_utc"],
        "capture_mode": "downloaded",
    }
    if redirected_to is not None:
        entry["final_redirected_url"] = redirected_to
    return entry


def make_block(*entries: dict) -> dict:
    return {"evidence_tree": "synthetic evidence tree path",
            "verified_by": "synthetic verifier note",
            "urls": list(entries),
            "note": "synthetic note"}


def make_linkage(*records: dict) -> dict:
    return {"report": "synthetic linkage", "records": list(records)}


def make_linkage_record(qid: str, urls: list, links: list) -> dict:
    return {"question_key": qid, "ledger_source_urls": list(urls),
            "url_links": links, "record_state": "all_urls_captured_and_byte_verified"}


def make_url_link(url: str, rec: dict, redirected_to: str | None = None,
                  shared_with: list | None = None, state: str = "captured_downloaded_verified") -> dict:
    link = {
        "ledger_url": url,
        "state": state,
        "host": HOST,
        "receipt_path": "synthetic/evidence/" + rec["receipt"],
        "page_path": "synthetic/evidence/" + rec["page"],
        "content_sha256": rec["sha256"],
        "bytes": rec["bytes"],
        "captured_at_utc": rec["captured_at_utc"],
        "capture_mode": "downloaded",
        "quote": rec["quote"],
        "receipt_recorded_source_url": redirected_to or url,
        "redirected": redirected_to is not None and redirected_to != url,
        "shared_with_question_keys": shared_with or [],
    }
    if redirected_to is not None and redirected_to != url:
        link["final_redirected_url"] = redirected_to
    return link


def run(tmp: Path, ledger: dict, linkage: dict | None = None):
    return audit_ledger_source_urls.audit(
        ledger, tmp, linkage, [HOST])


class TestAuditLedgerSourceUrls(unittest.TestCase):
    def test_all_verified_with_shared_url_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            p2 = make_page(tmp, "synthetic-b", "Synthetic beta quota text")
            ra = make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text")
            rb = make_receipt(tmp, "synthetic-b", f"https://{HOST}/b", p2, "Synthetic beta quota text")
            ledger = make_ledger(
                {"question_key": "synthetic1", "source_urls": [f"https://{HOST}/a", f"https://{HOST}/b"]},
                {"question_key": "synthetic2", "source_urls": [f"https://{HOST}/b"]},
            )
            linkage = make_linkage(
                make_linkage_record("synthetic1", [f"https://{HOST}/a", f"https://{HOST}/b"], [
                    make_url_link(f"https://{HOST}/a", ra, shared_with=[]),
                    make_url_link(f"https://{HOST}/b", rb, shared_with=["synthetic2"]),
                ]),
                make_linkage_record("synthetic2", [f"https://{HOST}/b"], [
                    make_url_link(f"https://{HOST}/b", rb, shared_with=["synthetic1"]),
                ]),
            )
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "all_url_instances_byte_verified")
            self.assertEqual(report["counts"]["url_instances"], 3)
            self.assertEqual(report["counts"]["unique_ledger_urls"], 2)
            self.assertEqual(report["counts"]["records_with_source_urls"], 2)
            # one shared URL across two records is legitimate many-to-one reuse
            self.assertEqual(report["counts"]["shared_urls"], {f"https://{HOST}/b": ["synthetic1", "synthetic2"]})
            # no ledger evidence blocks anywhere: explicitly reduced assurance
            self.assertFalse(report["ledger_evidence_blocks"]["present"])
            self.assertEqual(report["assurance"], "reduced_source_urls_only_no_blocks")
            self.assertIn("REDUCED ASSURANCE", report["assurance_note"])

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
            report = run(tmp, ledger)  # no linkage: redirect is unexplained
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("no byte-verified receipt" in b["reason"] for b in report["blockers"]))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            rec = make_receipt(tmp, "synthetic-a", f"https://{HOST}/new", p1, "Synthetic alpha quota text")
            linkage = make_linkage(
                make_linkage_record("synthetic1", [f"https://{HOST}/old"], [
                    make_url_link(f"https://{HOST}/old", rec, redirected_to=f"https://{HOST}/new"),
                ]),
            )
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

    def test_records_without_urls_are_out_of_scope_but_zero_url_ledger_is_not_vacuous_success(self):
        # DEV-005 strengthening: records without URLs stay out of scope for
        # per-record checks, but a ledger with ZERO URL instances must never
        # report vacuous success.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger = make_ledger({"question_key": "synthetic1", "source_urls": []},
                                 {"question_key": "synthetic2"})
            report = run(tmp, ledger)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("vacuous success suppressed" in b["reason"] for b in report["blockers"]))
            self.assertEqual(report["counts"]["records_with_source_urls"], 0)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            rec = make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text")
            # mixed ledger: records without URLs remain out of scope and do not block
            ledger = make_ledger(
                {"question_key": "synthetic1", "source_urls": [f"https://{HOST}/a"]},
                {"question_key": "synthetic2", "source_urls": []},
                {"question_key": "synthetic3"},
            )
            linkage = make_linkage(
                make_linkage_record("synthetic1", [f"https://{HOST}/a"], [
                    make_url_link(f"https://{HOST}/a", rec),
                ]),
            )
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "all_url_instances_byte_verified")
            self.assertEqual(report["counts"]["records_with_source_urls"], 1)

    def test_invalid_ledger_shapes(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self.assertEqual(run(tmp, {"entries": "nope"})["status"], "invalid")
            self.assertEqual(run(tmp, {})["status"], "invalid")


class TestLedgerEvidenceBlocks(unittest.TestCase):
    """DEV-005: the per-record ledger evidence blocks themselves are validated."""

    def _strict_fixture(self, tmp: Path):
        p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
        p2 = make_page(tmp, "synthetic-b", "Synthetic beta quota text")
        p3 = make_page(tmp, "synthetic-c", "Synthetic gamma quota text")
        ra = make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text")
        rb = make_receipt(tmp, "synthetic-b", f"https://{HOST}/b", p2, "Synthetic beta quota text")
        rc = make_receipt(tmp, "synthetic-c", f"https://{HOST}/final", p3, "Synthetic gamma quota text")
        ledger = make_ledger(
            {"question_key": "synthetic1",
             "source_urls": [f"https://{HOST}/a", f"https://{HOST}/b", f"https://{HOST}/old"],
             FIELD: make_block(
                 make_block_entry(f"https://{HOST}/a", ra),
                 make_block_entry(f"https://{HOST}/b", rb),
                 make_block_entry(f"https://{HOST}/old", rc, redirected_to=f"https://{HOST}/final"),
             )},
            {"question_key": "synthetic2",
             "source_urls": [f"https://{HOST}/b"],
             FIELD: make_block(make_block_entry(f"https://{HOST}/b", rb))},
        )
        linkage = make_linkage(
            make_linkage_record("synthetic1",
                                [f"https://{HOST}/a", f"https://{HOST}/b", f"https://{HOST}/old"], [
                                    make_url_link(f"https://{HOST}/a", ra, shared_with=[]),
                                    make_url_link(f"https://{HOST}/b", rb, shared_with=["synthetic2"]),
                                    make_url_link(f"https://{HOST}/old", rc,
                                                  redirected_to=f"https://{HOST}/final"),
                                ]),
            make_linkage_record("synthetic2", [f"https://{HOST}/b"], [
                make_url_link(f"https://{HOST}/b", rb, shared_with=["synthetic1"]),
            ]),
        )
        return ledger, linkage, ra, rb, rc

    def test_strict_blocks_pass_with_full_assurance(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, *_ = self._strict_fixture(tmp)
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "all_url_instances_byte_verified")
            self.assertEqual(report["counts"]["url_instances"], 4)
            self.assertTrue(report["ledger_evidence_blocks"]["present"])
            self.assertEqual(report["ledger_evidence_blocks"]["records_with_blocks"], 2)
            self.assertEqual(report["assurance"], "full_strict_per_url_and_blocks")

    def test_missing_block_on_one_url_bearing_record_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, *_ = self._strict_fixture(tmp)
            del ledger["entries"][1][FIELD]  # second URL-bearing record loses its block
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("missing its" in b["reason"] and "evidence block" in b["reason"]
                                for b in report["blockers"]))

    def test_omission_of_one_multi_url_source_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, *_ = self._strict_fixture(tmp)
            ledger["entries"][0][FIELD]["urls"] = ledger["entries"][0][FIELD]["urls"][:2]  # 3 URLs, 2 entries
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("url count 2 != source_urls count 3" in b["reason"]
                                for b in report["blockers"]))
            self.assertTrue(any("no evidence block entry for this URL instance" in b["reason"]
                                for b in report["blockers"]))

    def test_block_order_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, *_ = self._strict_fixture(tmp)
            urls = ledger["entries"][0][FIELD]["urls"]
            urls[0], urls[1] = urls[1], urls[0]
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("order or content mismatch" in b["reason"] for b in report["blockers"]))

    def test_altered_block_sha_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, *_ = self._strict_fixture(tmp)
            ledger["entries"][0][FIELD]["urls"][0]["content_sha256"] = "a" * 64  # altered hash
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("block content_sha256 does not match" in b["reason"]
                                for b in report["blockers"]))

    def test_forged_block_bytes_and_timestamp_fail(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, *_ = self._strict_fixture(tmp)
            ledger["entries"][0][FIELD]["urls"][0]["bytes"] += 1          # forged byte length
            ledger["entries"][0][FIELD]["urls"][1]["captured_at_utc"] = "1999-01-01T00:00:00+00:00"
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("block byte length does not match" in b["reason"]
                                for b in report["blockers"]))
            self.assertTrue(any("block captured_at_utc does not match" in b["reason"]
                                for b in report["blockers"]))

    def test_forged_block_receipt_of_other_question_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, ra, rb, rc = self._strict_fixture(tmp)
            # entry for /a claims synthetic-b's receipt (cross-question receipt forgery)
            ledger["entries"][0][FIELD]["urls"][0]["receipt"] = rb["receipt"]
            ledger["entries"][0][FIELD]["urls"][0]["page"] = rb["page"]
            ledger["entries"][0][FIELD]["urls"][0]["content_sha256"] = rb["sha256"]
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("block receipt filename does not match" in b["reason"]
                                for b in report["blockers"]))

    def test_cross_question_redirect_substitution_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, ra, rb, rc = self._strict_fixture(tmp)
            # /a has a direct receipt; attacker removes it and forges a redirect
            # claim to synthetic2's /b receipt inside the ledger block only.
            (tmp / "synthetic-a.source.json").unlink()
            ledger["entries"][0][FIELD]["urls"][0] = make_block_entry(
                f"https://{HOST}/a", rb, redirected_to=f"https://{HOST}/b")
            # the per-question sidecar still maps /a to its own (now missing) receipt
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("no byte-verified receipt" in b["reason"]
                                for b in report["blockers"]))
            self.assertFalse(any(b["reason"].startswith("orphan") for b in report["blockers"])
                            or False)

    def test_cross_question_redirect_substitution_via_sidecar_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, ra, rb, rc = self._strict_fixture(tmp)
            # attacker retargets the sidecar mapping of /old from /final to
            # synthetic2's /b receipt while the block still claims /final
            for link in linkage["records"][0]["url_links"]:
                if link["ledger_url"] == f"https://{HOST}/old":
                    link["final_redirected_url"] = f"https://{HOST}/b"
                    link["receipt_recorded_source_url"] = f"https://{HOST}/b"
                    link["redirected"] = True
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            reasons = " | ".join(b["reason"] for b in report["blockers"])
            self.assertTrue("does not match the byte-verified receipt" in reasons
                            or "does not match the byte-verified redirect target" in reasons)

    def test_wrong_final_target_in_block_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, ra, rb, rc = self._strict_fixture(tmp)
            # block claims a wrong final target for the redirected instance
            ledger["entries"][0][FIELD]["urls"][2]["final_redirected_url"] = f"https://{HOST}/b"
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("block final_redirected_url does not match" in b["reason"]
                                for b in report["blockers"]))

    def test_block_redirect_without_sidecar_corroboration_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, ra, rb, rc = self._strict_fixture(tmp)
            report = run(tmp, ledger, None)  # strict mode, no linkage sidecar at all
            self.assertEqual(report["status"], "blocked")
            # the redirected /old instance has no corroborated receipt: the
            # block's own redirect claim alone must not count as proof
            self.assertTrue(any("no byte-verified receipt" in b["reason"]
                                for b in report["blockers"]))
            self.assertTrue(any("evidence block alone cannot document a redirect"
                                in b["reason"] for b in report["blockers"]))

    def test_non_redirected_instance_claiming_final_target_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, ra, rb, rc = self._strict_fixture(tmp)
            ledger["entries"][0][FIELD]["urls"][0]["final_redirected_url"] = f"https://{HOST}/b"
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("non-redirected instance must not claim" in b["reason"]
                                for b in report["blockers"]))

    def test_duplicate_instance_omitted_from_block_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            ra = make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text")
            # record lists the same URL twice (duplicate instance), block lists it once
            ledger = make_ledger(
                {"question_key": "synthetic1",
                 "source_urls": [f"https://{HOST}/a", f"https://{HOST}/a"],
                 FIELD: make_block(make_block_entry(f"https://{HOST}/a", ra))},
            )
            linkage = make_linkage(
                make_linkage_record("synthetic1", [f"https://{HOST}/a", f"https://{HOST}/a"], [
                    make_url_link(f"https://{HOST}/a", ra),
                    make_url_link(f"https://{HOST}/a", ra),
                ]),
            )
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("url count 1 != source_urls count 2" in b["reason"]
                                for b in report["blockers"]))

    def test_duplicate_instance_present_in_block_passes(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            ra = make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text")
            ledger = make_ledger(
                {"question_key": "synthetic1",
                 "source_urls": [f"https://{HOST}/a", f"https://{HOST}/a"],
                 FIELD: make_block(make_block_entry(f"https://{HOST}/a", ra),
                                   make_block_entry(f"https://{HOST}/a", ra))},
            )
            linkage = make_linkage(
                make_linkage_record("synthetic1", [f"https://{HOST}/a", f"https://{HOST}/a"], [
                    make_url_link(f"https://{HOST}/a", ra),
                    make_url_link(f"https://{HOST}/a", ra),
                ]),
            )
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "all_url_instances_byte_verified")
            self.assertEqual(report["counts"]["url_instances"], 2)
            self.assertTrue(any("duplicate listing" in i.get("note", "") for i in report["url_instances"]))

    def test_block_on_record_without_source_urls_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            ra = make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text")
            ledger = make_ledger(
                {"question_key": "synthetic1", "source_urls": [f"https://{HOST}/a"],
                 FIELD: make_block(make_block_entry(f"https://{HOST}/a", ra))},
                {"question_key": "synthetic2",  # no source_urls, but carries a block
                 FIELD: make_block(make_block_entry(f"https://{HOST}/a", ra))},
            )
            linkage = make_linkage(
                make_linkage_record("synthetic1", [f"https://{HOST}/a"], [
                    make_url_link(f"https://{HOST}/a", ra),
                ]),
            )
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("block present on a record without source_urls" in b["reason"]
                                for b in report["blockers"]))

    def test_unknown_linkage_record_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, ra, rb, rc = self._strict_fixture(tmp)
            linkage["records"].append(make_linkage_record("ghost", [f"https://{HOST}/a"], [
                make_url_link(f"https://{HOST}/a", ra)]))
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("unknown linkage record" in b["reason"] for b in report["blockers"]))

    def test_orphan_linkage_url_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, ra, rb, rc = self._strict_fixture(tmp)
            # synthetic2's mapping references a URL it does not list
            linkage["records"][1]["url_links"].append(
                make_url_link(f"https://{HOST}/a", ra))
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("orphan linkage mapping" in b["reason"] for b in report["blockers"]))

    def test_url_bearing_record_missing_from_linkage_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, *_ = self._strict_fixture(tmp)
            del linkage["records"][1]
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("missing from the linkage sidecar" in b["reason"]
                                for b in report["blockers"]))

    def test_shared_with_inconsistency_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, ra, rb, rc = self._strict_fixture(tmp)
            # synthetic2's link stops declaring the real sharing with synthetic1
            linkage["records"][1]["url_links"][0]["shared_with_question_keys"] = []
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("shared_with_question_keys does not match the actual ledger sharing"
                                in b["reason"] for b in report["blockers"]))

    def test_shared_with_foreign_question_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, ra, rb, rc = self._strict_fixture(tmp)
            linkage["records"][0]["url_links"][0]["shared_with_question_keys"] = ["synthetic2"]
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("does not reference this URL in the ledger" in b["reason"]
                                for b in report["blockers"]))

    def test_sidecar_field_drift_against_receipt_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger, linkage, ra, rb, rc = self._strict_fixture(tmp)
            linkage["records"][0]["url_links"][0]["content_sha256"] = "b" * 64
            linkage["records"][0]["url_links"][0]["capture_mode"] = "cached"
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "blocked")
            self.assertTrue(any("linkage content_sha256 does not match" in b["reason"]
                                for b in report["blockers"]))
            self.assertTrue(any("linkage capture_mode is not downloaded" in b["reason"]
                                for b in report["blockers"]))

    def test_reduced_mode_is_explicitly_reduced(self):
        # backward-compatible read-only mode: no blocks anywhere; the report
        # must say so and must not be mislabeled complete ledger evidence.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            p1 = make_page(tmp, "synthetic-a", "Synthetic alpha quota text")
            rec = make_receipt(tmp, "synthetic-a", f"https://{HOST}/a", p1, "Synthetic alpha quota text")
            ledger = make_ledger({"question_key": "synthetic1", "source_urls": [f"https://{HOST}/a"]})
            linkage = make_linkage(
                make_linkage_record("synthetic1", [f"https://{HOST}/a"], [
                    make_url_link(f"https://{HOST}/a", rec)]))
            report = run(tmp, ledger, linkage)
            self.assertEqual(report["status"], "all_url_instances_byte_verified")
            self.assertFalse(report["ledger_evidence_blocks"]["present"])
            self.assertEqual(report["assurance"], "reduced_source_urls_only_no_blocks")
            self.assertIn("NOT complete ledger evidence", report["assurance_note"])
            self.assertEqual(report["counts"]["evidence_blocks_mode"], "absent_read_only")


if __name__ == "__main__":
    unittest.main()
