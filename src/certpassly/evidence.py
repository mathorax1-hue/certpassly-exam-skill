"""Fail-closed STRUCTURAL review of evidence and visual publication safety.

Does not independently fetch or authenticate vendor pages. An AI cannot use
this result as evidence of independent human approval or site acceptance.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _official(url: str, domains: list[str]) -> bool:
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower().rstrip(".")
        return p.scheme == "https" and not p.username and not p.password and any(
            host == domain or host.endswith("." + domain)
            for domain in domains if domain and "." in domain
        )
    except (TypeError, ValueError):
        return False


def audit_bank(bank: dict) -> dict:
    blockers: list[dict] = []
    def flag(item: str, reason: str):
        blockers.append({"item": item, "reason": reason})

    questions = bank.get("questions")
    domains = bank.get("official_domains")
    if not isinstance(questions, list) or not isinstance(domains, list):
        return {"status": "blocked", "question_count": 0, "media_count": 0,
                "blockers": [{"item": "bank", "reason": "questions and official_domains must be lists"}],
                "warning": "Structural audit only; not independent answer verification or release approval"}
    domains = [x.lower().rstrip(".") for x in domains if isinstance(x, str)]
    if not domains:
        flag("bank", "official_domains must include vendor-owned domain(s)")
    identifiers = set()
    for q in questions:
        if not isinstance(q, dict):
            flag("question", "question entry must be an object")
            continue
        item = str(q.get("id") or "unnamed")
        if item in identifiers:
            flag(item, "duplicate question ID")
        identifiers.add(item)
        if not isinstance(q.get("correct_answer"), (str, list)) or not q.get("correct_answer"):
            flag(item, "correct_answer missing")
        if q.get("accuracy_status") != "key_matches_current_docs":
            flag(item, "answer key not verified against current official documentation")
        if q.get("human_review_required") is not False:
            flag(item, "independent question review pending")
        evidence = q.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            flag(item, "official evidence missing")
            continue
        has_supported_source = False
        for ev in evidence:
            if not isinstance(ev, dict):
                flag(item, "invalid evidence entry")
                continue
            url = ev.get("url")
            sha = ev.get("saved_page_sha256")
            quote = ev.get("verbatim_quote")
            if (_official(url, domains) and isinstance(sha, str) and SHA256.fullmatch(sha)
                    and isinstance(quote, str) and quote.strip() and
                    ev.get("supports_correct_answer") is True):
                has_supported_source = True
        if not has_supported_source:
            flag(item, "no structurally valid official answer-support evidence")
    media = bank.get("media", [])
    if not isinstance(media, list):
        flag("bank", "media must be a list")
        media = []
    seen_media = set()
    for asset in media:
        if not isinstance(asset, dict):
            flag("media", "media entry must be an object")
            continue
        aid = str(asset.get("id") or "unnamed")
        if aid in seen_media:
            flag(aid, "duplicate media ID")
        seen_media.add(aid)
        role = asset.get("role")
        if role not in ("question_prompt", "answer_reference", "candidate_exhibit", "cover"):
            flag(aid, "unknown visual role")
        if role == "answer_reference" and asset.get("answer_verified") is not True:
            flag(aid, "visual answer reference not verified")
        if asset.get("approved_for_release") is not True:
            flag(aid, "visual asset not approved")
        if role == "answer_reference" and asset.get("in_learner_payload") is True:
            flag(aid, "answer-reference image exposed to learner")
        if asset.get("reviewer_only") is True and asset.get("in_learner_payload") is True:
            flag(aid, "reviewer-only asset exposed to learner")
    return {
        "status": "evidence_ready_for_independent_gate" if not blockers else "blocked",
        "exam_code": bank.get("exam_code", "unknown"),
        "question_count": len(questions), "media_count": len(media),
        "blocker_count": len(blockers), "blockers": blockers,
        "warning": "Structural checks do not verify whether a source is genuine, answer is correct, reviewer is independent, or site import succeeded",
        "audited_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def audit_file(path: Path) -> dict:
    return audit_bank(json.loads(path.read_text(encoding="utf-8")))
