# GitHub Actions workflow-control guide

## Four repositories and authorities

- Public `certpassly-exam-skill`: reusable source, docs, synthetic tests and optional read-only MCP.
- Public `exam`: the existing processing adapter, independent evidence code, and synthetic regression suite.
- Private `raw-exam`: original owner PDFs, private research and the *existing* `.github/workflows/process-exams.yml`.
- Private `ready-exams`: independent release evidence verification and approved package storage.

The central skill currently does **not** start private workflows automatically.

## Current commands (operator-controlled)

Check the public skill tests through the repo's `CertPassly Skill CI - synthetic only` workflow. The private processing workflow supports manual `workflow_dispatch` inputs, including `target=one`, `exam_code=AB-900`, and `max_exams=1`.

Example **existing private workflow** invocation, which consumes private Actions minutes:

```bash
gh workflow run process-exams.yml \
  --repo mathorax1-hue/raw-exam \
  -f target=one -f exam_code=AB-900 -f max_exams=1
```

Run it only when current private inputs or evidence changed enough to warrant a complete validation. Use the owner-approved pinned upstream revision. Never trigger full `target=all` processing by default.

## Before a private run

1. Confirm desired exam and source PDF hash.
2. Confirm the private workflow's processor and upstream commit pins.
3. Run local/synthetic tests and independent evidence checks.
4. Check last recorded status and existing private artifacts to avoid duplicate work.
5. Use manual `workflow_dispatch` with one exam and review maximum runtime.
6. Monitor the exact workflow run ID, job logs, artifact digests and status JSON.
7. Do not promote until the release gate establishes independent review and proof.

## CI permissions

`GITHUB_TOKEN` with `contents: write` does **not** automatically permit GitHub App workflow-file changes. Use a properly authorized GitHub account/token or reviewed pull request for workflow edits. Keep synthetic test jobs read-only, and release credentials private.

## Planned future controller

A future allowlisted `certpassly-control` private workflow may expose `exam_code`, `operation`, `resume_failed`, `dry_run`, `max_exams`, and `skill_sha`. This interface is **planned, not deployed**. It should use job IDs, idempotency keys, a per-exam concurrency lock, protected release approval and a no-cost dry-run mode.
