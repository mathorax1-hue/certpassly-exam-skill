# Operations and failure recovery

## Preflight

1. Read `AGENTS.md` and `SKILL.md`.
2. Confirm the target exam, source version, and private repository rights.
3. Run `certpassly doctor` and ensure dependencies for the selected stage are available.
4. Use `PYTHONPATH=src python -m unittest discover -s tests -v` before any shared code commit.
5. Check upstream full commit SHA in `config/repositories.json` before running it.

## Run synthetic checkpoint demo

```bash
PYTHONPATH=src python -m certpassly.cli run --plan config/pipeline.example.json
PYTHONPATH=src python -m certpassly.cli status
PYTHONPATH=src python -m certpassly.cli run --plan config/pipeline.example.json
```

The first run generates **synthetic** normalized data and a blocker report in ignored `work/demo/`. The second run should print `cached` for both stages. Edit the fixture and rerun to invalidate the checkpoint. State is in ignored `.certpassly/checkpoints.sqlite3`; error logs are in `.certpassly/logs/`.

## Run an existing upstream stage

```bash
bash scripts/bootstrap_upstream.sh
certpassly upstream-run --checkout vendor/certpassly-exam-pipeline \
  --private-root /private/owner-workspace --exam AB-900 --stage validate --dry-run
```

Remove `--dry-run` only after reviewing private source inputs and command scope. The adapter checks the upstream HEAD SHA and defaults to `--offline`. Add `--online` only when official page refresh is necessary and approved.

## What to do when a stage fails

1. Inspect the local failed stage and its ignored `.certpassly/logs/<stage>.log`.
2. Identify the exact failure, not a guessed category.
3. Fix only the input or module causing it. Add a synthetic regression test.
4. Rerun the plan; matching passed stages are reused. A changed command, dependency, input or output invalidates caching.
5. If source evidence is missing, keep the item blocked. Do not manufacture a quote, SHA, timestamp or human approval.

## Evidence audit

`certpassly verify-evidence --input PRIVATE_JSON --output PRIVATE_REPORT --strict`

Accepted synthetic input shape: `exam_code`, `official_domains`, `questions` and `media`. A question contains `id`, `correct_answer`, `accuracy_status`, `human_review_required`, and `evidence` entries (`url`, `saved_page_sha256`, `verbatim_quote`, `supports_correct_answer`). Media contain role, `answer_verified`, `approved_for_release`, and learner-exposure flags.

The checker is intentionally structural. It does not fetch or verify the saved source material. A passing structural report is called `evidence_ready_for_independent_gate`—**never** `released`. Protected private release workflows must separately verify source integrity, human review, import conformance and artifact digests.

## Operator handoff

Report exact tested commit, exam code, stage statuses, failing question IDs, saved evidence pointers, and pending human approvals. Never claim a live website was tested unless it actually was.
