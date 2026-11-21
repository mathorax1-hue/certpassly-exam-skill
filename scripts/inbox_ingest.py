#!/usr/bin/env python3
"""Ingest PDFs from raw-exam inbox/<EXAM-CODE>/ into exams/<CODE>/sources.json.

Each PDF is hashed. A duplicate sha256 is skipped. A new exam code creates
exams/<CODE>/. An existing code with a new file becomes a new version.
Versions are kept and never deleted. Stdout is counts only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from question_fingerprint import EXAM_CODE_RE, utc_now, valid_exam_code  # noqa: E402

PDF_RX = re.compile(r"\.pdf$", re.I)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def safe_filename(name: str) -> str:
    base = os.path.basename(name or "")
    base = base.replace(chr(92), "_").replace("/", "_")
    base = "".join(ch for ch in base if ord(ch) >= 32 and ch != chr(127)).strip(" .")
    if not base.lower().endswith(".pdf"):
        base = (base or "source") + ".pdf"
    return base[:180]


def load_sources(path: Path, exam_code: str) -> dict:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            data.setdefault("exam_code", exam_code)
            data.setdefault("sources", [])
            return data
    return {"exam_code": exam_code, "current_version": 0, "sources": [], "skipped_duplicates": []}


def known_hashes(data: dict) -> dict[str, int]:
    out = {}
    for row in data.get("sources") or []:
        sha = row.get("sha256")
        if sha:
            out[sha] = row.get("version") or 0
    return out


def next_version(data: dict) -> int:
    versions = [int(row.get("version") or 0) for row in data.get("sources") or []]
    return (max(versions) if versions else 0) + 1


def write_sources(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")



def move_ingested(src: Path) -> None:
    dest_dir = src.parent / "ingested"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        n = 2
        while dest.exists():
            dest = dest_dir / ("%s-%s%s" % (stem, n, suffix))
            n += 1
    src.rename(dest)


def copy_version(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def activate_current_source(exam_dir: Path, stored: Path, filename: str) -> None:
    source_dir = exam_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    # Replace current PDF copies with this version only (history stays in source-versions/).
    for old in source_dir.glob("*.pdf"):
        try:
            old.unlink()
        except OSError:
            pass
    copy_version(stored, source_dir / safe_filename(filename))


def ensure_manifest(exam_dir: Path, exam_code: str) -> None:
    path = exam_dir / "manifest.json"
    if path.is_file():
        return
    payload = {
        "exam_code": exam_code,
        "source_kind": "inbox",
        "note": "Created by inbox ingest. Fill official facts before promotion.",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def add_version(exam_dir: Path, data: dict, src: Path, sha: str, created: bool, activate: bool = True) -> dict:
    version = next_version(data)
    filename = safe_filename(src.name)
    stored = exam_dir / "source-versions" / ("v%s" % version) / filename
    copy_version(src, stored)
    for row in data.get("sources") or []:
        if row.get("status") == "active":
            row["status"] = "superseded"
    try:
        stored_path = str(stored.relative_to(exam_dir.parent.parent if exam_dir.parent.name == "exams" else exam_dir))
    except ValueError:
        stored_path = str(stored)
    row = {
        "version": version,
        "sha256": sha,
        "filename": filename,
        "bytes": src.stat().st_size,
        "stored_path": stored_path,
        "ingested_at": utc_now(),
        "status": "active",
    }
    data.setdefault("sources", []).append(row)
    data["current_version"] = version
    data["updated_at"] = utc_now()
    if created and not data.get("created_at"):
        data["created_at"] = data["updated_at"]
    write_sources(exam_dir / "sources.json", data)
    if activate:
        activate_current_source(exam_dir, stored, filename)
    ensure_manifest(exam_dir, data.get("exam_code") or exam_dir.name)
    return {"action": "new_exam" if created else "update", "version": version, "sha256": sha}


def ingest_inbox(raw_root: Path, inbox_root: Path | None = None) -> dict:
    raw_root = Path(raw_root)
    inbox_root = Path(inbox_root) if inbox_root else raw_root / "inbox"
    summary = {
        "new_exams": 0,
        "updates": 0,
        "skipped_duplicate": 0,
        "skipped_invalid": 0,
        "pdfs_seen": 0,
        "actions": [],
    }
    if not inbox_root.is_dir():
        return summary
    for entry in sorted(inbox_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        code = entry.name
        if not valid_exam_code(code):
            summary["skipped_invalid"] += 1
            continue
        exam_dir = raw_root / "exams" / code
        sources_path = exam_dir / "sources.json"
        existed = exam_dir.is_dir() and sources_path.is_file()
        data = load_sources(sources_path, code) if existed else load_sources(sources_path, code)
        known = known_hashes(data)
        for pdf in sorted(p for p in entry.iterdir() if p.is_file() and PDF_RX.search(p.name)):
            if pdf.name.startswith("."):
                continue
            # Do not ingest files already moved under ingested/.
            summary["pdfs_seen"] += 1
            sha = sha256_file(pdf)
            if sha in known:
                if sources_path.is_file() or data.get("sources"):
                    data.setdefault("skipped_duplicates", []).append({
                        "sha256": sha,
                        "skipped_at": utc_now(),
                    })
                    write_sources(sources_path, data)
                summary["skipped_duplicate"] += 1
                summary["actions"].append({"exam_code": code, "action": "skip_duplicate"})
                move_ingested(pdf)
                continue
            created = not bool(data.get("sources"))
            exam_dir.mkdir(parents=True, exist_ok=True)
            info = add_version(exam_dir, data, pdf, sha, created)
            known[sha] = info["version"]
            data = load_sources(exam_dir / "sources.json", code)
            if created:
                summary["new_exams"] += 1
            else:
                summary["updates"] += 1
            summary["actions"].append({"exam_code": code, "action": info["action"], "version": info["version"]})
            existed = True
            move_ingested(pdf)
    return summary


def register_existing_sources(raw_root: Path, exam_codes: list[str] | None = None) -> dict:
    """Record exams/*/source/*.pdf in sources.json when they are not yet listed."""
    raw_root = Path(raw_root)
    exams = raw_root / "exams"
    summary = {"registered": 0, "skipped_duplicate": 0, "exams": 0}
    if not exams.is_dir():
        return summary
    wanted = set(exam_codes) if exam_codes else None
    for exam_dir in sorted(p for p in exams.iterdir() if p.is_dir() and valid_exam_code(p.name)):
        if wanted is not None and exam_dir.name not in wanted:
            continue
        source_dir = exam_dir / "source"
        if not source_dir.is_dir():
            continue
        pdfs = sorted(p for p in source_dir.iterdir() if p.is_file() and PDF_RX.search(p.name))
        if not pdfs:
            continue
        summary["exams"] += 1
        data = load_sources(exam_dir / "sources.json", exam_dir.name)
        known = known_hashes(data)
        for pdf in pdfs:
            sha = sha256_file(pdf)
            if sha in known:
                summary["skipped_duplicate"] += 1
                continue
            add_version(exam_dir, data, pdf, sha, created=not bool(data.get("sources")), activate=False)
            data = load_sources(exam_dir / "sources.json", exam_dir.name)
            known = known_hashes(data)
            summary["registered"] += 1
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-root", required=True, type=Path)
    ap.add_argument("--inbox-root", type=Path)
    ap.add_argument("--register-existing-sources", action="store_true")
    ap.add_argument("--exam", action="append", dest="exams")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args(argv)
    report = {"generated_at": utc_now()}
    if args.register_existing_sources:
        report["register"] = register_existing_sources(args.raw_root, args.exams)
    report["inbox"] = ingest_inbox(args.raw_root, args.inbox_root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    inbox = report["inbox"]
    reg = report.get("register") or {}
    print("inbox_pdfs_seen=%s new_exams=%s updates=%s skipped_duplicate=%s skipped_invalid=%s registered_existing=%s" % (
        inbox.get("pdfs_seen", 0), inbox.get("new_exams", 0), inbox.get("updates", 0),
        inbox.get("skipped_duplicate", 0), inbox.get("skipped_invalid", 0),
        reg.get("registered", 0),
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
