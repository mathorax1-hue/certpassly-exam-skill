#!/usr/bin/env python3
"""List exams for a bulk technical run. Prints a JSON array of exam codes only."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from question_fingerprint import valid_exam_code  # noqa: E402
from inbox_ingest import load_sources, sha256_file, PDF_RX  # noqa: E402


def current_source_sha(exam_dir: Path) -> str:
    data = load_sources(exam_dir / "sources.json", exam_dir.name)
    current = data.get("current_version")
    for row in data.get("sources") or []:
        if row.get("version") == current or row.get("status") == "active":
            return row.get("sha256") or ""
    return ""


def index_source_sha(exam_dir: Path) -> str:
    path = exam_dir / "questions-index.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return (data or {}).get("source_sha256") or ""


def has_source_pdf(exam_dir: Path) -> bool:
    source = exam_dir / "source"
    if not source.is_dir():
        return False
    return any(p.is_file() and PDF_RX.search(p.name) for p in source.iterdir())


def parse_selection(raw: str) -> tuple[str, list[str]]:
    text = (raw or "new").strip()
    if not text or text.lower() == "new":
        return "new", []
    if text.lower() == "all":
        return "all", []
    codes = []
    for part in text.replace(";", ",").split(","):
        code = part.strip()
        if not code:
            continue
        if not valid_exam_code(code):
            raise SystemExit("Invalid exam code")
        if code not in codes:
            codes.append(code)
    if not codes:
        raise SystemExit("No exam codes in the list")
    return "list", codes


def list_exams(raw_root: Path, selection: str, ingest_actions: list[dict] | None = None) -> list[str]:
    raw_root = Path(raw_root)
    exams = raw_root / "exams"
    mode, listed = parse_selection(selection)
    if mode == "list":
        return listed
    if not exams.is_dir():
        return []
    codes = []
    touched = set()
    for act in ingest_actions or []:
        if act.get("action") in ("new_exam", "update") and act.get("exam_code"):
            touched.add(act["exam_code"])
    for exam_dir in sorted(p for p in exams.iterdir() if p.is_dir() and valid_exam_code(p.name)):
        if not has_source_pdf(exam_dir):
            continue
        code = exam_dir.name
        if mode == "all":
            codes.append(code)
            continue
        # new: inbox new/update, no index, or source sha differs from the index.
        if code in touched:
            codes.append(code)
            continue
        if not (exam_dir / "questions-index.json").is_file():
            codes.append(code)
            continue
        src = current_source_sha(exam_dir)
        idx = index_source_sha(exam_dir)
        if src and idx and src != idx:
            codes.append(code)
    return codes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-root", required=True, type=Path)
    ap.add_argument("--selection", default="new")
    ap.add_argument("--ingest-report", type=Path)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args(argv)
    actions = []
    if args.ingest_report and args.ingest_report.is_file():
        try:
            report = json.loads(args.ingest_report.read_text(encoding="utf-8"))
            actions = ((report.get("inbox") or {}).get("actions") or [])
        except (OSError, json.JSONDecodeError):
            actions = []
    codes = list_exams(args.raw_root, args.selection, actions)
    text = json.dumps(codes, separators=(",", ":"))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"exam_codes": codes, "count": len(codes)}, indent=2) + "\n", encoding="utf-8")
    print(text)
    print("exam_count=%s" % len(codes), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
