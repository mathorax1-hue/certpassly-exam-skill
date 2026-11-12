# Implementation roadmap

## v0.1 — implemented and testable locally

- [x] Skill instructions, agent contract, sanitized AB-900 lessons.
- [x] Core CLI `doctor`, `run`, `status`, `verify-evidence`, `upstream-run`.
- [x] Content-hash SQLite stage checkpoints with downstream invalidation.
- [x] Structural evidence gates for unverified answers and visual safety.
- [x] External pinned upstream adapter (no source redistribution).
- [x] Synthetic unit tests and a public CI workflow.
- [x] Read-only optional MCP server source (runtime integration not yet tested).

## 2026-11-12: reusable code integration completed (not release readiness)

- [x] Migrate and test a fail-closed private review-ledger preflight (`scripts/audit_question_evidence.py`).
- [x] Migrate and test a nested artifact-to-directory unpacker (`scripts/unpack_artifact_tree.py`).
- [x] Document canonical scripts/handovers in `docs/AI-SESSION-RECOVERY.md` with public/private boundaries.
- [x] Implement a bounded official-page capture helper with allowlisted HTTPS, SHA-256 and verified quote occurrence (provenance, not answer correctness).
- [x] Add offline saved-page receipt verifier; detect hash tampering, quote changes, forged path traversal and unverified origin.
- [x] Implement per-option source-field evidence preflight and matrix/dropdown row order checks.
- [x] Implement active vs superseded original visual role reconciliation (metadata, not pixel proof).
- [x] Register every shared tool in config/tool-registry.json and enforce it in public CI.
- [x] Add dependency guidance, four-repo playbook, centralized failure/pass history, and AI recovery instructions.
- [ ] Verify live option correctness against captured official documents and original PDF in the private workspace; preserve human signoff gates.
- [ ] Review and explicitly update private runtime pins only when the integrated skill is compatible and tested.

## v0.2 — planned beyond these helpers

- [ ] Build private AB-900 read-only adapter to current `raw-exam` editorial schema.
- [ ] Complete source-content-to-per-option authenticity checks, proof-quote archival, source aging, and independent key adjudication in private; capture helper is available but production verification is incomplete.
- [ ] Implement real PDF/pixel image alignment with PyMuPDF/OpenCV and semantic screenshot answer review; metadata reconciliation exists.
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
