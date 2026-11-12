#!/usr/bin/env python3
"""Fail-closed strict per-URL validator for ledger source URLs vs saved evidence.

For EVERY ``source_urls`` entry of EVERY ledger record this tool requires a
byte-verified saved snapshot: a matching receipt, the receipt's recorded source
URL equal to the ledger URL or to an explicitly documented redirect target, a
saved page whose SHA-256 and byte length match the receipt, ``capture_mode``
``downloaded``, and a proof quote present in the saved page's visible text.

It deliberately does NOT accept a single per-question hash field as proof for a
question that references several URLs: each URL instance is checked on its own.
Many-to-one reuse (one URL shared by several records) is valid only when every
instance resolves to the same receipt. Evidence files no ledger URL refers to
are reported as orphans. This is structural byte/linkage validation, not
semantic answer verification, human review, or release approval. Public tests
use wholly synthetic fixtures; real evidence stays private. Standard library
only.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_official_source import normalized_text, validate_url  # noqa: E402

SHA = re.compile(r"^[a-f0-9]{64}$")
ALLOWED_VERDICTS_URL_STATE = {"captured_downloaded_verified"}


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path.name}: {exc}") from exc


def iter_receipts(evidence_dir: Path):
    for receipt_path in sorted(evidence_dir.glob("*.source.json")):
        if receipt_path.is_symlink():
            yield receipt_path, None
            continue
        try:
            record = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            yield receipt_path, None
            continue
        yield receipt_path, record


def audit(ledger: dict, evidence_dir: Path, linkage: dict | None, allow_hosts: list[str]) -> dict:
    blockers: list[dict] = []

    def block(item: str, reason: str):
        blockers.append({"item": item, "reason": reason})

    if not isinstance(ledger, dict):
        return {"status": "invalid", "blockers": [{"item": "ledger", "reason": "not an object"}],
                "counts": {}, "url_instances": [], "note": "invalid ledger"}
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        return {"status": "invalid", "blockers": [{"item": "ledger", "reason": "entries must be a list"}],
                "counts": {}, "url_instances": [], "note": "invalid ledger"}

    # Receipt index keyed by the URL recorded inside the receipt.
    receipts_by_url: dict[str, dict] = {}
    for receipt_path, record in iter_receipts(evidence_dir):
        name = receipt_path.name
        if record is None:
            block(name, "receipt unreadable or a symlink")
            continue
        url = record.get("source_url")
        if not isinstance(url, str) or not url:
            block(name, "receipt missing source_url")
            continue
        if url in receipts_by_url:
            block(name, f"duplicate receipt for one URL: {url}")
            continue
        page_name = record.get("saved_content_path")
        if (not isinstance(page_name, str) or not page_name or "/" in page_name
                or "\\" in page_name or page_name.startswith(".")):
            block(name, "invalid saved_content_path")
            continue
        page = evidence_dir / page_name
        if not page.is_file() or page.is_symlink():
            block(name, "saved page missing or unsafe")
            continue
        blob = page.read_bytes()
        digest = record.get("sha256")
        if not isinstance(digest, str) or not SHA.fullmatch(digest):
            block(name, "receipt SHA-256 missing or malformed")
            continue
        if hashlib.sha256(blob).hexdigest() != digest:
            block(name, "saved page SHA-256 mismatch")
            continue
        if len(blob) != record.get("bytes"):
            block(name, "saved page byte length mismatch")
            continue
        if record.get("capture_mode") != "downloaded":
            block(name, "capture_mode is not downloaded")
            continue
        quote = record.get("quote")
        content_type = record.get("content_type")
        if (not isinstance(quote, str) or not quote.strip() or len(quote) > 250
                or content_type not in ("text/html", "text/plain")
                or " ".join(quote.split()) not in normalized_text(blob, content_type)):
            block(name, "proof quote absent from saved page")
            continue
        try:
            validate_url(url, allow_hosts)
        except ValueError:
            block(name, "receipt source_url not on the allowlist")
            continue
        receipts_by_url[url] = {
            "receipt": name,
            "page": page_name,
            "sha256": digest,
            "bytes": len(blob),
            "captured_at_utc": record.get("captured_at_utc"),
            "quote": quote,
        }

    # Optional linkage: ledger URL -> documented final redirected URL.
    redirects: dict[str, str] = {}
    if linkage is not None:
        if not isinstance(linkage, dict):
            block("linkage", "linkage must be an object")
            linkage = None
        else:
            for record in linkage.get("records", []) if isinstance(linkage.get("records"), list) else []:
                if not isinstance(record, dict):
                    continue
                for link in record.get("url_links", []) if isinstance(record.get("url_links"), list) else []:
                    if not isinstance(link, dict):
                        continue
                    ledger_url = link.get("ledger_url")
                    final_url = link.get("final_redirected_url")
                    if isinstance(ledger_url, str) and isinstance(final_url, str) and final_url != ledger_url:
                        redirects[ledger_url] = final_url

    instances = []
    seen_pairs = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_key") or "?")
        urls = item.get("source_urls") or []
        if not isinstance(urls, list):
            block(qid, "source_urls must be a list")
            urls = []
        if not urls:
            continue  # records without URLs are out of scope here
        for url in urls:
            if not isinstance(url, str) or not url:
                block(qid, "empty source_urls entry")
                continue
            key = (qid, url)
            if key in seen_pairs:
                instance_note = "duplicate listing of the same URL in one record"
            else:
                instance_note = ""
            seen_pairs.add(key)
            resolved = url if url in receipts_by_url else redirects.get(url, url)
            receipt = receipts_by_url.get(resolved)
            if receipt is None:
                if url in receipts_by_url:
                    # unreachable branch, kept for clarity
                    receipt = receipts_by_url[url]
                else:
                    instances.append({"question_key": qid, "ledger_url": url,
                                      "state": "missing_saved_evidence"})
                    block(f"{qid}: {url}", "no byte-verified receipt for this exact URL instance")
                    continue
            entry = {
                "question_key": qid,
                "ledger_url": url,
                "resolved_url": resolved,
                "redirected": resolved != url,
                "state": "captured_downloaded_verified",
                "receipt": receipt["receipt"],
                "page": receipt["page"],
                "sha256": receipt["sha256"],
                "bytes": receipt["bytes"],
            }
            if instance_note:
                entry["note"] = instance_note
            instances.append(entry)

    # Orphan receipts: evidence no ledger URL refers to.
    referenced = {(i.get("resolved_url") or i.get("ledger_url")) for i in instances} | {i["ledger_url"] for i in instances}
    for url in receipts_by_url:
        if url not in referenced:
            block(receipts_by_url[url]["receipt"], "evidence not referenced by any ledger URL")

    shared: dict[str, list[str]] = {}
    for i in instances:
        if i.get("state") in ALLOWED_VERDICTS_URL_STATE:
            shared.setdefault(i["ledger_url"], []).append(i["question_key"])
    shared = {u: sorted(set(qs)) for u, qs in shared.items() if len(set(qs)) > 1}

    counts = {
        "records_with_source_urls": sum(1 for i in entries if isinstance(i, dict) and (i.get("source_urls") or [])),
        "url_instances": len(instances),
        "unique_ledger_urls": len({i["ledger_url"] for i in instances}),
        "verified_instances": sum(1 for i in instances if i["state"] in ALLOWED_VERDICTS_URL_STATE),
        "redirected_instances": sum(1 for i in instances if i.get("redirected")),
        "shared_urls": shared,
    }
    if any(not isinstance(e.get("captured_at_utc"), str) for e in receipts_by_url.values()):
        block("evidence", "receipt missing capture timestamp")
    return {
        "status": "blocked" if blockers else "all_url_instances_byte_verified",
        "counts": counts,
        "url_instances": instances,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "human_review_approved": False,
        "release_approved": False,
        "note": "Strict per-URL byte/linkage validation only. No semantic answer, "
                "option-correctness, human-review or release judgment.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--linkage", type=Path, help="Optional machine-readable URL linkage map")
    parser.add_argument("--allow-host", action="append", required=True)
    parser.add_argument("--private-report", type=Path)
    args = parser.parse_args(argv)
    try:
        ledger = load_json(args.ledger)
        linkage = load_json(args.linkage) if args.linkage else None
        if linkage is not None and not isinstance(linkage, dict):
            raise ValueError("linkage must be an object")
    except ValueError as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    report = audit(ledger, args.evidence_dir, linkage, args.allow_host)
    output = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.private_report:
        args.private_report.parent.mkdir(parents=True, exist_ok=True)
        args.private_report.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if report["status"] == "all_url_instances_byte_verified" else 2


if __name__ == "__main__":
    sys.exit(main())
