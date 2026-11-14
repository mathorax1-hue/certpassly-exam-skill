#!/usr/bin/env python3
"""Technical-only, fail-closed source comparison for CertPassly pilot drafts.

Input files are PRIVATE. Output is PRIVATE. Never upload generated reports to a
public skill repository. No answer checking, rewriting, research or publishing.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

FIELDS = ("stem", "options", "answer_raw")
ANSWER_FIELDS = {"answer_raw"}
KEY_RE = re.compile(r"^q[0-9]{3}$")
VERSION_RE = re.compile(r"^q[0-9]{3}\.v[0-9]+\.json$")
SENSITIVE = re.compile(r"answer[_ -]?(key|area|review)|reviewer|correct[_ -]?answer", re.I)

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def normalized(value):
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, list):
        return [normalized(v) for v in value]
    if isinstance(value, dict):
        return {str(k): normalized(v) for k, v in sorted(value.items())}
    return value

def fingerprint(value):
    payload = json.dumps(normalized(value), ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()

def compare_split(archive, fresh):
    if not isinstance(archive, dict) or not isinstance(fresh, dict):
        raise ValueError("split inputs must be key-to-object mappings")
    changes = []
    for key in sorted(set(archive) | set(fresh)):
        if not KEY_RE.fullmatch(key):
            raise ValueError("invalid question key: " + str(key))
        if key not in archive or key not in fresh:
            changes.append({"question_key": key, "field": "_question",
                            "status": "missing_in_" + ("archive" if key not in archive else "fresh"),
                            "technical_blocked": True})
            continue
        for field in FIELDS:
            before = archive[key].get(field)
            after = fresh[key].get(field)
            if normalized(before) != normalized(after):
                changes.append({
                    "question_key": key, "field": field,
                    "status": "requires_original_pdf_adjudication",
                    "archive_sha256": fingerprint(before), "fresh_sha256": fingerprint(after),
                    "answer_review_deferred": field in ANSWER_FIELDS,
                    "technical_blocked": field not in ANSWER_FIELDS,
                })
    return changes

def audit_v2(directory):
    errors = []
    inventory = []
    for file in sorted(Path(directory).glob("*.json")):
        if not VERSION_RE.fullmatch(file.name):
            continue
        doc = load_json(file)
        learner = doc.get("learner")
        qid = file.name[:4]
        bad = []
        if doc.get("question_key") != qid:
            bad.append("question_key/filename mismatch")
        if not isinstance(learner, dict) or not learner:
            bad.append("missing learner payload")
        else:
            if not learner.get("stem") and not learner.get("prompt") and not learner.get("content"):
                bad.append("learner prompt or content absent")
            for media in learner.get("media") or []:
                if not isinstance(media, dict):
                    bad.append("invalid media entry")
                    continue
                for name in ("href", "original_asset"):
                    val = media.get(name)
                    if SENSITIVE.search(json.dumps(val, ensure_ascii=False)):
                        bad.append("answer/reviewer media reference")
        if bad:
            errors.append({"question_key": qid, "problems": sorted(set(bad))})
        inventory.append(qid)
    return {"total": len(inventory), "unique": len(set(inventory)),
            "types_not_schema_validated": True, "structural_errors": errors}

def build_report(old, new, v2_dir, blocked_keys, expected=89):
    diffs = compare_split(old, new)
    inventory = audit_v2(v2_dir)
    blocked = sorted(set(blocked_keys))
    overlap = sorted(set(d["question_key"] for d in diffs) & set(blocked))
    missing = sorted(set(old) ^ set(new))
    structural = sorted(set(d["question_key"] for d in diffs if d["technical_blocked"]))
    review = sorted(set(blocked) | set(structural) |
                    set(e["question_key"] for e in inventory["structural_errors"]))
    return {
        "schema": "certpassly.source-fidelity-diff.v1",
        "technical_only": True, "answers_researched": False,
        "source_fidelity_independently_verified": False,
        "website_import_tested": False, "publication_approved": False,
        "archive_count": len(old), "fresh_count": len(new),
        "diff_question_count": len({d["question_key"] for d in diffs}),
        "diff_field_count": len(diffs), "diffs": diffs,
        "missing_question_keys": missing,
        "previously_flagged_source_questions": blocked,
        "flagged_and_changed": overlap,
        "v2_inventory": inventory,
        "technical_review_required": review,
        "technical_eligible_all": (len(old) == expected and len(new) == expected and
            inventory["total"] == expected and inventory["unique"] == expected and
            not review and not missing and not diffs),
        "status": "BLOCKED_SOURCE_VERIFICATION" if review or missing or diffs or
            inventory["total"] != expected else "AUTOMATED_CHECKS_ONLY_NOT_SOURCE_APPROVAL",
        "caution": "Hashes localize discrepancies; source PDF page review is mandatory. "
                   "This tool is not schema validation or a website importer test."
    }

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-split", required=True, type=Path)
    p.add_argument("--fresh-split", required=True, type=Path)
    p.add_argument("--v2-dir", required=True, type=Path)
    p.add_argument("--cannot-convert", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--expected", type=int, default=89)
    args = p.parse_args()
    cannot = load_json(args.cannot_convert)
    keys = cannot.get("question_keys") or [x["question_key"] for x in cannot.get("items", [])]
    report = build_report(load_json(args.archive_split),
                          load_json(args.fresh_split), args.v2_dir, keys, args.expected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("archive_count", "fresh_count",
        "diff_question_count", "diff_field_count", "status")}, sort_keys=True))
    return 0 if report["technical_eligible_all"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
