# GitHub Actions lessons: first public skill bootstrap

## Observed failure (2026-11-12)

The first public bootstrap workflow passed all 27 synthetic tests and the tracked-file safety check, then failed to push its source commit:

`remote rejected: refusing to allow a GitHub App to create or update workflow .github/workflows/ci.yml without workflows permission`

This is **a workflow-writing credential-scope failure**, not a failed exam pipeline or Python test.

Reference: https://github.com/mathorax1-hue/certpassly-exam-skill/actions/runs/43087739001

## Fix that passed

1. Limit the workflow runner's commit to ordinary source files. Do **not** let an Actions job modify `.github/workflows/*.yml` without an explicitly authorized workflow-writing credential.
2. Add the permanent `.github/workflows/ci.yml` via the connected GitHub account, using normal reviewed repository file operations.
3. Remove the one-time bootstrap workflow using the same authorized integration.
4. Re-run synthetic CI on the final commit and verify `success`.

Successful bootstrap: https://github.com/mathorax1-hue/certpassly-exam-skill/actions/runs/43088041687

Passing public CI: https://github.com/mathorax1-hue/certpassly-exam-skill/actions/runs/43088200619

## Permanent prevention

- Treat workflow-file mutations as a separately permissioned operation from source-file commits.
- Keep normal CI as `contents: read`; do not grant `workflows` or repository write scope simply to run tests.
- Avoid self-modifying release workflows.
- Test synthetic changes publicly before requesting a bounded private exam run.
- On a failed GitHub run inspect the **failing step and logs**, not just the top-level red status; preserve verified passing tests.
- Keep deployment/release approval in a protected private repo environment, never in self-generated JSON.
