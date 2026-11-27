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


def normalize_question_id(qid: str, exam_code: str = "") -> str:
    """Return the exam-scoped form of a question ID.

    Older indexes use short keys (q001) while newer exports use exam-scoped
    keys (AB-730-q001). Both forms name the same question, so the change
    classifier compares and stores the scoped form. An ID that already
    carries a different exam prefix is left alone. With no exam code the
    ID is returned unchanged.
    """
    qid = (qid or "").strip()
    if not qid or not exam_code:
        return qid
    code = exam_code.strip()
    if qid == code or qid.startswith(code + "-"):
        return qid
    if "-" in qid:
        return qid
    return "%s-%s" % (code, qid)


def _has_choices(item: dict) -> bool:
    """True when the identity payload carries at least one choice.

    A fingerprint collision proves duplication only when the payload can
    tell questions apart. Matrix and dropdown items read from page images
    share one generic stem with no choices, so their fingerprints collide
    even though they are different questions. Only a payload with choices
    can prove two items are the same question.
    """
    return bool(item.get("has_choices"))


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
        return [canonical_answer_token(x) for x in answer]
    return [canonical_answer_token(answer)]


def canonical_answer_token(value) -> str:
    """Map a letter key (A/b) to a 0-based index string; leave other values normalized.

    Site exports use numeric answer_key lists. Extracted items use A/B/C/D.
    Identity must treat those as the same selection.
    """
    s = normalize_text(_plain(value))
    if len(s) == 1 and "a" <= s <= "z":
        return str(ord(s) - ord("a"))
    return s


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
        "answer": [canonical_answer_token(a) for a in (answer or [])],
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
        "has_choices": bool([c for c in payload["choices"] if c]),
    }


def item_from_extracted(data: dict, question_id: str | None = None) -> dict | None:
    if not isinstance(data, dict):
        return None
    key = str(question_id or data.get("question_key") or data.get("id") or "").strip()
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
        "key_in_file": str(data.get("question_key") or data.get("id") or "").strip(),
        "has_choices": bool([c for c in payload["choices"] if c]),
    }


def load_json_file(path: Path):
    if not path or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_held_keys(run_dir: Path) -> set[str]:
    data = load_json_file(Path(run_dir) / "export" / "cannot-convert.json")
    keys: set[str] = set()
    rows = data if isinstance(data, list) else (data.get("items") or data.get("held") or []) if isinstance(data, dict) else []
    for row in rows:
        if isinstance(row, dict):
            key = str(row.get("question_key") or row.get("id") or row.get("question_id") or "").strip()
        else:
            key = str(row or "").strip()
        if key:
            keys.add(key)
    return keys


def load_site_keys(run_dir: Path, exam_code: str) -> set[str]:
    data = load_json_file(Path(run_dir) / ("%s.site-format.v2.json" % exam_code))
    keys: set[str] = set()
    if isinstance(data, dict):
        for q in data.get("questions") or []:
            if isinstance(q, dict):
                key = str(q.get("question_key") or q.get("id") or "").strip()
                if key:
                    keys.add(key)
    return keys


def export_status_for(file_id: str, key_in_file: str, held_keys: set[str], site_keys: set[str], exam_code: str = "") -> str:
    """Prefer the extracted file stem. A remapped question_key can collide with
    another item's held or exported ID, so it is only used to detect that this
    file's content was exported.

    Keys are compared in exam-scoped form: the site file uses scoped keys
    (AB-730-q001) while extracted file stems are short (q001). Without the
    normalization every exported question reads as held.
    """
    norm = lambda k: normalize_question_id(k, exam_code)
    file_id_n = norm(file_id)
    key_n = norm(key_in_file)
    held_n = {norm(k) for k in held_keys}
    site_n = {norm(k) for k in site_keys}
    if file_id_n and file_id_n in held_n:
        return "held"
    if file_id_n and file_id_n in site_n:
        return "exported"
    if key_n and key_n in site_n:
        return "exported"
    if site_n or held_n:
        return "held"
    return ""


