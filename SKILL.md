---
name: certpassly-exam-skill
version: 0.1.0
description: >-
  Resumable, evidence-first CertPassly exam orchestration and safety checks.
  Use for owner-exam intake, progress recovery, vendor-answer review,
  visual-question audit, upstream pipeline reuse, and release-gate diagnosis.
  Never claim an AI draft has independent approval.
---

# CertPassly Exam Skill 2.0

Read `AGENTS.md`, `knowledge/AB900-LESSONS.md`, `knowledge/ENGINEERING-HISTORY.md`, `docs/OPERATIONS.md`, `docs/TOOL-HUB.md`, `docs/DEPENDENCIES.md`, `docs/INTEGRATION-PLAYBOOK.md` and **`docs/AI-SESSION-RECOVERY.md`** before processing real owner questions. Use this repository (`mathorax1-hue/certpassly-exam-skill`) as the canonical shared skill, scripts, dependency and lessons hub; do not write new skill updates to the older external upstream. Read upstream `SKILL.md` and `reference/lessons-learned.md` before running its pipeline.

## Default workflow

1. Identify the exact owner exam and repo. Keep its PDF, screenshots, keys, and research in `raw-exam` or an approved private workspace.
2. Check `config/repositories.json`, upstream pin, tool versions, and `certpassly doctor` output.
3. Run local synthetic tests before modifying the public shared skill or public processor.
4. For existing upstream processing, use `certpassly upstream-run` with a verified pinned checkout and a private root. Do not rewrite or vendor upstream scripts.
5. Use `certpassly run` for trusted multi-step plans; checkpoints skip **only** previously passed steps whose inputs, outputs, commands, and dependency hashes match.
6. Record question-by-question evidence. Differentiate incorrect, outdated, arguable, and merely unverified keys. Keep source originals and provenance.
7. Use `certpassly verify-evidence --input PATH --strict` for a **structural** check. An official URL or saved quote alone does not demonstrate that a specific answer is correct.
8. Final import conformance, screenshot scoring, reviewer attestation, and protected approval remain **separate private gates**.
9. Never promote, publish, or claim `100% ready` when any gate is unresolved.

## Conversation-history recovery (required for authorized handovers)

Read docs/CONVERSATION-ARCHIVE-PROTOCOL.md and the private raw-exam master, not only the tool registry. All actual conversations, owner source and embedded evidence stay PRIVATE. Preserve the single existing master in-place via scripts/append_conversation_history.py, with preview, authenticated event provenance, explicit --apply, readback and matching private GitHub/Library copies when both are accessible. Recording conversation context is not model retraining or automatic account-wide export.

## Reuse-first tool discipline

Treat this repository as the canonical source for new CertPassly scripts, tools, tests, dependency decisions and sanitized experience. Search the machine-readable registry at config/tool-registry.json and existing public processor before implementing a new helper. Every new tool must have synthetic tests, a dependency/side-effect description, public CI proof and a permanent incident/lesson record where relevant.

New source-and-visual tooling includes scripts/capture_official_source.py, scripts/audit_option_evidence.py, scripts/audit_question_evidence.py, scripts/reconcile_visual_roles.py and scripts/unpack_artifact_tree.py. Their checks are **structural/provenance only**, not answer truth or independent human approval. Full invocation and schemas are in docs/TOOL-HUB.md.

Run python scripts/verify_tool_registry.py and all unit tests before calling an engineering change complete. A green build does not imply any private exam has passed the release gates.

## Commands

```bash
certpassly doctor
certpassly run --plan config/pipeline.example.json
certpassly status
certpassly verify-evidence --input tests/fixtures/pending-review.json --strict
certpassly upstream-run --checkout vendor/certpassly-exam-pipeline --private-root /private/work --exam AB-900 --stage extract --dry-run
```

## Agent instructions

- Prefer tools and scripts already in this repository. Fix or extend tested functions instead of generating new one-off code.
- Make the smallest change, rerun relevant tests, store a regression case, and record lessons with observed evidence.
- All answers require evidence from official vendor documentation saved with URL, retrieval timestamp, SHA256 and relevant quote. Check **all** answer options before changing an original key.
- Human review must be performed by a real authorized reviewer. AI-generated review metadata is not independent approval.
- Never leak reviewer-only answer screenshots into learner payloads. Synthetic test images are allowed only if no owner content is reused.
- Never place secret tokens in output, logs, git, prompts, or public CI. GitHub actions should use least privilege.
- No external network or money-spending actions without the applicable user authorization and policy.
- Keep private Actions costs low: run public synthetic checks on every change, and private end-to-end checks only when warranted.
- Record accurate status including blockers and unknowns rather than completing checklists optimistically.

## Optional MCP

`pip install -e '.[mcp]'` then `certpassly-mcp` runs a read-only stdio server exposing `environment_doctor`, `checkpoint_status`, and `evidence_status`. This does **not** create privileged ChatGPT integrations automatically. See `docs/MCP.md`.
