#!/usr/bin/env python3
"""Fail-closed structural auditor for option-by-option question review dossiers.

This is a review checklist, not semantic truth verification, a key correction,
pixel matching, an independent human sign-off, or a release approval.
Public fixtures must be wholly synthetic; real dossiers stay private.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

SHA = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_VERDICTS = {"supported", "contradicted", "uncertain"}
ALLOWED_IMAGE_ROLES = {"question_prompt", "answer_reference"}


def valid_official_url(url, hosts):
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower().rstrip(".")
        return (p.scheme == "https" and bool(host) and not p.username and not p.password
                and p.port in (None, 443) and any(
                    host == h or host.endswith("." + h)
                    for h in hosts if isinstance(h, str) and "." in h))
    except (ValueError, TypeError, AttributeError):
        return False


def audit_dossier(doc):
    blockers = []
    def block(item, reason):
        blockers.append({"item": str(item), "reason": reason})

    if not isinstance(doc, dict):
        return {"status": "blocked", "blockers": [{"item": "document", "reason": "not an object"}]}
    hosts = doc.get("official_hosts", [])
    if not isinstance(hosts, list) or not hosts or any(not isinstance(h, str) for h in hosts):
        block("document", "official_hosts must list vendor-controlled domains")
        hosts = []
    else:
        hosts = [h.lower().rstrip(".") for h in hosts]
    questions = doc.get("questions")
    if not isinstance(questions, list) or not questions:
        block("document", "questions must be a nonempty list")
        questions = []
    seen = set()
    for question in questions:
        if not isinstance(question, dict):
            block("question", "not an object")
            continue
        qid = question.get("id")
        if not isinstance(qid, str) or not qid:
            block("question", "missing question ID")
            continue
        if qid in seen:
            block(qid, "duplicate question ID")
        seen.add(qid)
        opts = question.get("options")
        if not isinstance(opts, list) or not opts:
            block(qid, "options are missing")
            continue
        ids = [o.get("id") if isinstance(o, dict) else None for o in opts]
        if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
            block(qid, "option IDs missing or duplicate")
            continue
        if any(not isinstance(o.get("text"), str) or not o["text"].strip()
               for o in opts):
            block(qid, "option text missing or obscured")
        if question.get("option_order") != ids:
            block(qid, "option order was not explicitly preserved")
        selected = question.get("selected_option_ids")
        if not isinstance(selected, list) or not selected or len(selected) != len(set(selected)) or any(
                i not in ids for i in selected):
            block(qid, "selected IDs are missing or invalid")
            selected = []
        reviews = question.get("option_reviews")
        if not isinstance(reviews, list):
            block(qid, "option_reviews missing")
            reviews = []
        reviewed_ids = [r.get("option_id") if isinstance(r, dict) else None for r in reviews]
        if reviewed_ids != ids:
            block(qid, "each option must be reviewed in original order")
        for r in reviews:
            if not isinstance(r, dict):
                block(qid, "nonobject option review")
                continue
            label = r.get("option_id")
            verdict = r.get("verdict")
            if verdict not in ALLOWED_VERDICTS:
                block(qid, "missing/invalid verdict: " + str(label))
            elif verdict == "uncertain":
                block(qid, "unresolved answer-option uncertainty: " + str(label))
            elif (label in selected and verdict != "supported") or (
                    label not in selected and verdict != "contradicted"):
                block(qid, "selected option vs documented verdict conflict: " + str(label))
            if not isinstance(r.get("rationale"), str) or not r["rationale"].strip():
                block(qid, "missing option rationale: " + str(label))
            sources = r.get("sources")
            if not isinstance(sources, list) or not sources:
                block(qid, "missing official source evidence: " + str(label))
                continue
            for source in sources:
                if not isinstance(source, dict):
                    block(qid, "invalid source object: " + str(label))
                    continue
                if not valid_official_url(source.get("url"), hosts):
                    block(qid, "unallowlisted source URL: " + str(label))
                if not isinstance(source.get("sha256"), str) or not SHA.fullmatch(source["sha256"]):
                    block(qid, "source SHA-256 missing: " + str(label))
                if not isinstance(source.get("quote"), str) or not source["quote"].strip():
                    block(qid, "verbatim source quote missing: " + str(label))
                if source.get("capture_mode") != "downloaded":
                    block(qid, "source download provenance not established: " + str(label))
        visual = question.get("visual")
        if visual is not None:
            if not isinstance(visual, dict):
                block(qid, "invalid visual metadata")
            else:
                for role in ALLOWED_IMAGE_ROLES:
                    if not isinstance(visual.get(role + "_sha256"), str) or not SHA.fullmatch(
                            visual[role + "_sha256"]):
                        block(qid, "original visual checksum missing: " + role)
                rows = visual.get("original_row_order")
                if not isinstance(rows, list) or not rows or visual.get("reviewed_row_order") != rows:
                    block(qid, "visual row order not reviewed exactly")
                if visual.get("obscured_answer") is not False:
                    block(qid, "obscured visual answers cannot be inferred")
                if visual.get("image_meaning_reviewed") is not True:
                    block(qid, "image semantic review pending")
        # Deliberately ignore any AI-provided human-approved or released fields.
    return {
        "status": "blocked" if blockers else "structurally_documented_for_independent_review",
        "question_count": len(questions),
        "blocker_count": len(blockers),
        "blockers": blockers,
        "human_review_approved": False,
        "release_approved": False,
        "note": "Option-level evidence structure only; quotes, source content, answers and images still require independent review.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--private-report", type=Path)
    args = parser.parse_args(argv)
    try:
        report = audit_dossier(json.loads(args.input.read_text(encoding="utf-8")))
        if args.private_report:
            args.private_report.parent.mkdir(parents=True, exist_ok=True)
            args.private_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2 if report["status"] == "blocked" else 0
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print("BLOCKED: " + str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
