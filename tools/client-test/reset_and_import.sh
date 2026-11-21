#!/usr/bin/env bash
# Rebuild the throwaway client-test site DB from the import sandbox and import
# the site v2 files through the skill's import gate. Local sqlite copy only.
set -euo pipefail
SITE=${SITE:-/workspace/client-site}
SRC=${SRC:-/workspace/import-sandbox/database/sandbox.sqlite}
GATE=${GATE:-/workspace/qtypes/skill/scripts/site_import_gate.php}
OUT=$(cd "$(dirname "$0")" && pwd)
grep -q "CLIENT TEST COPY" "$SITE/SANDBOX-SOURCE.txt" || { echo "refusing: $SITE is not the client test copy"; exit 1; }
cp "$SRC" "$SITE/database/sandbox.sqlite"
python3 - "$SITE/database/sandbox.sqlite" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
ids = [r[0] for r in c.execute("select id from questions where question_key glob 'q[0-9]*'")]
tabs = [r[0] for r in c.execute("select name from sqlite_master where type='table'")]
for t in tabs:
    cols = [r[1] for r in c.execute('pragma table_info(%s)' % t)]
    if 'question_id' not in cols or t == 'questions':
        continue
    c.executemany('delete from %s where question_id = ?' % t, [(i,) for i in ids])
c.executemany('delete from questions where id = ?', [(i,) for i in ids])
c.commit()
print('removed old pdf-keyed questions:', len(ids))
PY
for f in "$@"; do
  code=$(basename "$f" .site-format.v2.json)
  php "$GATE" --sandbox="$SITE" --file="$f" --report="$OUT/import-$code.json" --grade-all | tail -1
done
