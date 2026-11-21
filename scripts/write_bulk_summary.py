#!/usr/bin/env python3
"""Build a counts-only bulk run summary table from per-exam public summaries."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from question_fingerprint import valid_exam_code  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def row_for_exam(raw_root: Path, exam_code: str, run_id: str) -> dict:
    run_dir = Path(raw_root) / "exams" / exam_code / "runs" / str(run_id)
    public = load_json(run_dir / "phase-reports" / "public-summary.json")
    change = load_json(run_dir / "phase-reports" / "change-report.json")
    counts = change.get("counts") or {}
    failed = not public
    return {
        "exam_code": exam_code,
        "failed": failed,
        "exported": public.get("exported_question_count") if not failed else None,
        "held": public.get("held_count") if not failed else None,
        "same": counts.get("same"),
        "changed": counts.get("changed"),
        "new": counts.get("new"),
        "retired": counts.get("retired"),
        "duplicate": counts.get("duplicate"),
        "promotion": public.get("promotion") if not failed else "failed",
    }


def write_summary(path_json: Path, path_md: Path, rows: list[dict], run_id: str) -> dict:
    payload = {
        "run_id": run_id,
        "generated_at": utc_now(),
        "exam_count": len(rows),
        "failed_count": sum(1 for r in rows if r.get("failed")),
        "rows": rows,
    }
    path_json.parent.mkdir(parents=True, exist_ok=True)
    path_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Bulk exam summary",
        "",
        "Run %s at %s" % (run_id, payload["generated_at"]),
        "",
        "| exam_code | exported | held | failed | same | changed | new | retired |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    def cell(v):
        return "" if v is None else v
    for r in rows:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r.get("exam_code") or "",
            cell(r.get("exported")),
            cell(r.get("held")),
            "yes" if r.get("failed") else "no",
            cell(r.get("same")),
            cell(r.get("changed")),
            cell(r.get("new")),
            cell(r.get("retired")),
        ))
    path_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-root", required=True, type=Path)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--exam-codes", required=True, help="JSON array of exam codes")
    ap.add_argument("--output-dir", required=True, type=Path)
    args = ap.parse_args(argv)
    try:
        codes = json.loads(args.exam_codes)
    except json.JSONDecodeError:
        codes = [c.strip() for c in args.exam_codes.split(",") if c.strip()]
    if not isinstance(codes, list):
        raise SystemExit("exam-codes must be a JSON array")
    rows = []
    for code in codes:
        if not valid_exam_code(str(code)):
            continue
        rows.append(row_for_exam(args.raw_root, str(code), args.run_id))
    payload = write_summary(args.output_dir / "summary.json", args.output_dir / "summary.md", rows, args.run_id)
    print("bulk_exam_count=%s failed_count=%s" % (payload["exam_count"], payload["failed_count"]))
    # Reprint the table (counts and IDs only).
    print((args.output_dir / "summary.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
