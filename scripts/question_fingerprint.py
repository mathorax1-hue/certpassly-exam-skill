#!/usr/bin/env python3
"""Fingerprint questions and classify same/changed/new/retired on an update.

Reports use IDs, hashes and counts only. Question text is never printed.
Prior IDs are kept for same and changed items. Retired IDs are never reused
or deleted. Cross-PDF (or in-batch) duplicates are kept once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

EXAM_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,39}$")
MIN_ID_WIDTH = 3


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def valid_exam_code(code: str) -> bool:
    return bool(code and EXAM_CODE_RE.fullmatch(code))


def _plain(node) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float, bool)):
        return str(node)
    if isinstance(node, list):
        return " ".join(_plain(x) for x in node if x is not None)
    if isinstance(node, dict):
        if "text" in node and isinstance(node["text"], str):
            parts = [node["text"]]
            for key in ("content", "children", "items"):
                if key in node:
                    parts.append(_plain(node[key]))
            return " ".join(parts)
        return " ".join(_plain(v) for k, v in node.items() if k not in {"url", "id", "type", "version"})
    return ""


def normalize_text(text: str) -> str:
    s = (text or "").replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def normalize_answer(answer) -> list[str]:
    if answer is None:
        return []
    if isinstance(answer, dict):
        if "answer_key" in answer:
            return normalize_answer(answer.get("answer_key"))
        if "key" in answer:
            return normalize_answer(answer.get("key"))
        return [normalize_text(_plain(answer))]
    if isinstance(answer, (list, tuple)):
        return [normalize_text(_plain(x)) for x in answer]
    return [normalize_text(_plain(answer))]


def _choices_from_learner(learner: dict) -> list[str]:
    out = []
    for ch in learner.get("choices") or []:
        out.append(normalize_text(_plain(ch)))
    return out


def fingerprint_payload(stem: str, choices: list[str], answer: list[str], qtype: str = "") -> dict:
    # Type is stored on the index but is not part of the identity hash.
    return {
        "stem": normalize_text(stem),
        "choices": [normalize_text(c) for c in (choices or [])],
        "answer": [normalize_text(a) for a in (answer or [])],
    }


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprints_from_payload(payload: dict) -> tuple[str, str]:
    full = sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
    stem_fp = sha256_text(payload.get("stem") or "")
    return full, stem_fp


def item_from_site_question(q: dict) -> dict | None:
    if not isinstance(q, dict):
        return None
    learner = q.get("learner") or {}
    payload = fingerprint_payload(
        _plain(learner.get("stem")),
        _choices_from_learner(learner if isinstance(learner, dict) else {}),
        normalize_answer(q.get("answer")),
        str(q.get("type") or ""),
    )
    full, stem_fp = fingerprints_from_payload(payload)
    key = str(q.get("question_key") or q.get("id") or "").strip()
    if not key:
        return None
    return {
        "question_id": key,
        "fingerprint": full,
        "stem_fingerprint": stem_fp,
        "type": str(q.get("type") or ""),
        "origin": "exported",
    }


def item_from_extracted(data: dict) -> dict | None:
    if not isinstance(data, dict):
        return None
    key = str(data.get("question_key") or data.get("id") or "").strip()
    if not key:
        return None
    opts = data.get("options") or {}
    if isinstance(opts, dict):
        choices = [normalize_text(_plain(v)) for v in opts.values()]
    elif isinstance(opts, list):
        choices = [normalize_text(_plain(v)) for v in opts]
    else:
        choices = []
    answer = data.get("answer_raw")
    if answer is None:
        answer = data.get("answer") or data.get("key")
    payload = fingerprint_payload(_plain(data.get("stem")), choices, normalize_answer(answer), str(data.get("type") or ""))
    full, stem_fp = fingerprints_from_payload(payload)
    return {
        "question_id": key,
        "fingerprint": full,
        "stem_fingerprint": stem_fp,
        "type": str(data.get("type") or ""),
        "origin": "extracted",
    }


def load_items_from_run(run_dir: Path, exam_code: str) -> list[dict]:
    items: list[dict] = []
    seen_ids: set[str] = set()
    site = Path(run_dir) / ("%s.site-format.v2.json" % exam_code)
    if site.is_file():
        try:
            data = json.loads(site.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        for q in (data.get("questions") or []) if isinstance(data, dict) else []:
            item = item_from_site_question(q)
            if item and item["question_id"] not in seen_ids:
                items.append(item)
                seen_ids.add(item["question_id"])
    extracted = Path(run_dir) / "extracted" / "items"
    if extracted.is_dir():
        for path in sorted(extracted.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            item = item_from_extracted(data)
            if item and item["question_id"] not in seen_ids:
                items.append(item)
                seen_ids.add(item["question_id"])
    return items


def load_index(path: Path) -> dict:
    if not path or not path.is_file():
        return {"exam_code": "", "questions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"exam_code": "", "questions": []}
    if not isinstance(data, dict):
        return {"exam_code": "", "questions": []}
    data.setdefault("questions", [])
    return data


def next_question_id(used: set[str]) -> str:
    n = 1
    while True:
        cand = "q%0*d" % (MIN_ID_WIDTH, n)
        if cand not in used:
            return cand
        n += 1


def diff_items(previous: list[dict], incoming: list[dict]) -> dict:
    """Classify incoming items against the previous index.

    Duplicates in the incoming batch (same full fingerprint) are kept once.
    Retired previous IDs stay in the result with status retired.
    """
    prev_active = [q for q in previous if (q.get("status") or "active") != "retired"]
    retired_prev = [q for q in previous if (q.get("status") or "") == "retired"]
    used_ids = {q["question_id"] for q in previous if q.get("question_id")}

    by_fp: dict[str, dict] = {}
    by_stem: dict[str, list[dict]] = {}
    for q in prev_active:
        fp = q.get("fingerprint") or ""
        if fp and fp not in by_fp:
            by_fp[fp] = q
        stem = q.get("stem_fingerprint") or ""
        if stem:
            by_stem.setdefault(stem, []).append(q)

    assigned_old: set[str] = set()
    seen_fp: set[str] = set()
    results: list[dict] = []
    duplicates: list[dict] = []

    for item in incoming:
        fp = item.get("fingerprint") or ""
        if fp and fp in seen_fp:
            duplicates.append({
                "fingerprint": fp,
                "incoming_id": item.get("question_id"),
                "kept_id": next((r["question_id"] for r in results if r.get("fingerprint") == fp), ""),
                "status": "duplicate",
            })
            continue
        if fp:
            seen_fp.add(fp)

        match = by_fp.get(fp) if fp else None
        if match and match["question_id"] not in assigned_old:
            results.append({
                "question_id": match["question_id"],
                "incoming_id": item.get("question_id"),
                "fingerprint": fp,
                "stem_fingerprint": item.get("stem_fingerprint") or "",
                "status": "same",
                "type": item.get("type") or match.get("type") or "",
                "origin": item.get("origin") or "",
            })
            assigned_old.add(match["question_id"])
            continue

        stem = item.get("stem_fingerprint") or ""
        stem_match = None
        for cand in by_stem.get(stem) or []:
            if cand["question_id"] not in assigned_old:
                stem_match = cand
                break
        if stem_match:
            results.append({
                "question_id": stem_match["question_id"],
                "incoming_id": item.get("question_id"),
                "fingerprint": fp,
                "stem_fingerprint": stem,
                "status": "changed",
                "type": item.get("type") or stem_match.get("type") or "",
                "origin": item.get("origin") or "",
            })
            assigned_old.add(stem_match["question_id"])
            continue

        new_id = next_question_id(used_ids)
        used_ids.add(new_id)
        results.append({
            "question_id": new_id,
            "incoming_id": item.get("question_id"),
            "fingerprint": fp,
            "stem_fingerprint": stem,
            "status": "new",
            "type": item.get("type") or "",
            "origin": item.get("origin") or "",
        })

    retired = []
    for q in prev_active:
        if q["question_id"] not in assigned_old:
            row = {
                "question_id": q["question_id"],
                "incoming_id": "",
                "fingerprint": q.get("fingerprint") or "",
                "stem_fingerprint": q.get("stem_fingerprint") or "",
                "status": "retired",
                "type": q.get("type") or "",
                "origin": q.get("origin") or "",
                "retired_at": utc_now(),
            }
            retired.append(row)
            results.append(row)

    # Keep earlier retired rows in the index, unchanged.
    for q in retired_prev:
        results.append({
            "question_id": q["question_id"],
            "incoming_id": "",
            "fingerprint": q.get("fingerprint") or "",
            "stem_fingerprint": q.get("stem_fingerprint") or "",
            "status": "retired",
            "type": q.get("type") or "",
            "origin": q.get("origin") or "",
            "retired_at": q.get("retired_at") or "",
        })

    counts = {
        "same": sum(1 for r in results if r["status"] == "same"),
        "changed": sum(1 for r in results if r["status"] == "changed"),
        "new": sum(1 for r in results if r["status"] == "new"),
        "retired": sum(1 for r in results if r["status"] == "retired"),
        "duplicate": len(duplicates),
    }
    return {"items": results, "duplicates": duplicates, "counts": counts}


def counts_only(result: dict) -> dict:
    c = dict(result.get("counts") or {})
    c["incoming"] = c.get("same", 0) + c.get("changed", 0) + c.get("new", 0)
    return c


def write_change_report(path_json: Path, path_md: Path, exam_code: str, result: dict, source_version=None, source_sha256: str = "") -> None:
    counts = counts_only(result)
    payload = {
        "exam_code": exam_code,
        "generated_at": utc_now(),
        "source_version": source_version,
        "source_sha256": source_sha256,
        "counts": counts,
        "items": [
            {
                "question_id": r.get("question_id"),
                "incoming_id": r.get("incoming_id") or "",
                "status": r.get("status"),
                "fingerprint": r.get("fingerprint"),
            }
            for r in result.get("items") or []
        ],
        "duplicates": result.get("duplicates") or [],
        "note": "IDs, hashes and counts only. Question text is not stored in this report.",
    }
    path_json.parent.mkdir(parents=True, exist_ok=True)
    path_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Change report for %s" % exam_code,
        "",
        "Generated at %s" % payload["generated_at"],
        "",
        "- same: %s" % counts.get("same", 0),
        "- changed: %s" % counts.get("changed", 0),
        "- new: %s" % counts.get("new", 0),
        "- retired: %s" % counts.get("retired", 0),
        "- duplicate: %s" % counts.get("duplicate", 0),
        "",
        "| question_id | incoming_id | status | fingerprint_prefix |",
        "| --- | --- | --- | --- |",
    ]
    for r in payload["items"]:
        fp = r.get("fingerprint") or ""
        lines.append("| %s | %s | %s | %s |" % (
            r.get("question_id") or "",
            r.get("incoming_id") or "",
            r.get("status") or "",
            fp[:12],
        ))
    if payload["duplicates"]:
        lines.extend(["", "Duplicates kept once: %s" % len(payload["duplicates"])])
    path_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_index(path: Path, exam_code: str, result: dict, source_version=None, source_sha256: str = "") -> None:
    questions = []
    for r in result.get("items") or []:
        questions.append({
            "question_id": r.get("question_id"),
            "fingerprint": r.get("fingerprint") or "",
            "stem_fingerprint": r.get("stem_fingerprint") or "",
            "status": "retired" if r.get("status") == "retired" else "active",
            "last_status": r.get("status"),
            "type": r.get("type") or "",
            "origin": r.get("origin") or "",
            "retired_at": r.get("retired_at") or "",
        })
    payload = {
        "exam_code": exam_code,
        "updated_at": utc_now(),
        "source_version": source_version,
        "source_sha256": source_sha256,
        "counts": counts_only(result),
        "questions": questions,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def remap_question_key(data, mapping: dict[str, str]):
    if isinstance(data, dict):
        if "question_key" in data and str(data["question_key"]) in mapping:
            data = dict(data)
            data["question_key"] = mapping[str(data["question_key"])]
        return {k: remap_question_key(v, mapping) for k, v in data.items()}
    if isinstance(data, list):
        return [remap_question_key(v, mapping) for v in data]
    return data


def apply_id_mapping(run_dir: Path, exam_code: str, result: dict) -> int:
    """Rewrite incoming question_key values to stable IDs. Returns files changed."""
    mapping = {}
    for r in result.get("items") or []:
        incoming = r.get("incoming_id") or ""
        stable = r.get("question_id") or ""
        if incoming and stable and incoming != stable:
            mapping[incoming] = stable
    if not mapping:
        return 0
    changed = 0
    root = Path(run_dir)
    candidates = [root / ("%s.site-format.v2.json" % exam_code), root / "questions.json"]
    for folder in (root / "extracted" / "items", root / "export"):
        if folder.is_dir():
            candidates.extend(sorted(folder.rglob("*.json")))
    seen: set[Path] = set()
    for path in candidates:
        path = path.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        updated = remap_question_key(data, mapping)
        if updated != data:
            path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            changed += 1
    return changed


def load_source_meta(raw_dir: Path) -> tuple[object, str]:
    sources = Path(raw_dir) / "sources.json" if raw_dir else None
    if not sources or not sources.is_file():
        return None, ""
    try:
        data = json.loads(sources.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, ""
    current = data.get("current_version")
    sha = ""
    for row in data.get("sources") or []:
        if row.get("version") == current or row.get("status") == "active":
            sha = row.get("sha256") or sha
            if current is None:
                current = row.get("version")
    return current, sha


def process_run(exam_code: str, run_dir: Path, raw_dir: Path | None, reports_dir: Path | None = None, update_run_files: bool = True) -> dict:
    if not valid_exam_code(exam_code):
        raise SystemExit("Invalid exam code")
    run_dir = Path(run_dir)
    incoming = load_items_from_run(run_dir, exam_code)
    index_path = Path(raw_dir) / "questions-index.json" if raw_dir else run_dir / "questions-index.json"
    previous = load_index(index_path).get("questions") or []
    result = diff_items(previous, incoming)
    version, sha = load_source_meta(raw_dir) if raw_dir else (None, "")
    reports = Path(reports_dir) if reports_dir else (run_dir / "phase-reports")
    if update_run_files:
        write_change_report(reports / "change-report.json", reports / "change-report.md", exam_code, result, version, sha)
        apply_id_mapping(run_dir, exam_code, result)
        write_index(run_dir / "questions-index.json", exam_code, result, version, sha)
    if raw_dir:
        write_index(Path(raw_dir) / "questions-index.json", exam_code, result, version, sha)
        # Keep a copy of the change report next to the index.
        write_change_report(
            Path(raw_dir) / "changes" / ("v%s-change-report.json" % (version or "unknown")),
            Path(raw_dir) / "changes" / ("v%s-change-report.md" % (version or "unknown")),
            exam_code, result, version, sha,
        )
    elif not update_run_files:
        write_change_report(reports / "change-report.json", reports / "change-report.md", exam_code, result, version, sha)
    return {"counts": counts_only(result), "exam_code": exam_code}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exam", required=True)
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--raw-dir", type=Path)
    ap.add_argument("--reports-dir", type=Path)
    ap.add_argument("--no-update-run-files", action="store_true", help="Write the index and change report only; do not rewrite a historical run")
    args = ap.parse_args(argv)
    result = process_run(args.exam, args.run_dir, args.raw_dir, args.reports_dir, update_run_files=not args.no_update_run_files)
    print(json.dumps({"exam_code": result["exam_code"], **result["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
