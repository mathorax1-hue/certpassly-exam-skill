#!/usr/bin/env python3
"""Fail-closed, read-only preflight for a private exam review ledger.

This tool never changes owner keys or awards release approval. A successful
preflight is necessary evidence hygiene, not a substitute for pipeline,
independent release, visual or human-review gates. Standard library only.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys

SHA256 = re.compile(r"^[0-9a-f]{64}$")
QID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def audit(doc):
    if not isinstance(doc, dict):
        raise ValueError("ledger root must be an object")
    entries = doc.get("entries")
    count = doc.get("total_questions")
    if not isinstance(entries, list) or isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("total_questions must be positive and entries must be a list")
    errors = []
    blockers = []
    if len(entries) != count:
        errors.append(f"record_count_mismatch:{len(entries)}!={count}")
    seen = set()
    reviewed = 0
    signed = 0
    key_verified = 0
    approved = 0
    missing_source_hash = 0
    for i, item in enumerate(entries, 1):
        if not isinstance(item, dict):
            errors.append(f"entry_{i}_not_object")
            continue
        qid = item.get("question_key")
        if not isinstance(qid, str) or not QID.fullmatch(qid):
            errors.append(f"entry_{i}_invalid_key")
            continue
        if qid in seen:
            errors.append(f"duplicate_key:{qid}")
        seen.add(qid)
        if item.get("signed_human_review") is True:
            signed += 1
        proofs = [v for k, v in item.items()
                  if k.startswith("ai_artifact_full_bank_structure_review_") and isinstance(v, dict)]
        if any(proof.get("source_key_verified_for_release") is True for proof in proofs):
            key_verified += 1
        if item.get("release_approved") is True:
            approved += 1
        if item.get("full_choice_verification") in ("complete", "verified", "passed"):
            reviewed += 1
        # URLs are references, not a saved and hashed source snapshot.
        urls = item.get("source_urls") or []
        if urls and not any(SHA256.fullmatch(str(item.get(k) or "")) for k in
                            ("source_snapshot_sha256", "official_source_sha256", "source_html_sha256")):
            missing_source_hash += 1
        if item.get("release_approved") is True and item.get("signed_human_review") is not True:
            errors.append(f"approval_without_signed_review:{qid}")
    if approved != count:
        blockers.append(f"questions_not_release_approved:{count - approved}")
    if signed != count:
        blockers.append(f"questions_without_signed_review:{count - signed}")
    if key_verified != count:
        blockers.append(f"questions_without_explicit_release_key_proof:{count - key_verified}")
    if missing_source_hash:
        blockers.append(f"question_records_with_urls_but_no_local_source_hash:{missing_source_hash}")
    if doc.get("full_answer_accuracy_verified") != count:
        blockers.append("full_accuracy_count_not_complete")
    if doc.get("potential_source_key_conflicts"):
        blockers.append("unresolved_source_key_conflicts")
    if "BLOCKED" in str(doc.get("status", "")).upper():
        blockers.append("ledger_status_blocked")
    checkpoints = [v for k, v in doc.items()
                   if k.startswith("ai_source_supported_") and isinstance(v, dict)]
    reported_supported = [v.get("cumulative_ai_supported") for v in checkpoints
                          if isinstance(v.get("cumulative_ai_supported"), int)]
    ai_supported = max(reported_supported) if reported_supported else None
    if ai_supported is not None and not (0 <= ai_supported <= count):
        errors.append("unsupported_ai_support_count")
    if any(v.get("source_html_sha256_captured") is False for v in checkpoints):
        blockers.append("official_source_snapshots_unhashed")
    if any(v.get("original_pdf_reinspected") is False for v in checkpoints):
        blockers.append("original_pdf_reinspection_pending")
    if any(v.get("full_release_approved", None) == 0 for v in checkpoints):
        blockers.append("checkpoint_reports_zero_release_approvals")
    return {
        "exam": doc.get("exam"), "total_questions": count,
        "records": len(entries), "ai_supported_checks_reported": ai_supported,
        "fully_release_approved_records": approved,
        "signed_review_records": signed,
        "release_key_proof_records": key_verified,
        "fully_choice_reviewed_records": reviewed,
        "status": "invalid" if errors else "blocked" if blockers else "preflight_only",
        "errors": errors, "blockers": blockers,
        "note": "A clean preflight never grants permission to publish or promotes an exam. Execute the independent release gates.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path, help="Private active-question-review-ledger.json")
    parser.add_argument("--output", type=Path, help="Optional machine-readable JSON report")
    args = parser.parse_args(argv)
    try:
        report = audit(json.loads(args.ledger.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        report = {"status": "invalid", "errors": [str(exc)], "blockers": []}
    output = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    print(output, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    return 0 if report["status"] == "preflight_only" else (1 if report["status"] == "invalid" else 2)


if __name__ == "__main__":
    sys.exit(main())
