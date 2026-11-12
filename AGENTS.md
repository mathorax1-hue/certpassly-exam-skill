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

## Permanent shared-skill stewardship

This repository is the canonical writable home for CertPassly reusable scripts, tests, dependency decisions, AI handovers and sanitized technical lessons. Consult config/tool-registry.json and existing public processor code before writing another helper. Add regression tests and a documented dependency/side-effect model; verify public CI on the commit. Keep raw exam records, owner media, complete source snapshots, per-choice proofs and reviewer data in PRIVATE raw-exam.

Do not claim the AI has automatically learned or been trained by reading these files; new sessions must actually read the documented handover. Do not assume a new skill commit automatically changes the old pipeline's pinned runtime. Independent reviewer approval and promotion remain separate private gates.

## Operator loop

Review state -> reproduce with synthetic input -> edit shared code -> run unit tests -> check CI -> propose private integration -> run bounded private stage -> compare evidence -> request independent approval -> promote only when all release checks pass.

## Upstream license note

The public upstream root tree did not show a `LICENSE` file during initial review. Linking to its pinned Git checkout is permitted as an integration design; copying substantial source into this public repository is on hold until redistribution rights are confirmed.
