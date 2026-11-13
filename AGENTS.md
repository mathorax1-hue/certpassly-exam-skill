# CertPassly agent operating contract

Every AI agent (ChatGPT, Claude, Gemini, Codex, Copilot and others) must read `SKILL.md`, `knowledge/AB900-LESSONS.md`, `knowledge/ENGINEERING-HISTORY.md`, `docs/OPERATIONS.md`, `docs/TOOL-HUB.md`, `docs/INTEGRATION-PLAYBOOK.md`, and **`docs/AI-SESSION-RECOVERY.md`** before working on exams. This repository is the canonical home for new shared scripts, tests, dependencies, and sanitized lessons; read the separate PRIVATE raw-exam handover for live item progress. For upstream runs read upstream `SKILL.md` and its exact versioned reference manual.

## Mandatory boundaries

1. This repository is **public**. Original exams, response keys, licensed images, personal data, review records, customer secrets and source snapshots must remain private.
2. Original owner questions are immutable. Any correction or new CertPassly Team question is a separately provenance-tracked overlay; do not silently edit the source.
3. Distinguish **technical pipeline passed**, **AI evidence found**, **answer independently reviewed**, **release approved**, and **site import accepted**. These are five different statuses.
4. Never mark `human_review_required=false` by guessing or by asserting an AI persona is human. Missing evidence is NOT proof of an incorrect answer.
5. The structural `verify-evidence` auditor is necessary but not sufficient: it cannot verify whether stored quotes are genuine or whether selected answers match the source.
6. No automatic promotion to private `ready-exams`, website import, public publication, credential disclosure or secret copying.
7. Use verified git commits, tests and sha256 as provenance. Pin upstream code. Do not force-push or delete source history.
8. Each new confirmed bug needs: observed failure, cause, patch, test, reproduction command, and resolution status in `knowledge/`.
9. Prioritize the current exam requested by the owner. Avoid unsolicited full private Actions runs; one exam per run by default.
10. Follow least privilege. Do not modify workflows or private repository secrets without review of scope and behavior.

## Mandatory private conversation-history archiving

When the owner requests chat-history retention or at a manually approved handover, read docs/CONVERSATION-ARCHIVE-PROTOCOL.md. Update the existing PRIVATE master JSON in raw-exam/docs/conversation-history/ and the ChatGPT Library SAME path only if authorized and technically available. Preserve original history and embedded evidence; append only authenticated available messages, commands, failures, successes, links and next steps. Do not copy any private conversation contents into this public skill. Verify Git commit and Library version/bytes; never claim skipped messages were recovered. Use scripts/append_conversation_history.py and its synthetic tests.

## Permanent shared-skill stewardship

This repository is the canonical writable home for CertPassly reusable scripts, tests, dependency decisions, AI handovers and sanitized technical lessons. Consult config/tool-registry.json and existing public processor code before writing another helper. Add regression tests and a documented dependency/side-effect model; verify public CI on the commit. Keep raw exam records, owner media, complete source snapshots, per-choice proofs and reviewer data in PRIVATE raw-exam.

Do not claim the AI has automatically learned or been trained by reading these files; new sessions must actually read the documented handover. Do not assume a new skill commit automatically changes the old pipeline's pinned runtime. Independent reviewer approval and promotion remain separate private gates.

## Operator loop

Review state -> reproduce with synthetic input -> edit shared code -> run unit tests -> check CI -> propose private integration -> run bounded private stage -> compare evidence -> request independent approval -> promote only when all release checks pass.

## Upstream license note

The public upstream root tree did not show a `LICENSE` file during initial review. Linking to its pinned Git checkout is permitted as an integration design; copying substantial source into this public repository is on hold until redistribution rights are confirmed.

## Universal reusable-tool intake rule

All CertPassly developers and AI agents (including Z.ai and Grok) must submit new **generally reusable, owner-authored and public-safe** scripts, validators, schemas, OCR/extraction utilities, tests, install/caching recipes, bug fixes and versioned commands here as separate **reviewed public pull requests**. This repo is the **permanent canonical tool home**; the private raw-exam repository documents the matching mandatory [tool-promotion policy](https://github.com/mathorax1-hue/raw-exam/blob/main/docs/REUSABLE-TOOL-PROMOTION-POLICY.md), which is accessible only to authorized collaborators. Read this repo's `config/tool-registry.json`, `docs/DEPENDENCIES.md`, `docs/TOOL-HUB.md`, `SKILL.md` and existing code before creating another script.

Each promoted command MUST include its sanitized source and synthetic test fixtures; CLI syntax, examples and expected output/exit codes; minimum Python/system dependencies and reproducible pinned install; a cached/idempotent environment workflow (no unnecessary reinstalls); registry ID, input/output schemas and safe side effects; provenance/commit pin; basic security/license/public-data audit; compatibility with the currently pinned upstream integration; and public CI result. Make the private worker use the exact reviewed public tool SHA, not an independently drifting copy. Document restrictions and limitations clearly.

**Security/license boundary:** never publish original exam PDFs, text, question options, owner answer keys, images, real source manifests/receipts, real derived exam JSON, private run logs, credentials, customer data, private conversation history or third-party code lacking redistribution permission. A generic script may be promoted only after removing real private content and verifying licensing. If a safe public release is not possible, record `tool_promotion_pending` and keep the private adapter/source in `raw-exam`. No PR promotion by itself authorizes an exam publication, owner-key modification or a human review assertion.
