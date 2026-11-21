#!/usr/bin/env python3
"""Build the phase-2 research worklist from a technical export.

No AI and no network. Lists held items, answer_not_found questions, and
missing official exam facts. Official-source capture stays a separate hook.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EXAM_FACTS = (
    "duration_minutes",
    "passing_score",
    "question_count",
    "languages",
    "domain_weights",
)


def _load(path: Path) -> object:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _site_path(export_dir: Path, exam: str) -> Path:
    direct = export_dir / f"{exam}.site-format.v2.json"
    if direct.is_file():
        return direct
    parent = export_dir.parent / f"{exam}.site-format.v2.json"
    return parent


def _held_from(export_dir: Path) -> list[dict]:
    held: list[dict] = []
    seen: set[str] = set()
    blobs: list[object] = []
    cannot = _load(export_dir / "cannot-convert.json")
    if isinstance(cannot, list):
        blobs.extend(cannot)
    elif isinstance(cannot, dict):
        blobs.extend(cannot.get("items") or cannot.get("held") or cannot.get("questions") or [])
    fidelity = _load(export_dir / "fidelity.json")
    if isinstance(fidelity, dict):
        if isinstance(fidelity.get("held"), list):
            blobs.extend(fidelity["held"])
        for item in fidelity.get("items") or []:
            if isinstance(item, dict) and (item.get("status") == "held" or item.get("exported") is False):
                blobs.append(item)
    for raw in blobs:
        if not isinstance(raw, dict):
            continue
        if raw.get("exported") is True or raw.get("status") == "exported":
            continue
        qid = str(raw.get("question_key") or raw.get("id") or raw.get("question_id") or "").strip()
        if not qid:
            continue
        reasons = raw.get("reasons") or raw.get("reason") or raw.get("hold_reasons") or []
        if isinstance(reasons, str):
            reasons = [reasons]
        reasons = [str(r) for r in reasons if str(r).strip()]
        if qid in seen:
            for row in held:
                if row["question_key"] == qid:
                    for r in reasons:
                        if r not in row["reasons"]:
                            row["reasons"].append(r)
            continue
        seen.add(qid)
        held.append({"question_key": qid, "reasons": reasons or ["held by fidelity gate"]})
    return held



def _answer_not_found(site: dict) -> list[dict]:
    out = []
    for q in site.get("questions") or []:
        if not isinstance(q, dict):
            continue
        status = ((q.get("answer") or {}).get("status") or "")
        if status == "answer_not_found":
            out.append({
                "question_key": str(q.get("question_key") or ""),
                "reasons": ["answer_not_found"],
            })
    return out


def _official_urls(site: dict, catalog: object, research: object) -> list[str]:
    urls: list[str] = []
    def add(url: object) -> None:
        if isinstance(url, str) and url.startswith("https://") and url not in urls:
            # Drive and social links are not official vendor pages
            host = url.split("/")[2].lower()
            if "drive.google.com" in host or "facebook.com" in host or "youtu" in host:
                return
            urls.append(url)
    exam = (site or {}).get("exam") or {}
    for key in ("official_url", "official_exam_url", "official_study_guide_url"):
        add(exam.get(key))
    if isinstance(catalog, dict):
        add(catalog.get("official_exam_url"))
    if isinstance(catalog, list):
        for row in catalog:
            if isinstance(row, dict):
                add(row.get("official_exam_url"))
    if isinstance(research, dict):
        for src in research.get("sources") or []:
            if isinstance(src, dict):
                add(src.get("url"))
        facts = research.get("facts") or {}
        if isinstance(facts, dict):
            for fact in facts.values():
                if isinstance(fact, dict):
                    add(fact.get("url"))
    return urls


def _missing_facts(site: dict, research: object) -> list[dict]:
    exam = (site or {}).get("exam") or {}
    facts = {}
    if isinstance(research, dict):
        raw = research.get("facts") or research.get("exam_facts") or {}
        if isinstance(raw, dict):
            facts = raw
    missing = []
    for name in EXAM_FACTS:
        entry = facts.get(name) if isinstance(facts, dict) else None
        has_quote = isinstance(entry, dict) and entry.get("url") and entry.get("sha256") and entry.get("quote")
        value = exam.get(name)
        if has_quote:
            continue
        if value in (None, "", [], {}):
            missing.append({
                "fact": name,
                "reason": "not published by the vendor in a saved official source, or no official source is on file",
            })
        else:
            missing.append({
                "fact": name,
                "reason": "a value is present but it has no saved official URL, sha256 and verbatim quote",
            })
    return missing


def build(export_dir: Path, exam: str, catalog_path: Path | None = None, research_path: Path | None = None) -> dict:
    export_dir = export_dir.resolve()
    site_file = _site_path(export_dir, exam)
    site = _load(site_file) if site_file.is_file() else {}
    if not isinstance(site, dict):
        site = {}
    catalog = _load(catalog_path) if catalog_path else None
    if catalog is None and catalog_path is None:
        for c in (export_dir.parent.parent / "catalog.csv", export_dir.parent / "catalog.json"):
            if c.is_file() and c.suffix == ".json":
                catalog = _load(c)
                break
    research = _load(research_path) if research_path else None
    held = _held_from(export_dir)
    anf = _answer_not_found(site)
    missing = _missing_facts(site, research)
    urls = _official_urls(site, catalog, research)
    return {
        "schema_version": 1,
        "exam_code": exam,
        "held": held,
        "answer_not_found": anf,
        "missing_exam_facts": missing,
        "official_urls_available": urls,
        "exported_question_count": len(site.get("questions") or []) if isinstance(site.get("questions"), list) else 0,
        "work_item_count": len(held) + len(anf) + len(missing),
        "ai_research_hook": (
            "Phase 2 AI research is a documented hook only. Do not call a paid model here. "
            "An operator may later research only the items in this worklist from official vendor documentation, "
            "recording URL, sha256 and a verbatim quote, and marking answers researched_unverified."
        ),
        "official_source_capture_hook": (
            "Use scripts/capture_official_source.py on an allowlisted official URL already listed in official_urls_available. "
            "Do not guess URLs. Drive and social links are not official sources."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exam", required=True)
    ap.add_argument("--export-dir", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--catalog", type=Path)
    ap.add_argument("--research", type=Path)
    args = ap.parse_args(argv)
    if not args.export_dir.is_dir():
        print(f"ERROR: export directory not found: {args.export_dir}", file=sys.stderr)
        return 2
    report = build(args.export_dir, args.exam, args.catalog, args.research)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "exam_code": report["exam_code"],
        "held": len(report["held"]),
        "answer_not_found": len(report["answer_not_found"]),
        "missing_exam_facts": len(report["missing_exam_facts"]),
        "official_urls_available": len(report["official_urls_available"]),
        "work_item_count": report["work_item_count"],
        "output": str(args.output),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
