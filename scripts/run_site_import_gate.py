#!/usr/bin/env python3
"""Wrapper for the real site v2 importer, run only in a throwaway sandbox."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHP_SCRIPT = HERE / "site_import_gate.php"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sandbox", required=True, type=Path)
    ap.add_argument("--site-file", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--php", default="php")
    ap.add_argument("--grade-all", action="store_true")
    args = ap.parse_args(argv)
    if not args.sandbox.is_dir():
        print("ERROR: sandbox not found", file=sys.stderr)
        return 2
    if not (args.sandbox / "artisan").is_file():
        print("ERROR: sandbox is not a Laravel app", file=sys.stderr)
        return 2
    if not args.site_file.is_file():
        print("ERROR: site file not found", file=sys.stderr)
        return 2
    php = args.php if Path(args.php).exists() or shutil.which(args.php) else None
    if not php:
        print("ERROR: php is not installed", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [php, str(PHP_SCRIPT), f"--sandbox={args.sandbox}", f"--file={args.site_file}", f"--report={args.output}"]
    if args.grade_all:
        cmd.append("--grade-all")
    result = subprocess.run(cmd, check=False)
    if args.output.is_file():
        data = json.loads(args.output.read_text(encoding="utf-8"))
        sha = hashlib.sha256(args.site_file.read_bytes()).hexdigest()
        data["site_file"] = str(args.site_file)
        data["site_file_sha256"] = sha
        data["site_file_bytes"] = args.site_file.stat().st_size
        args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        samples = data.get("grading_samples") or []
        graded_ok = sum(1 for s in samples if isinstance(s, dict) and s.get("correct_response_accepted") and s.get("wrong_response_rejected"))
        graded_failed = sum(1 for s in samples if isinstance(s, dict) and not (s.get("correct_response_accepted") and s.get("wrong_response_rejected")) and not s.get("manual_or_skipped"))
        print(json.dumps({
            "status": data.get("status"),
            "exam_code": data.get("exam_code"),
            "created_count": data.get("created_count"),
            "draft_count": data.get("draft_count"),
            "rejected_count": data.get("rejected_count"),
            "held_count": data.get("held_count"),
            "graded": len(samples),
            "graded_ok": graded_ok,
            "graded_failed": graded_failed,
            "site_file_sha256": sha,
        }))
    return 0 if result.returncode == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
