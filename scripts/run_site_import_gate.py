#!/usr/bin/env python3
"""Wrapper for the real site v2 importer, run only in a throwaway sandbox."""
from __future__ import annotations

import argparse
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
    result = subprocess.run(
        [php, str(PHP_SCRIPT), f"--sandbox={args.sandbox}", f"--file={args.site_file}", f"--report={args.output}"],
        check=False,
    )
    if args.output.is_file():
        data = json.loads(args.output.read_text(encoding="utf-8"))
        print(json.dumps({
            "status": data.get("status"),
            "exam_code": data.get("exam_code"),
            "created_count": data.get("created_count"),
            "draft_count": data.get("draft_count"),
            "rejected_count": data.get("rejected_count"),
            "held_count": data.get("held_count"),
        }))
    return 0 if result.returncode == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
