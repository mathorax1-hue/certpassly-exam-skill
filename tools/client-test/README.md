# Client simulator test (local site copy only)

Drives the real exam simulator as a learner with headless Chromium.
Runs only against a throwaway copy whose SANDBOX-SOURCE.txt says "CLIENT TEST COPY",
on sqlite and a local port (never 8330, 3306 or a public host).

1. `reset_and_import.sh <site v2 files...>` copies the sandbox DB and imports through site_import_gate.php.
2. `php setup_client_site.php <site copy>` publishes questions and creates the test learner.
3. `python3 client_simulator_test.py --base http://127.0.0.1:PORT --db <sqlite> --fixture-site <file> --fixture-slug <slug> --session-site <file> --session-slug <slug> --out <dir>`

Per question: render check, interaction (click, select, pointer drag), correct and wrong
submits, UI score totals and per item attempt verdicts. Screenshots in <out>/shots.
The site shares one throttle counter across routes, so the script waits 62 s before submit.
