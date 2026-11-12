# CertPassly canonical skill: session recovery and reusable-tool index

**Canonical reusable skill:** https://github.com/mathorax1-hue/certpassly-exam-skill

**Purpose:** Future AI sessions can reconstruct the operating rules, proven scripts, dependencies, known failures, and exact next steps without relying on a prior chat. Reading this repository restores documented project context; it does not train model weights, grant GitHub permissions or certify answers.

## Resume sequence (every new session)

1. Read `AGENTS.md`, `SKILL.md`, `README.md`, `docs/OPERATIONS.md`, `docs/WORKFLOW-CONTROL.md`, `docs/TOOL-HUB.md`, `docs/DEPENDENCIES.md`, `docs/INTEGRATION-PLAYBOOK.md`, this file, `knowledge/AB900-LESSONS.md` and `knowledge/ENGINEERING-HISTORY.md`.
2. Read `config/repositories.json` and identify the actual **pinned** source revisions used by the private workflow; do not assume this repository's main branch is deployed automatically.
3. For exam-specific progress, read **PRIVATE** `mathorax1-hue/raw-exam/docs/AI-SESSION-HANDOVER.md` and then the live evidence ledger and review checklist under `exams/AB-900/`. Authorized private access is required. Do not copy private content into this public repository.
4. Compare current GitHub commits, relevant Actions runs, and protected release-gate results. Treat dated summaries as snapshots, not present truth.
5. Resume the first unfinished task. After a tested change: commit generic fixes here with synthetic tests; record private review/answer evidence only in `raw-exam`. Append observed failures and verified recovery steps to `knowledge/`.
6. Never assume answer accuracy, human approvals, a ready-exams release, or website publication from completed code tests or a past AI claim.

## Four repository roles

| Role | Repository | Content allowed |
| --- | --- | --- |
| Canonical skill, tested utilities, deps, playbooks | **PUBLIC** `mathorax1-hue/certpassly-exam-skill` | Generic source code, synthetic fixtures, public sanitized learning |
| Existing processor / release-evidence generator | **PUBLIC** `mathorax1-hue/exam` | Source-independent processing code and synthetic CI |
| Source of truth for exams and working evidence | **PRIVATE** `mathorax1-hue/raw-exam` | Original PDF, question images, keys, authoring JSON, official source snapshots, per-question ledgers and handover |
| Destination for independently accepted drafts | **PRIVATE** `mathorax1-hue/ready-exams` | Only approved proof-backed release packages |

The older public `msaqlainhaneef1/certpassly-exam-pipeline` remains a **pinned, external compatibility dependency** for its established processing stages where the private workflow still invokes it. It is no longer the requested repository for new skills, lessons, or scripts. Do not copy its code into this repository without appropriate reuse rights. A central skill repo is not automatically the runtime used by existing private GitHub Actions; every approved pin change needs an explicit test and audited commit.

## Reusable tool registry

**Authoritative machine-readable registry:** `config/tool-registry.json` (check with `python scripts/verify_tool_registry.py`). **Full command and JSON schema guide:** `docs/TOOL-HUB.md`. The quick table below is introductory only and does not replace the registry.

| Tool | Purpose | Invocation | Dependencies | Provenance |
| --- | --- | --- | --- | --- |
| `src/certpassly/cli.py` | Resumable plan, doctor, checkpoint report and structural evidence preflight | `PYTHONPATH=src python -m certpassly.cli --help` | Python 3.11 standard library for core | Original local skill |
| `scripts/audit_question_evidence.py` | Read-only audit of **private active review-ledger schema**; AI support is NOT release approval | `python scripts/audit_question_evidence.py PRIVATE/active-question-review-ledger.json --output PRIVATE/preflight.json` | Python standard library | Ported from public `exam`, SHA `e48bd01a2995d779db4490c210e280261f7cc439` |
| `scripts/unpack_artifact_tree.py` | Expand existing pipeline artifacts into browsable folders and SHA-256 file manifest, reject unsafe archive members | `python scripts/unpack_artifact_tree.py PRIVATE/artifact.zip PRIVATE/research-archive` | Python standard library | Ported from public `exam`, SHA `6fbda285db37b826ce1a74f66e1af7caf7d8009d` |
| `scripts/check_public_safety.py` | Scan committed tree for accidental private artifacts or token patterns | `python scripts/check_public_safety.py` | Python standard library | Original local skill |
| `scripts/bootstrap_upstream.sh` | Fetch full-hash-pinned external upstream in ignored directory | `bash scripts/bootstrap_upstream.sh` | git, bash, network access | Original local skill |