def load_items_from_run(run_dir: Path, exam_code: str) -> list[dict]:
    """Load identity items from PDF-derived extracted files when present.

    The site export is not the identity source: its stems, choices, types,
    and answer_key forms can change when an item moves from held to exported
    or when a type-builder wraps the same PDF content. Held items are included.
    File stems are the stable incoming IDs, even if question_key was remapped.
    """
    run_dir = Path(run_dir)
    held_keys = load_held_keys(run_dir)
    site_keys = load_site_keys(run_dir, exam_code)
    items: list[dict] = []
    seen_ids: set[str] = set()
    extracted = run_dir / "extracted" / "items"
    if extracted.is_dir():
        for path in sorted(extracted.glob("*.json")):
            data = load_json_file(path)
            if not isinstance(data, dict):
                continue
            item = item_from_extracted(data, question_id=path.stem)
            if not item or item["question_id"] in seen_ids:
                continue
            item["export_status"] = export_status_for(
                path.stem, item.get("key_in_file") or "", held_keys, site_keys, exam_code
            )
            items.append(item)
            seen_ids.add(item["question_id"])
        return items
    # Tests and incomplete runs may only have a site file.
    site = run_dir / ("%s.site-format.v2.json" % exam_code)
    data = load_json_file(site)
    if isinstance(data, dict):
        for q in data.get("questions") or []:
            item = item_from_site_question(q)
            if item and item["question_id"] not in seen_ids:
                item["export_status"] = "held" if item["question_id"] in held_keys else "exported"
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


def next_question_id(used: set[str], exam_code: str = "") -> str:
    n = 1
    while True:
        cand = normalize_question_id("q%0*d" % (MIN_ID_WIDTH, n), exam_code)
        if cand not in used:
            return cand
        n += 1


def allocate_question_id(incoming_id: str, used_ids: set[str], exam_code: str = "") -> str:
    """Keep the incoming PDF key when it is free. Never reuse a retired ID.

    IDs are compared and allocated in exam-scoped form, so a short incoming
    key (q001) keeps its scoped form (AB-730-q001) and a generated ID never
    collides with a scoped entry already in the index.
    """
    cid = normalize_question_id((incoming_id or "").strip(), exam_code)
    if cid and cid not in used_ids:
        return cid
    return next_question_id(used_ids, exam_code)


