#!/usr/bin/env python3
"""Map exported questions to official exam domains. Scripts only, no web, no AI.

An official domain list is used only when it is already saved with a URL,
sha256 and verbatim quote. If that evidence is missing, questions are kept
and every one is flagged domain_unmapped. This script never guesses a
domain name silently.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

STOP = {
    "a", "an", "and", "the", "or", "of", "to", "in", "on", "for", "with",
    "by", "at", "from", "as", "is", "are", "be", "this", "that", "it",
    "its", "into", "about", "over", "under", "exam", "domain", "objective",
    "objectives", "weight", "percent", "percentage",
}


def _load_json(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _has_official_evidence(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    url = str(data.get("url") or data.get("official_url") or data.get("source_url") or "").strip()
    sha = str(data.get("sha256") or data.get("source_sha256") or data.get("sha") or "").strip()
    quote = str(
        data.get("quote")
        or data.get("verbatim_quote")
        or data.get("verbatim")
        or data.get("quote_text")
        or ""
    ).strip()
    if url.startswith("http") and len(sha) == 64 and quote:
        return True
    for key in ("evidence", "receipt", "source", "official_source"):
        inner = data.get(key)
        if isinstance(inner, dict) and _has_official_evidence(inner):
            return True
        if isinstance(inner, list) and any(_has_official_evidence(x) for x in inner if isinstance(x, dict)):
            return True
    return False


def _receipt_files(roots: list[Path]) -> list[Path]:
    names = (
        "receipt.json",
        "source.json",
        "official-source.json",
        "official_source.json",
        "capture.json",
        "exam_official_facts.json",
    )
    out: list[Path] = []
    for root in roots:
        if not root:
            continue
        for rel in (
            "official",
            "official/receipts",
            "import",
            "evidence",
            ".",
        ):
            base = root / rel if rel != "." else root
            if not base.is_dir():
                continue
            for name in names:
                path = base / name
                if path.is_file():
                    out.append(path)
    return out


def official_evidence_present(roots: list[Path]) -> dict | None:
    for path in _receipt_files(roots):
        data = _load_json(path)
        if _has_official_evidence(data):
            return {"path": str(path), "ok": True}
        if isinstance(data, list):
            for item in data:
                if _has_official_evidence(item):
                    return {"path": str(path), "ok": True}
    return None


def _domain_from_row(row: dict) -> dict | None:
    name = (row.get("domain_name") or row.get("name") or row.get("title") or "").strip()
    if not name:
        return None
    key = (row.get("domain_key") or row.get("code") or row.get("id") or name).strip()
    blob = " ".join(
        str(row.get(k) or "")
        for k in ("keywords", "objectives", "objective", "description", "text", "name", "domain_name")
    )
    return {"key": key, "name": name, "text": blob}


def load_official_domains(roots: list[Path]) -> list[dict]:
    candidates: list[Path] = []
    for root in roots:
        if not root:
            continue
        for rel in (
            "import/domains.csv",
            "official/domains.csv",
            "official/objectives.json",
            "import/objectives.json",
            "official/domains.json",
            "authoring/domains.csv",
        ):
            path = root / rel
            if path.is_file():
                candidates.append(path)
    domains: list[dict] = []
    seen = set()
    for path in candidates:
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    rec = _domain_from_row(row or {})
                    if rec and rec["name"] not in seen:
                        seen.add(rec["name"])
                        rec["source_path"] = str(path)
                        domains.append(rec)
        else:
            data = _load_json(path)
            rows = []
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = data.get("domains") or data.get("objectives") or []
                if isinstance(data.get("objectives"), dict):
                    rows = data["objectives"].get("domains") or rows
            for row in rows:
                if not isinstance(row, dict):
                    continue
                rec = _domain_from_row(row)
                if rec and rec["name"] not in seen:
                    seen.add(rec["name"])
                    rec["source_path"] = str(path)
                    domains.append(rec)
    return domains


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[A-Za-z0-9]+", (text or "").lower()) if t not in STOP and len(t) >= 3}


def map_question(question: dict, domains: list[dict]) -> str | None:
    learner = question.get("learner") or {}
    parts = [json.dumps(learner.get("stem") or question.get("stem") or "")]
    for c in learner.get("choices") or question.get("choices") or []:
        parts.append(json.dumps(c) if not isinstance(c, str) else c)
    qtok = _tokens(" ".join(parts))
    if not qtok or not domains:
        return None
    scores = []
    for dom in domains:
        dtok = _tokens(dom["name"] + " " + (dom.get("text") or ""))
        if not dtok:
            dtok = _tokens(dom["name"])
        score = len(qtok & dtok)
        # Prefer a whole-word hit on a distinctive domain-name token.
        name_tok = _tokens(dom["name"])
        if name_tok & qtok:
            score += 3
        scores.append((score, dom["name"]))
    scores.sort(reverse=True)
    if not scores or scores[0][0] <= 0:
        return None
    if len(scores) > 1 and scores[0][0] == scores[1][0]:
        return None
    return scores[0][1]


def apply_mapping(site: dict, domains: list[dict], evidence_ok: bool) -> dict:
    questions = site.get("questions") if isinstance(site, dict) else None
    if not isinstance(questions, list):
        questions = []
    mapped = []
    unmapped = []
    status = "mapped"
    reason = ""
    if not evidence_ok or not domains:
        status = "domain_unmapped"
        reason = (
            "no official domain list is saved with a URL, sha256 and verbatim quote"
            if not evidence_ok or not domains
            else ""
        )
        for q in questions:
            key = q.get("question_key") or q.get("id")
            unmapped.append({"question_key": key, "reason": "domain_unmapped"})
    else:
        for q in questions:
            key = q.get("question_key") or q.get("id")
            name = map_question(q, domains)
            if name:
                q["domain"] = name
                mapped.append({"question_key": key, "domain": name})
            else:
                if not q.get("domain") or q.get("domain") == "Unassigned":
                    q["domain"] = "Unassigned"
                unmapped.append({"question_key": key, "reason": "domain_unmapped"})
        if unmapped:
            status = "domain_unmapped"
            reason = "one or more questions could not be mapped from the official domain list without guessing"
    return {
        "schema_version": 1,
        "status": status,
        "reason": reason,
        "official_domain_list_saved": bool(evidence_ok and domains),
        "official_domain_count": len(domains) if evidence_ok and domains else 0,
        "question_count": len(questions),
        "mapped_count": len(mapped),
        "unmapped_count": len(unmapped),
        "mapped": mapped,
        "unmapped": unmapped,
        "promotion_blocker": status != "mapped" or bool(unmapped),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site-file", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--raw-dir", type=Path)
    ap.add_argument("--workspace", type=Path)
    args = ap.parse_args(argv)
    site = _load_json(args.site_file)
    if not isinstance(site, dict):
        raise SystemExit("ERROR: site v2 file is missing or invalid")
    roots: list[Path] = []
    if args.raw_dir:
        roots.append(args.raw_dir)
    if args.workspace:
        roots.append(args.workspace)
        exam = (site.get("exam") or {}).get("exam_code")
        if exam:
            roots.append(args.workspace / "out" / str(exam))
    evidence = official_evidence_present(roots)
    domains = load_official_domains(roots) if evidence else []
    report = apply_mapping(site, domains, bool(evidence) and bool(domains))
    if report["official_domain_list_saved"] and report["mapped_count"]:
        args.site_file.write_text(json.dumps(site, indent=2) + "\n", encoding="utf-8")
        report["site_file_updated"] = True
    else:
        report["site_file_updated"] = False
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "official_domain_list_saved": report["official_domain_list_saved"],
        "mapped_count": report["mapped_count"],
        "unmapped_count": report["unmapped_count"],
        "promotion_blocker": report["promotion_blocker"],
    }))
    return 0 if not report["promotion_blocker"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
