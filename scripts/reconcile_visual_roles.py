#!/usr/bin/env python3
"""Audit image roles against active question IDs; exclude superseded owner images.

Metadata integrity only. This cannot inspect image pixels, verify image answers
or approve publication. Any actual original-PDF review must be done separately.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

SHA = re.compile(r"^[a-f0-9]{64}$")
ROLES = {"question_prompt", "answer_reference", "candidate_exhibit", "cover"}


def reconcile(doc):
    errors = []
    def err(owner, reason):
        errors.append({"item": str(owner), "reason": reason})

    if not isinstance(doc, dict):
        return {"status": "blocked", "errors": [{"item": "document", "reason": "not an object"}]}
    qs = doc.get("active_questions")
    images = doc.get("images")
    if not isinstance(qs, list) or not isinstance(images, list):
        return {"status": "blocked", "errors": [{"item": "document", "reason": "missing question/image arrays"}]}
    expected = {}
    for q in qs:
        if not isinstance(q, dict) or not isinstance(q.get("id"), str) or not q["id"]:
            err("question", "invalid question ID")
            continue
        qid = q["id"]
        if qid in expected:
            err(qid, "duplicate active question")
        roles = q.get("expected_roles")
        if not isinstance(roles, list) or any(r not in ROLES for r in roles):
            err(qid, "invalid expected visual roles")
            roles = []
        expected[qid] = set(roles)
    active, superseded = [], []
    seen = set()
    found = {qid: set() for qid in expected}
    for item in images:
        if not isinstance(item, dict):
            err("image", "image record is not an object")
            continue
        asset = item.get("id")
        owner = item.get("owner_question")
        role = item.get("role")
        state = item.get("owner_state")
        if not isinstance(asset, str) or not asset:
            err("image", "missing image ID")
            continue
        if asset in seen:
            err(asset, "duplicate image ID")
        seen.add(asset)
        if role not in ROLES:
            err(asset, "unknown image role")
        if not isinstance(item.get("sha256"), str) or not SHA.fullmatch(item["sha256"]):
            err(asset, "missing original image checksum")
        if state == "superseded":
            superseded.append(asset)
            if owner in expected:
                err(asset, "active owner image incorrectly marked superseded")
            if item.get("learner_visible") is True:
                err(asset, "superseded image exposed to learner")
            continue
        if state != "active":
            err(asset, "owner_state must be active or superseded")
            continue
        active.append(asset)
        if owner not in expected:
            err(asset, "image owner is not an active question")
            continue
        found[owner].add(role)
        if role == "answer_reference" and item.get("learner_visible") is True:
            err(asset, "answer-reference image exposed to learner")
        if item.get("reviewer_only") is True and item.get("learner_visible") is True:
            err(asset, "reviewer-only image exposed to learner")
        if item.get("visual_answer_verified") is not True and role == "answer_reference":
            err(asset, "visual answer meaning review still pending")
    for qid, roles in expected.items():
        for role in sorted(roles - found[qid]):
            err(qid, "expected active image role not found: " + role)
    counts = {role: sum(1 for img in images if isinstance(img, dict)
                       and img.get("owner_state") == "active" and img.get("role") == role)
              for role in sorted(ROLES)}
    return {
        "status": "blocked" if errors else "role_metadata_consistent_pending_independent_review",
        "active_question_count": len(expected),
        "active_image_count": len(active),
        "superseded_image_count": len(superseded),
        "active_image_roles": counts,
        "errors": errors,
        "error_count": len(errors),
        "pixel_integrity_verified_by_this_tool": False,
        "answer_truth_verified_by_this_tool": False,
        "release_approved": False,
        "note": "Role metadata only; verify source PDF pixels and answer meaning independently.",
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--private-report", type=Path)
    a = p.parse_args(argv)
    try:
        report = reconcile(json.loads(a.input.read_text(encoding="utf-8")))
        if a.private_report:
            a.private_report.parent.mkdir(parents=True, exist_ok=True)
            a.private_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2 if report["status"] == "blocked" else 0
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print("BLOCKED: " + str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
