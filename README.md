# CertPassly shared skill hub (core v0.1.0 + tested reusable utilities)

A reusable **scripts-first, evidence-first** toolkit for CertPassly exam processing. This repository is PUBLIC and must never contain owner PDFs, answer keys, credentials, raw screenshots, private artifacts, or human approval tokens.

> **Status:** Tested foundation, not a finished production exam verifier. The evidence audit checks the *structure* of official-source records and image-release metadata; it does **not** independently verify answer truth or certify independent review. Production promotion is intentionally absent from this public repository.

## Private master conversation history

The [conversation archive protocol](docs/CONVERSATION-ARCHIVE-PROTOCOL.md) documents how to update the SAME private conversation-history JSON in ChatGPT Library and private raw-exam, with verified GitHub hashes, synthetic append-only tooling, and an explicit boundary against fictitious or inaccessible chat messages. The permanent private archive is NEVER committed here.

## Reusable tools, dependencies and lessons

This repository is the **canonical** home for new reusable CertPassly tools, tests, dependency guidance and sanitized failure/pass history. Read the [machine-readable registry](config/tool-registry.json) before building a new helper; public CI now validates registry entries and all synthetic tests. Real owner PDFs, keys, original screenshots, downloaded official pages and per-question evidence remain private.

- [Tool hub and evidence schemas](docs/TOOL-HUB.md): exact commands for official source capture, offline receipt verification, option-by-option audits, visual role reconciliation, ledger preflight and artifact archive organization.
- [Phase 1 PDF extraction toolkit](docs/PHASE1-EXTRACTION.md): config-driven, fail-closed extraction of owner exam PDFs into a private structured/v1 layer (`certpassly phase1-audit` / `phase1-extract`); strictly local, no release authority.
- [Dependencies and installation](docs/DEPENDENCIES.md): core Python 3.11+, optional PDF, visual, browser, MCP and developer extras.
- [Four-repo integration playbook](docs/INTEGRATION-PLAYBOOK.md): private verification, raw-to-ready gates, rollback and no publication.
- [Engineering history](knowledge/ENGINEERING-HISTORY.md): observed failures, tested fixes, CI links, open gaps and permanent safeguards.
- [AI session recovery](docs/AI-SESSION-RECOVERY.md): new-session restart order and private handover pointer.

**These tools document and safeguard evidence; they cannot independently establish answer truth or authorize human review.** Older upstream pipeline code remains a separately pinned compatibility dependency where the private workflow still uses it.

## What works now

- `certpassly doctor`: identify installed tools and missing optional dependencies.
- `certpassly run`: execute a trusted, ordered JSON plan, keeping content-hash checkpoints in ignored local SQLite storage.
- Resume previously successful stages, automatically invalidating stages after input, output, command, or dependency changes.
- `certpassly verify-evidence`: fail-closed review of unverified answer keys, missing official citations, screenshot answer keys, image approvals, and reviewer-only content leaks.
- `certpassly upstream-run`: run **existing original upstream scripts** from an external Git checkout verified against a full commit SHA; no duplication of upstream source code.
- Optional read-only MCP tools: environment doctor, checkpoint status, evidence-status overview.
- Synthetic unit and regression tests through public CI without private GitHub minutes.

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
certpassly doctor
certpassly run --plan config/pipeline.example.json
certpassly status
# The second run should show cached stages:
certpassly run --plan config/pipeline.example.json
# This deliberately blocks a pending synthetic review:
certpassly verify-evidence --input tests/fixtures/pending-review.json --strict
```

On Windows PowerShell: `.venv\\Scripts\\Activate.ps1` instead of `. .venv/bin/activate`.

Test with no installation: `PYTHONPATH=src python -m unittest discover -s tests -v`.

## Reuse upstream without copying it

The existing public upstream is [`msaqlainhaneef1/certpassly-exam-pipeline`](https://github.com/msaqlainhaneef1/certpassly-exam-pipeline), pinned to `13dea6bab662ab1c4bbf87017e912e519907c8bc`. Existing site-format rules, 15 stages and CSV schemas stay there until compatibility and reuse permissions are fully confirmed. No `LICENSE` file appeared in the upstream root tree at initial review; **do not vendor its code into this repository without permission**.

```bash
bash scripts/bootstrap_upstream.sh
certpassly upstream-run \
  --checkout vendor/certpassly-exam-pipeline \
  --private-root /path/to/PRIVATE-owner-workspace \
  --exam AB-900 --stage extract --dry-run
# For a real local stage, remove --dry-run; offline is the default.
```

The private workspace must have the config/source files required by upstream, as described in its `SKILL.md` and operator guide. This adapter never imports to the website or promotes to `ready-exams`.

## Repository roles

| Repository | Visibility | Responsibility |
|---|---|---|
| `mathorax1-hue/certpassly-exam-skill` | public | Shared orchestration, tests, skills, safe knowledge |
| `mathorax1-hue/exam` | public | Existing processor, synthetic tests, release evidence code |
| `mathorax1-hue/raw-exam` | private | Owner PDFs, question keys, editorial source evidence, gated pipeline |
| `mathorax1-hue/ready-exams` | private | Independently checked and approved release evidence + packages |

The release authority must remain in a protected private GitHub environment, not in AI-produced JSON or an MCP tool.

Read [`SKILL.md`](SKILL.md), [`AGENTS.md`](AGENTS.md), [`docs/OPERATIONS.md`](docs/OPERATIONS.md), and [`knowledge/AB900-LESSONS.md`](knowledge/AB900-LESSONS.md). **New AI sessions must begin with the [canonical recovery and reusable-tool registry](docs/AI-SESSION-RECOVERY.md)** and the private handover linked from it. This repository is now the requested destination for all new shared skills, tooling, tests, and sanitized failure lessons.

## Future work

See [`docs/ROADMAP.md`](docs/ROADMAP.md). The current foundation does **not** include a verified CertPassly live-site importer, automatic document-based answer reasoning, private GitHub Actions dispatch, a cloud database, or a complete release-authority model. Those require controlled integration and tests.
