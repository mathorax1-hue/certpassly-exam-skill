#!/usr/bin/env python3
"""Guardrail for accidental publication of owner exams, archives, or keys."""
from __future__ import annotations

import subprocess
from pathlib import Path

BAD_EXTENSIONS = {".pdf", ".zip", ".vce", ".7z", ".sqlite", ".sqlite3", ".pem", ".p12", ".key"}
BAD_NAMES = {".env", "service-account.json"}
BAD_PARTS = {"raw-exam", "ready-exams", ".certpassly", "private"}


def main() -> int:
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    invalid = []
    for name in result.stdout.splitlines():
        p = Path(name)
        if p.suffix.lower() in BAD_EXTENSIONS or p.name in BAD_NAMES or BAD_PARTS.intersection(p.parts):
            invalid.append(name)
    if invalid:
        print("FAIL: forbidden files tracked in public repository:")
        print("\n".join(invalid))
        return 1
    print("PASS: tracked public file paths contain no prohibited exam artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