def diff_items(previous: list[dict], incoming: list[dict], exam_code: str = "") -> dict:
    """Classify incoming items against the previous index.

    Duplicates in the incoming batch (same full fingerprint, with real
    content) are kept once. Retired previous IDs stay in the result with
    status retired.

    Question IDs are compared and stored in exam-scoped form: an old index
    entry q001 and a new export entry AB-730-q001 are the same question.
    With no exam code the IDs are used as given, exactly as before.
    """
    prev_active = [q for q in previous if (q.get("status") or "active") != "retired"]
    retired_prev = [q for q in previous if (q.get("status") or "") == "retired"]
    used_ids = {normalize_question_id(q["question_id"], exam_code) for q in previous if q.get("question_id")}

    by_fp: dict[str, list[dict]] = {}
    by_stem: dict[str, list[dict]] = {}
    by_id: dict[str, dict] = {}
    for q in prev_active:
        fp = q.get("fingerprint") or ""
        if fp:
            by_fp.setdefault(fp, []).append(q)
        stem = q.get("stem_fingerprint") or ""
        if stem:
            by_stem.setdefault(stem, []).append(q)
        qid = normalize_question_id(q.get("question_id") or "", exam_code)
        if qid and qid not in by_id:
            by_id[qid] = q

    assigned_old: set[str] = set()
    seen_fp: set[str] = set()
    results: list[dict] = []
    duplicates: list[dict] = []

    for item in incoming:
        fp = item.get("fingerprint") or ""
        if fp and fp in seen_fp and _has_choices(item):
            duplicates.append({
                "fingerprint": fp,
                "incoming_id": item.get("question_id"),
                "kept_id": next((r["question_id"] for r in results if r.get("fingerprint") == fp), ""),
                "status": "duplicate",
            })
            continue
        if fp:
            seen_fp.add(fp)

        match = None
        for cand in by_fp.get(fp) or []:
            if cand["question_id"] not in assigned_old:
                match = cand
                break
        if match:
            prev_export = match.get("export_status") or ""
            new_export = item.get("export_status") or prev_export
            results.append({
                "question_id": normalize_question_id(match["question_id"], exam_code),
                "incoming_id": item.get("question_id"),
                "fingerprint": fp,
                "stem_fingerprint": item.get("stem_fingerprint") or "",
                "status": "same",
                "type": item.get("type") or match.get("type") or "",
                "origin": item.get("origin") or "",
                "export_status": new_export,
                "previous_export_status": prev_export,
                "export_status_changed": bool(prev_export and new_export and prev_export != new_export),
            })
            assigned_old.add(match["question_id"])
            continue

        stem = item.get("stem_fingerprint") or ""
        # Same normalized question ID, different content: the question is
        # the same slot in the exam, but what it asks changed. That is a
        # change, not a retirement plus a new question. The ID is checked
        # before the stem, so a stem match never steals a different
        # question's slot. This is what makes a rebuild with no real change
        # report everything as same even when the old index used short keys
        # and the new export is scoped.
        id_match = by_id.get(normalize_question_id(item.get("question_id") or "", exam_code))
        if id_match and id_match["question_id"] not in assigned_old:
            results.append({
                "question_id": normalize_question_id(id_match["question_id"], exam_code),
                "incoming_id": item.get("question_id"),
                "fingerprint": fp,
                "stem_fingerprint": stem,
                "status": "changed",
                "type": item.get("type") or id_match.get("type") or "",
                "origin": item.get("origin") or "",
                "export_status": item.get("export_status") or id_match.get("export_status") or "",
                "previous_export_status": id_match.get("export_status") or "",
                "export_status_changed": False,
            })
            assigned_old.add(id_match["question_id"])
            continue

        stem_match = None
        for cand in by_stem.get(stem) or []:
            if cand["question_id"] not in assigned_old:
                stem_match = cand
                break
        if stem_match:
            results.append({
                "question_id": normalize_question_id(stem_match["question_id"], exam_code),
                "incoming_id": item.get("question_id"),
                "fingerprint": fp,
                "stem_fingerprint": stem,
                "status": "changed",
                "type": item.get("type") or stem_match.get("type") or "",
                "origin": item.get("origin") or "",
                "export_status": item.get("export_status") or stem_match.get("export_status") or "",
                "previous_export_status": stem_match.get("export_status") or "",
                "export_status_changed": False,
            })
            assigned_old.add(stem_match["question_id"])
            continue

        new_id = allocate_question_id(item.get("question_id") or "", used_ids, exam_code)
        used_ids.add(new_id)
        results.append({
            "question_id": new_id,
            "incoming_id": item.get("question_id"),
            "fingerprint": fp,
            "stem_fingerprint": stem,
            "status": "new",
            "type": item.get("type") or "",
            "origin": item.get("origin") or "",
            "export_status": item.get("export_status") or "",
        })

    retired = []
    for q in prev_active:
        if q["question_id"] not in assigned_old:
            row = {
                "question_id": normalize_question_id(q["question_id"], exam_code),
                "incoming_id": "",
                "fingerprint": q.get("fingerprint") or "",
                "stem_fingerprint": q.get("stem_fingerprint") or "",
                "status": "retired",
                "type": q.get("type") or "",
                "origin": q.get("origin") or "",
                "export_status": q.get("export_status") or "",
                "retired_at": utc_now(),
            }
            retired.append(row)
            results.append(row)

    # Keep earlier retired rows in the index, unchanged.
    for q in retired_prev:
        results.append({
            "question_id": normalize_question_id(q["question_id"], exam_code),
            "incoming_id": "",
            "fingerprint": q.get("fingerprint") or "",
            "stem_fingerprint": q.get("stem_fingerprint") or "",
            "status": "retired",
            "type": q.get("type") or "",
            "origin": q.get("origin") or "",
            "export_status": q.get("export_status") or "",
            "retired_at": q.get("retired_at") or "",
        })

    counts = {
        "same": sum(1 for r in results if r["status"] == "same"),
        "changed": sum(1 for r in results if r["status"] == "changed"),
        "new": sum(1 for r in results if r["status"] == "new"),
        "retired": sum(1 for r in results if r["status"] == "retired"),
        "duplicate": len(duplicates),
        "export_status_changed": sum(1 for r in results if r.get("export_status_changed")),
        "held": sum(1 for r in results if r.get("status") != "retired" and r.get("export_status") == "held"),
        "exported": sum(1 for r in results if r.get("status") != "retired" and r.get("export_status") == "exported"),
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
                "export_status": r.get("export_status") or "",
                "previous_export_status": r.get("previous_export_status") or "",
                "export_status_changed": bool(r.get("export_status_changed")),
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
        "- export_status_changed: %s" % counts.get("export_status_changed", 0),
        "",
        "| question_id | incoming_id | status | export_status | fingerprint_prefix |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in payload["items"]:
        fp = r.get("fingerprint") or ""
        lines.append("| %s | %s | %s | %s | %s |" % (
            r.get("question_id") or "",
            r.get("incoming_id") or "",
            r.get("status") or "",
            r.get("export_status") or "",
            fp[:12],
        ))
    if payload["duplicates"]:
        lines.extend(["", "Duplicates kept once: %s" % len(payload["duplicates"])])
    path_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_index(path: Path, exam_code: str, result: dict, source_version=None, source_sha256: str = "", extra: dict | None = None) -> None:
    questions = []
    for r in result.get("items") or []:
        questions.append({
            "question_id": r.get("question_id"),
            "fingerprint": r.get("fingerprint") or "",
            "stem_fingerprint": r.get("stem_fingerprint") or "",
            "status": "retired" if r.get("status") == "retired" else "active",
            "last_status": r.get("status"),
            "export_status": r.get("export_status") or "",
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
        "id_source": "extracted",
        "questions": questions,
    }
    if extra:
        payload.update(extra)
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


def process_run(exam_code: str, run_dir: Path, raw_dir: Path | None, reports_dir: Path | None = None, update_run_files: bool = True, reset_index: bool = False, index_extra: dict | None = None) -> dict:
    if not valid_exam_code(exam_code):
        raise SystemExit("Invalid exam code")
    run_dir = Path(run_dir)
    incoming = load_items_from_run(run_dir, exam_code)
    index_path = Path(raw_dir) / "questions-index.json" if raw_dir else run_dir / "questions-index.json"
    previous = [] if reset_index else (load_index(index_path).get("questions") or [])
    result = diff_items(previous, incoming, exam_code)
    version, sha = load_source_meta(raw_dir) if raw_dir else (None, "")
    reports = Path(reports_dir) if reports_dir else (run_dir / "phase-reports")
    if update_run_files:
        write_change_report(reports / "change-report.json", reports / "change-report.md", exam_code, result, version, sha)
        apply_id_mapping(run_dir, exam_code, result)
        write_index(run_dir / "questions-index.json", exam_code, result, version, sha, extra=index_extra)
    if raw_dir:
        write_index(Path(raw_dir) / "questions-index.json", exam_code, result, version, sha, extra=index_extra)
        # Keep a copy of the change report next to the index.
        report_name = ("reseed-change-report" if reset_index else ("v%s-change-report" % (version or "unknown")))
        write_change_report(
            Path(raw_dir) / "changes" / (report_name + ".json"),
            Path(raw_dir) / "changes" / (report_name + ".md"),
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
    ap.add_argument("--reset-index", action="store_true", help="Rebuild the index from incoming extracted IDs, ignoring a previous index")
    args = ap.parse_args(argv)
    result = process_run(args.exam, args.run_dir, args.raw_dir, args.reports_dir, update_run_files=not args.no_update_run_files, reset_index=args.reset_index)
    print(json.dumps({"exam_code": result["exam_code"], **result["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
