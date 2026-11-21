#!/usr/bin/env bash
# Run the local site-import sandbox with --grade-all on raw-exam site files.
# Writes counts-only JSON into raw-exam. Never copies site application code.
# Refuses to run if the sandbox is not sqlite (no MariaDB 3306, no 8330, no production).
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SANDBOX="${IMPORT_SANDBOX:-/workspace/import-sandbox}"
RAW_ROOT="${RAW_EXAM_ROOT:-}"
EXAMS="${IMPORT_EXAMS:-}"

usage() {
  echo "Usage: RAW_EXAM_ROOT=/path/to/raw-exam $0 [EXAM_CODE ...]"
  echo "Optional: IMPORT_SANDBOX=/workspace/import-sandbox"
}

if [ ! -d "$SANDBOX" ] || [ ! -f "$SANDBOX/artisan" ]; then
  echo "ERROR: sandbox is not a Laravel app: $SANDBOX" >&2
  exit 2
fi
if [ ! -f "$SANDBOX/.env" ]; then
  echo "ERROR: sandbox .env missing" >&2
  exit 2
fi
# Refuse anything other than sqlite. Do not print secret values.
if ! grep -q '^DB_CONNECTION=sqlite$' "$SANDBOX/.env"; then
  echo "ERROR: sandbox DB_CONNECTION must be sqlite" >&2
  exit 2
fi
if grep -Eq '3306|DB_HOST=.+' "$SANDBOX/.env" && ! grep -q '^DB_CONNECTION=sqlite$' "$SANDBOX/.env"; then
  echo "ERROR: sandbox must not use a network database" >&2
  exit 2
fi

if [ -z "$RAW_ROOT" ]; then
  echo "ERROR: set RAW_EXAM_ROOT" >&2
  usage >&2
  exit 2
fi
if [ ! -d "$RAW_ROOT" ]; then
  echo "ERROR: raw-exam root not found" >&2
  exit 2
fi

if [ "$#" -gt 0 ]; then
  CODES=("$@")
else
  mapfile -t CODES < <(python3 - "$RAW_ROOT" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1]) / "exams"
if not root.is_dir():
    sys.exit(0)
for exam in sorted(p for p in root.iterdir() if p.is_dir()):
    runs = exam / "runs"
    if not runs.is_dir():
        continue
    for run in runs.iterdir():
        if run.is_dir() and (run / ("%s.site-format.v2.json" % exam.name)).is_file():
            print(exam.name)
            break
PY
)
fi

if [ "${#CODES[@]}" -eq 0 ]; then
  echo "ERROR: no exams with a site file" >&2
  exit 2
fi

python3 "$SKILL_ROOT/tools/import-check/write_import_check.py" \
  --skill-root "$SKILL_ROOT" \
  --sandbox "$SANDBOX" \
  --raw-root "$RAW_ROOT" \
  --exams "${CODES[@]}"
