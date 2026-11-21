#!/usr/bin/env python3
"""Seed sources.json and a hash-only questions-index.json from an existing raw-exam run.

Does not print question text. Does not delete prior versions or retired IDs
unless --reseed is set, which rebuilds IDs from extracted file stems.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from inbox_ingest import register_existing_sources  # noqa: E402
from question_fingerprint import process_run, valid_exam_code, utc_now  # noqa: E402


def latest_run_dir(exam_dir: Path, exam_code: str) -> Path | None:
    runs = exam_dir / "runs"
    if not runs.is_dir():
        return None
    found = []
    for path in runs.iterdir():
        if not path.is_dir():
            continue
        site = path / ("%s.site-format.v2.json" % exam_code)
        extracted = path / "extracted" / "items"
        if site.is_file() or extracted.is_dir():
            found.append(path)
    if not found:
        return None

    def key(p: Path):
        name = p.name
        return (int(name) if name.isdigit() else -1, name)

    return max(found, key=key)


def resolve_run_dir(exam_dir: Path, exam_code: str, run_id: str | None) -> Path | None:
    if run_id:
        path = exam_dir / "runs" / run_id
        return path if path.is_dir() else None
    return latest_run_dir(exam_dir, exam_code)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-root", required=True, type=Path)
    ap.add_argument("--exam", action="append", dest="exams")
    ap.add_argument("--register-sources", action="store_true")
    ap.add_argument("--run-id", help="Use this run folder instead of the latest")
    ap.add_argument("--reseed", action="store_true", help="Rebuild the index from extracted IDs, ignoring a previous shifted index")
    ap.add_argument("--note", default="", help="Optional counts-only note stored on the index")
    args = ap.parse_args(argv)
    raw = args.raw_root
    if args.register_sources:
        report = register_existing_sources(raw, args.exams)
        print("registered_existing=%s skipped_duplicate=%s exams_with_source=%s" % (
            report.get("registered", 0), report.get("skipped_duplicate", 0), report.get("exams", 0)))
    codes = list(args.exams or [])
    if not codes:
        return 0
    seeded = 0
    for code in codes:
        if not valid_exam_code(code):
            print("skipped_invalid=1")
            continue
        exam_dir = raw / "exams" / code
        run_dir = resolve_run_dir(exam_dir, code, args.run_id)
        if run_dir is None:
            print("index_seed_skipped exam_present=%s reason=no_run" % int(exam_dir.is_dir()))
            continue
        extra = None
        if args.reseed:
            extra = {
                "reseed": {
                    "at": utc_now(),
                    "from_run": run_dir.name,
                    "id_source": "extracted",
                    "note": args.note or "Rebuilt from extracted PDF keys, including held items.",
                }
            }
        result = process_run(
            code, run_dir, exam_dir,
            update_run_files=False,
            reset_index=args.reseed,
            index_extra=extra,
        )
        counts = result.get("counts") or {}
        print("index_seeded exam_ok incoming=%s same=%s new=%s changed=%s retired=%s held=%s exported=%s reseed=%s" % (
            counts.get("incoming", 0), counts.get("same", 0), counts.get("new", 0),
            counts.get("changed", 0), counts.get("retired", 0),
            counts.get("held", 0), counts.get("exported", 0), int(args.reseed)))
        seeded += 1
    print("index_seeded_count=%s" % seeded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
