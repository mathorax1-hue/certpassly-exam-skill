# CertPassly Exam Skill 2.0 — initial foundation (v0.1.0)

A reusable **scripts-first, evidence-first** toolkit for CertPassly exam processing. This repository is PUBLIC and must never contain owner PDFs, answer keys, credentials, raw screenshots, private artifacts, or human approval tokens.

> **Status:** Tested foundation, not a finished production exam verifier. The evidence audit checks the *structure* of official-source records and image-release metadata; it does **not** independently verify answer truth or certify independent review. Production promotion is intentionally absent from this public repository.

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

Read [`SKILL.md`](SKILL.md), [`AGENTS.md`](AGENTS.md), [`docs/OPERATIONS.md`](docs/OPERATIONS.md), and [`knowledge/AB900-LESSONS.md`](knowledge/AB900-LESSONS.md).

## Future work

See [`docs/ROADMAP.md`](docs/ROADMAP.md). The current foundation does **not** include a verified CertPassly live-site importer, automatic document-based answer reasoning, private GitHub Actions dispatch, a cloud database, or a complete release-authority model. Those require controlled integration and tests.
