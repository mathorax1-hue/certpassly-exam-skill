#!/usr/bin/env python3
"""Run the local import gate with --grade-all and write counts-only reports."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_site(raw_root: Path, exam: str) -> Path | None:
    runs = raw_root / "exams" / exam / "runs"
    found = []
    if not runs.is_dir():
        return None
    for path in runs.iterdir():
        site = path / ("%s.site-format.v2.json" % exam)
        if path.is_dir() and site.is_file():
            found.append(path)
    if not found:
        return None

    def key(p: Path):
        return (int(p.name) if p.name.isdigit() else -1, p.name)

    run = max(found, key=key)
    return run / ("%s.site-format.v2.json" % exam)


def counts_from_report(data: dict, sha: str, exam: str, run_id: str) -> dict:
    samples = data.get("grading_samples") or []
    graded_ok = 0
    graded_failed = 0
    graded_skipped = 0
    for row in samples:
        if not isinstance(row, dict):
            continue
        if row.get("manual_or_skipped"):
            graded_skipped += 1
            continue
        if row.get("correct_response_accepted") and row.get("wrong_response_rejected"):
            graded_ok += 1
        else:
            graded_failed += 1
    return {
        "exam_code": exam,
        "run_id": run_id,
        "status": data.get("status"),
        "created": data.get("created_count"),
        "draft_count": data.get("draft_count"),
        "held_count": data.get("held_count"),
        "rejected_count": data.get("rejected_count"),
        "graded": len(samples),
        "graded_ok": graded_ok,
        "graded_failed": graded_failed,
        "graded_skipped": graded_skipped,
        "site_file_sha256": sha,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skill-root", required=True, type=Path)
    ap.add_argument("--sandbox", required=True, type=Path)
    ap.add_argument("--raw-root", required=True, type=Path)
    ap.add_argument("--exams", nargs="+", required=True)
    args = ap.parse_args(argv)
    runner = args.skill_root / "scripts" / "run_site_import_gate.py"
    rows = []
    rc = 0
    with tempfile.TemporaryDirectory(prefix="import-check-") as tmp:
        tmp_path = Path(tmp)
        for exam in args.exams:
            site = latest_site(args.raw_root, exam)
            if site is None:
                print("import_check skipped exam=%s reason=no_site_file" % exam)
                rows.append({"exam_code": exam, "status": "skipped", "reason": "no_site_file"})
                rc = 2
                continue
            sha = hashlib.sha256(site.read_bytes()).hexdigest()
            raw_report = tmp_path / ("%s.import-gate.json" % exam)
            result = subprocess.run(
                [sys.executable, str(runner),
                 "--sandbox", str(args.sandbox),
                 "--site-file", str(site),
                 "--output", str(raw_report),
                 "--grade-all"],
                check=False,
            )
            if raw_report.is_file():
                data = json.loads(raw_report.read_text(encoding="utf-8"))
                # Never copy grading samples or question keys into raw-exam.
                row = counts_from_report(data, sha, exam, site.parent.name)
            else:
                row = {"exam_code": exam, "status": "failed", "created": None,
                       "graded_ok": None, "graded_failed": None, "site_file_sha256": sha,
                       "run_id": site.parent.name}
            dest = args.raw_root / "results" / exam / "import-check.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps({**row, "generated_at": utc_now(), "grade_all": True}, indent=2) + "\n", encoding="utf-8")
            print("import_check exam=%s created=%s graded_ok=%s graded_failed=%s status=%s sha256=%s" % (
                exam, row.get("created"), row.get("graded_ok"), row.get("graded_failed"),
                row.get("status"), sha[:16]))
            rows.append(row)
            if result.returncode != 0 and rc == 0:
                rc = result.returncode
    summary = {
        "generated_at": utc_now(),
        "exam_count": len(rows),
        "rows": rows,
    }
    out = args.raw_root / "results" / "import-check-summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("import_check_exam_count=%s" % len(rows))
    return 0 if rc == 0 else rc


if __name__ == "__main__":
    raise SystemExit(main())
