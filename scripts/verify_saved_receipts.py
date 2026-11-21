#!/usr/bin/env python3
"""Verify saved official-page receipts against exact local bytes, without network.

This script verifies *archive integrity and quote occurrence*, not whether
Microsoft actually authored the bytes, whether the quote supports an option,
or whether human review happened. Run on private snapshots only.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

from capture_official_source import validate_url, normalized_text, MAX_BYTES

SHA = re.compile(r"^[a-f0-9]{64}$")


def verify_receipts(folder: Path, allowed_hosts: list[str]) -> dict:
    errors = []
    entries = []
    receipts = sorted(folder.glob("*.source.json"))
    if not receipts:
        errors.append({"file": str(folder), "reason": "no source receipts found"})
    for receipt_path in receipts:
        try:
            if receipt_path.is_symlink():
                raise ValueError("symlink receipt forbidden")
            record = json.loads(receipt_path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ValueError("receipt must be an object")
            url = validate_url(record["source_url"], allowed_hosts)
            name = record.get("saved_content_path")
            if (not isinstance(name, str) or not name or name in (".", "..") or
                    "/" in name or "\\" in name or name.startswith(".")):
                raise ValueError("invalid saved content filename")
            saved = folder / name
            if not saved.is_file() or saved.is_symlink():
                raise ValueError("missing or unsafe saved source")
            blob = saved.read_bytes()
            if not blob or len(blob) > MAX_BYTES:
                raise ValueError("saved source missing or oversized")
            digest = record.get("sha256")
            if not isinstance(digest, str) or not SHA.fullmatch(digest):
                raise ValueError("invalid receipt SHA-256")
            if hashlib.sha256(blob).hexdigest() != digest:
                raise ValueError("saved source SHA-256 mismatch")
            if len(blob) != record.get("bytes"):
                raise ValueError("saved source length mismatch")
            content_type = record.get("content_type")
            if content_type not in ("text/html", "text/plain"):
                raise ValueError("unsupported source content type")
            quote = record.get("quote")
            if (not isinstance(quote, str) or not quote.strip() or len(quote) > 250 or
                    " ".join(quote.split()) not in normalized_text(blob, content_type)):
                raise ValueError("proof quote absent from saved source")
            when = record.get("captured_at_utc")
            if not isinstance(when, str):
                raise ValueError("source capture timestamp missing")
            parsed = datetime.fromisoformat(when)
            if parsed.utcoffset() is None:
                raise ValueError("source capture timezone missing")
            if record.get("capture_mode") != "downloaded":
                raise ValueError("offline/unverified source origin cannot satisfy full download provenance")
            entries.append({"receipt": receipt_path.name, "source_file": saved.name,
                            "source_url": url, "sha256": digest, "status": "bytes_and_quote_match"})
        except (KeyError, ValueError, OSError, TypeError, json.JSONDecodeError) as exc:
            errors.append({"file": receipt_path.name, "reason": str(exc)})
    return {
        "status": "blocked" if errors else "stored_source_integrity_consistent_pending_semantic_review",
        "receipt_count": len(receipts),
        "integrity_checked": len(entries),
        "entries": entries,
        "errors": errors,
        "error_count": len(errors),
        "answer_correctness_verified": False,
        "human_review_approved": False,
        "release_approved": False,
        "note": "Offline integrity of receipts only; it does not authenticate remote vendor authorship or option truth.",
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--private-dir", required=True, type=Path)
    p.add_argument("--allow-host", action="append", required=True)
    p.add_argument("--private-report", type=Path)
    a = p.parse_args(argv)
    report = verify_receipts(a.private_dir, a.allow_host)
    if a.private_report:
        a.private_report.parent.mkdir(parents=True, exist_ok=True)
        a.private_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