Run all regression tests with `PYTHONPATH=src python -m unittest discover -s tests -v`, then confirm public GitHub Actions CI on the exact commit. The migrated scripts' tests are `tests/test_audit_question_evidence.py` and `tests/test_unpack_artifact_tree.py`. All fixtures must be synthetic.

## Quality and release gates (do not collapse them)

1. Extract question and choices from immutable original source (private).
2. Compare images against original PDF; preserve matrix/dropdown row order and distinguish question vs answer references.
3. For each option, save official Microsoft/vendor URL, short verbatim supporting quote, retrieval time and SHA-256 content where accessible. Flag missing support rather than guessing.
4. Document an AI-supported crosscheck separately from a corrected key, independently approved answer or reviewer attestation.
5. Pass original technical authoring/writing/bank/import-conformance/validation/package safety checks.
6. Pass private independent proof verifier and accountable reviewer approvals before any promotion to `ready-exams`.
7. Website import or publication is separate and is **not** part of this skill migration.

The user requested AB-900 before AI-103, with no weakening of blockers and no private-PDF or answer-key leakage to public repositories.

## Known checkpoints and limitations (2026-11-12)

- Private AB-900 ledger previously recorded **47/89 AI-supported checks**, **0/89 independently approved releases**. This is a dated snapshot; do not cite it as a fresh count without rereading the private ledger.
- A private repository research-archive was organized into browsable directories and hashed; those files are **draft evidence**, not proof that keys are correct.
- The private ledger preflight correctly blocked because review, SHA-backed sources, and answer conflicts remain unresolved.
- The original upstream was not writable by the connected account. The owner-controlled `mathorax1-hue/certpassly-exam-skill` has write access and is now the approved skill development destination.
- The two extra helpers and their ten synthetic tests were previously verified in `mathorax1-hue/exam` CI at https://github.com/mathorax1-hue/exam/actions/runs/43183489036. Re-run this skill's CI after each future integration; do not rely only on old results.
- Dependencies for the new helpers: none beyond the standard library; optional PDF/visual/MCP dependencies remain documented in `pyproject.toml`.

## Failure record template

For every meaningful incident, append under `knowledge/`: date; exact command/run; observed error; cause (confirmed vs suspected); fix and diff/commit; synthetic regression test; CI URL/result; blast radius/privacy check; whether private workflow pin changed; unresolved work. Never invent a fix or mark a task complete based on an unconfirmed CI run.

## New reusable tools and tests (2026-11-12)

- scripts/capture_official_source.py: bounded allowlisted HTTPS source download, exact-byte SHA-256, proof quote match and provenance status; tests/test_capture_official_source.py.
- scripts/audit_option_evidence.py: option-by-option rationale and source-field preflight, plus visual row-order checks; tests/test_audit_option_evidence.py.
- scripts/reconcile_visual_roles.py: active/superseded owner screenshot role reconciliation and learner-answer visibility checks; tests/test_reconcile_visual_roles.py.
- scripts/verify_tool_registry.py and config/tool-registry.json: enforce a single index of registered tools, dependencies and tests; tests/test_tool_registry.py.
- See knowledge/ENGINEERING-HISTORY.md for actual failures and confirmed fixes, and docs/DEPENDENCIES.md for approved tooling choices.

These are metadata and source-byte tools, NOT automatic semantic key verification, real human signoff or ready-exams acceptance.

## Next safe engineering tasks

1. Continue consolidating demonstrated generic fixes into this skill (without duplicating existing modules).
2. Provide a stable command and schema adapter for private ledger review, plus a full official-source checksum/option-support workflow; validate with synthetic tests first.
3. Document and test a deliberate, separate integration to the private processing workflow once compatibility is demonstrated; keep original upstream executable pinned until then.
4. Resume the private AB-900 item-by-item verification work with source PDFs and current official pages. Keep human review pending and independent release strict.

**No private bank data, PDF, answer images, secrets, or customer records belong in this file.**
