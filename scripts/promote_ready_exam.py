#!/usr/bin/env python3
"""Copy a fully gated exam draft into a private ready-exams checkout.

Promotion is never automatic. Every gate must pass, and the caller must pass
--promote. The destination receives the site v2 file plus a provenance note
that names the raw-exam commit. This script does not grant human review or
website publication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

BLOCKING_CONTENT = {"blocked_needs_content", "blocked_violations"}


def _load(path: Path | None) -> dict:
    if not path or not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


TEST_FIXTURE_CODES = {"QTYPE-FIXTURE"}
STAGING_TYPES = {"active_screen", "multimedia_stimulus", "testlet"}  # registry staging list; the four former staging types are publishable now
STAGING_TAG = "staging_draft_only"


def staging_items(site_file: Path | None) -> list[dict]:
    """Questions whose site type is not publishable. They must stay draft only."""
    if not site_file or not site_file.is_file():
        return []
    try:
        doc = json.loads(site_file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    rows = []
    for q in doc.get("questions") or []:
        typ = q.get("type")
        tags = q.get("tags") or []
        if typ in STAGING_TYPES or STAGING_TAG in tags:
            rows.append({"question_key": q.get("question_key"), "type": typ, "publication": "draft_only"})
    return rows


def is_test_fixture(exam: str, site_file: Path | None) -> bool:
    """Synthetic test fixtures (tests/fixtures) are never promoted."""
    code = (exam or "").upper()
    if code in TEST_FIXTURE_CODES or code.startswith("TEST-FIXTURE"):
        return True
    try:
        if site_file and site_file.is_file():
            exam_obj = json.loads(site_file.read_text(encoding="utf-8")).get("exam") or {}
            code = str(exam_obj.get("exam_code") or "").upper()
            return code in TEST_FIXTURE_CODES or code.startswith("TEST-FIXTURE") or bool(exam_obj.get("test_only"))
    except (ValueError, OSError, AttributeError):
        return False
    return False


def evaluate(args: argparse.Namespace) -> dict:
    reasons: list[str] = []
    worklist = _load(args.worklist)
    content = _load(args.content_gate)
    importer = _load(args.import_gate)
    domains = _load(args.domain_gate)
    if worklist.get("held"):
        reasons.append(f"held items remain: {len(worklist['held'])}")
    if worklist.get("answer_not_found"):
        reasons.append(f"answer_not_found items remain: {len(worklist['answer_not_found'])}")
    if worklist.get("missing_exam_facts"):
        reasons.append("official exam facts are missing saved URL, sha256 and quote")
    if domains.get("promotion_blocker") or domains.get("unmapped_count") or (
        not domains or domains.get("status") in {"domain_unmapped", "no_official_domain_list"}
    ):
        if not domains:
            reasons.append("domain mapping report is missing")
        else:
            reasons.append(
                "domain mapping: %s (%s unmapped)"
                % (domains.get("status") or "missing", domains.get("unmapped_count") or 0)
            )
    if content.get("status") in BLOCKING_CONTENT or not content:
        reasons.append(f"content gate: {content.get('status') or 'missing'}")
    if not importer or importer.get("status") != "passed":
        reasons.append(f"site import gate: {(importer or {}).get('status') or 'missing'}")
    elif not (importer.get("site_file_sha256") or "").strip():
        reasons.append("site import gate report is missing the site file sha256")
    elif not args.site_file.is_file():
        reasons.append("site v2 file is missing")
    else:
        site_sha = hashlib.sha256(args.site_file.read_bytes()).hexdigest()
        report_sha = str(importer.get("site_file_sha256") or "").strip().lower()
        if report_sha != site_sha:
            reasons.append("site import gate sha256 does not match the site v2 file")
    if importer and importer.get("rejected"):
        reasons.append(f"importer rejected {len(importer['rejected'])} questions")
    if not args.site_file.is_file() and "site v2 file is missing" not in reasons:
        reasons.append("site v2 file is missing")
    if not args.raw_commit or len(args.raw_commit) != 40:
        reasons.append("raw-exam commit sha is missing or not a full SHA")
    if is_test_fixture(args.exam, args.site_file):
        reasons.append("test-only fixture exam (never promote)")
    if not args.promote:
        reasons.append("promote flag was not set (auto promotion is forbidden)")
    staging = staging_items(args.site_file)
    status = "promoted" if not reasons and args.promote else "not_promoted"
    return {
        "schema_version": 1,
        "status": status,
        "exam_code": args.exam,
        "blockers": reasons,
        "raw_exam_commit": args.raw_commit,
        "published": False,
        "ready_for_publication": False,
        "staging_draft_only": staging,
        "human_review_status": "pending",
        "editorial_process": "AI-assisted draft; independent human subject review pending",
    }


def promote(args: argparse.Namespace, decision: dict) -> dict:
    dest_dir = args.ready_root / "exams" / args.exam
    if dest_dir.exists() and not args.force:
        decision["blockers"].append("destination exam folder already exists (pass --force to replace a draft)")
        decision["status"] = "not_promoted"
        return decision
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / args.site_file.name
    shutil.copy2(args.site_file, dest_file)
    sha = hashlib.sha256(dest_file.read_bytes()).hexdigest()
    provenance = {
        "exam_code": args.exam,
        "raw_exam_commit": args.raw_commit,
        "raw_exam_repository": "mathorax1-hue/raw-exam",
        "site_file": dest_file.name,
        "site_file_sha256": sha,
        "site_file_bytes": dest_file.stat().st_size,
        "promoted_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "published": False,
        "ready_for_publication": False,
        "human_review_status": "pending",
        "note": "Validated technical and import draft only. Not a website publication and not an independent human review.",
        "staging_draft_only": decision.get("staging_draft_only") or [],
        "publication_note": "Staging types stay draft only until the site publishable flag is on.",
    }
    (dest_dir / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    (dest_dir / "PROVENANCE.md").write_text(
        f"# Provenance for {args.exam}\n\n"
        f"This ready-exams draft came from private raw-exam commit `{args.raw_commit}`.\n\n"
        f"Site file: `{dest_file.name}`\n\n"
        f"SHA-256: `{sha}`\n\n"
        "Status: validated draft. published=false. ready_for_publication=false. "
        "Human review is still pending. This is not a live site import.\n"
        "Staging types stay draft only until the site publishable flag is on.\n",
        encoding="utf-8",
    )
    decision["destination"] = str(dest_dir)
    decision["site_file_sha256"] = sha
    return decision


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exam", required=True)
    ap.add_argument("--site-file", required=True, type=Path)
    ap.add_argument("--ready-root", required=True, type=Path)
    ap.add_argument("--raw-commit", required=True)
    ap.add_argument("--worklist", type=Path)
    ap.add_argument("--content-gate", type=Path)
    ap.add_argument("--import-gate", type=Path)
    ap.add_argument("--domain-gate", type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--promote", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    decision = evaluate(args)
    if decision["status"] == "promoted":
        decision = promote(args, decision)
        if decision["status"] != "promoted":
            pass
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": decision["status"],
        "exam_code": decision["exam_code"],
        "blocker_count": len(decision["blockers"]),
        "blockers": decision["blockers"],
        "raw_exam_commit": decision["raw_exam_commit"],
    }))
    return 0 if decision["status"] == "promoted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
