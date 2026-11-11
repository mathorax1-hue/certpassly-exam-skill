# Implementation roadmap

## v0.1 — implemented and testable locally

- [x] Skill instructions, agent contract, sanitized AB-900 lessons.
- [x] Core CLI `doctor`, `run`, `status`, `verify-evidence`, `upstream-run`.
- [x] Content-hash SQLite stage checkpoints with downstream invalidation.
- [x] Structural evidence gates for unverified answers and visual safety.
- [x] External pinned upstream adapter (no source redistribution).
- [x] Synthetic unit tests and a public CI workflow.
- [x] Read-only optional MCP server source (runtime integration not yet tested).

## v0.2 — planned, not implemented

- [ ] Build private AB-900 read-only adapter to current `raw-exam` editorial schema.
- [ ] Add actual official-document snapshots with HTTPS fetch, digest validation, option-level matching and source aging.
- [ ] Support image cross-reference reconciliation using PyMuPDF/OpenCV and unmarked-versus-marked screenshot evidence.
- [ ] Add a real import-format compatibility test from the approved site-format version.
- [ ] Add robust package scanning for hidden answer keys in learner payloads.
- [ ] Add full MCP transport tests and a version-pinned dependency lockfile.

## v0.3 — controlled service rollout

- [ ] Add protected private cross-repository reusable workflow with bounded `workflow_dispatch` inputs.
- [ ] Define short-lived GitHub App permissions for raw and ready repos.
- [ ] Add optional Supabase schema, migrations, RLS and private review dashboard.
- [ ] Add usage/time limits, job IDs, idempotency keys, queue monitoring and cost reporting.
- [ ] Deploy a tested controlled MCP endpoint with read-only default and approval requirements.
- [ ] Validate a private end-to-end exam draft through independent review and importer contract before promotion.

Owner choices pending: public repository license, redistribution license for original upstream code, optional cloud database plan, real website importer access, release-review authority.
