# Reusable tool hub: commands and evidence schemas

**Canonical repository:** https://github.com/mathorax1-hue/certpassly-exam-skill

This is the single catalog for new reusable CertPassly tools. Before writing any new tool, search [config/tool-registry.json](../config/tool-registry.json), relevant modules under src/certpassly/, scripts/, and the test suite. Avoid duplicate implementations. A command must have synthetic regression tests, documented dependencies, and a known failure mode.

## Private conversation master archiving

The reusable script scripts/append_conversation_history.py receives an existing private master and a provenance-marked event batch. Run a preview first, then --apply to atomically append to the SAME file. See docs/CONVERSATION-ARCHIVE-PROTOCOL.md for exact commands and post-commit/library verification. Do not add confidential master JSON to this public repo.

## Core commands

From the repository root, with Python 3.11+:

| Command | Use | Writes? |
|---|---|---|
| python -m certpassly.cli doctor --json | System tool/optional dependency inventory | No |
| python -m certpassly.cli run --plan config/pipeline.example.json | Run/resume trusted plan | Local ignored work and SQLite |
| python -m certpassly.cli status | Inspect checkpoint state | No |
| python -m certpassly.cli verify-evidence --input PRIVATE/dossier.json --strict | Structural bank and learner-media privacy audit | Optional private output |
| python scripts/audit_question_evidence.py PRIVATE/active-question-review-ledger.json | Preflight current private review ledger schema | No by default |
| python scripts/audit_option_evidence.py --input PRIVATE/option-dossier.json | Check every selected option and distractor for source fields and order | No by default |
| python scripts/verify_saved_receipts.py --private-dir PRIVATE/official-pages --allow-host learn.microsoft.com | Rehash saved pages and recheck receipt quotes without network | Read-only; optional private report |
| python scripts/reconcile_visual_roles.py --input PRIVATE/visual-roles.json | Separate active and superseded screenshots; catch role and learner-safety errors | No by default |
| python scripts/capture_official_source.py --help | Download and SHA-256-hash an allowlisted official page, verify proof quote | Private snapshots only |
| python scripts/unpack_artifact_tree.py PRIVATE/archive.zip PRIVATE/unpacked | Expand nested artifact ZIP into folders with a checksummed file manifest | Private directories only |
| python scripts/verify_tool_registry.py | Ensure tools, tests and policy entries exist | No |
| python scripts/check_public_safety.py | Scan tracked public file paths | No |
| bash scripts/bootstrap_upstream.sh | Fetch exact legacy runtime revision into ignored vendor/ | Network and ignored vendor/ |

If installed as a package, use certpassly rather than python -m certpassly.cli. See [dependencies](DEPENDENCIES.md) and [operator workflow](INTEGRATION-PLAYBOOK.md).

## Phase 1 PDF extraction toolkit (certpassly.phase1)

Config-driven source extraction of owner exam PDFs into a private structured/v1
layer. Ten registered commands (`phase1_source_audit`, `phase1_media_pmap`,
`phase1_structured_builder`, `phase1_export_builder`, `phase1_source_manifest`,
`phase1_validator`, `phase1_reconciler`, `phase1_visual_qa`, `phase1_run_all`,
`phase1_adversarial_suite`). Install once per pinned commit with
`python -m pip install -e ".[phase1]"`, reuse the cached venv and the pinned
upstream checkout. Strictly local, fail-closed, no release authority —
see [PHASE1-EXTRACTION.md](PHASE1-EXTRACTION.md) for the exact command
sequence, caching, troubleshooting and the honest scope statement.

| Command | Use | Writes? |
|---|---|---|
| certpassly phase1-info | Toolkit version, schema compatibility, upstream pin | No |
| certpassly phase1-audit --pdf PRIVATE/source.pdf --expected-sha256 HEX | Read-only source identity/integrity audit (exit 2 = BLOCKED) | Optional local JSON |
| python -m certpassly.phase1.make_pmap PRIVATE/source.pdf PRIVATE/out/media/src PRIVATE/pmap.json | Map pdftohtml media to PDF xrefs | One local JSON |
| python -m certpassly.phase1.build_structured_v1 PRIVATE/config.json | Build the private structured/v1 layer | Private structured tree |
| python -m certpassly.phase1.build_exports PRIVATE/config.json | Deterministic + fail-closed export adapters | Export files (no learner content) |
| python -m certpassly.phase1.make_source_manifest PRIVATE/config.json | Read-only artifact inventory | source-manifest.json |
| python -m certpassly.phase1.validate_structured_v1 PRIVATE/config.json | Config-driven validation contract | extraction-report.json |
| python -m certpassly.phase1.reconcile PRIVATE/config.json | Count-system cross-walk; stage-log/visual-draft claims are genuinely recomputed from the pinned upstream outputs (or informational notes outside the passed denominator) | reconciliation.json |
| python -m certpassly.phase1.visual_qa PRIVATE/config.json | Machine visual QA (not human review); exit 2 = MACHINE VISIBILITY FAILURE (not-visible placement / image-bearing page rendering blank), pending human review never impersonated | qa/ renders and reports |
| certpassly phase1-extract --config PRIVATE/config.json --upstream-scripts DIR [--dry-run --resume --start-from STAGE] | Deterministic stage orchestrator with checkpoints; runs the read-only source audit as stage 0 and refuses to continue past a failed audit; --resume/--start-from are gated by a fail-closed source guard (exit 3 on changed/missing PDF, edited config, swapped upstream pin, changed toolkit code or stale checkpoint) AND an output-inventory guard that is also an EXACT FILE-SET receipt (exit 3 when a recorded question JSON, asset binary or QA/validation/reconciliation report was deleted or modified, AND when an unexpected extra file - injected question JSON, stray answer asset, rogue upstream output - appears in the monitored output roots; inventory-less old checkpoints force an explicit full stage-0 rebuild; partial resumes preserve the verified skipped stages' receipts so the checkpoint keeps the complete stage list and repeated partial resumes chain) - never a green no-op without verification | Stage outputs + checkpoint with per-stage output inventories and the complete stage list |
| python -m certpassly.phase1.adversarial --base SCRATCH --upstream PINNED/scripts | 37 synthetic adversarial scenarios (real pinned extractor + real builder) | Scratch + optional report |


## Non-AI clean simulator images (certpassly.media_prep)

Deterministic clean-image selection, high-resolution rendering, quality gates and the hard answer-image privacy gate on top of the PINNED upstream extraction (read-only checkout; never vendored, never reimplemented). Strictly local, no AI, no inpainting, no upscaling-as-restoration. Install with `python -m pip install -e ".[phase1,visual]"`. Full design, role definitions and the A/B/C/D priority contract: [NONAI-SIMULATOR-IMAGES.md](NONAI-SIMULATOR-IMAGES.md); test matrix: [NONAI-IMAGE-TEST-PLAN.md](NONAI-IMAGE-TEST-PLAN.md); install/commands/troubleshooting: [NONAI-IMAGE-OPERATOR-RUNBOOK.md](NONAI-IMAGE-OPERATOR-RUNBOOK.md).

| Command | Use | Writes? |
|---|---|---|
| python -m certpassly.media_prep doctor --json | Module/system-tool/pin inventory | No |
| python -m certpassly.media_prep scan --config PRIVATE/media-prep-config.json [--output F --explain] | Read-only source-image role inventory + per-question readiness; exit 2 = blocked questions (honest, listed) | Optional local JSON |
| python -m certpassly.media_prep prepare --config PRIVATE/media-prep-config.json [--dry-run --explain] | Write ONLY verified clean candidates + isolated reviewer-only copies + tamper-evident manifest; byte-identical on rerun | prepared/clean, prepared/private/reviewer-only, manifest, inventory |
| python -m certpassly.media_prep verify-package --config PRIVATE/media-prep-config.json --package DRAFT.zip | Explicit-allowlist privacy gate: reviewer-only SHA, unallowlisted members, traversal/symlink/nested-zip/external-URL/duplicate/publish-flag refusals, manifest tamper; exit 3 = refused | Optional report JSON |

Registry entries: `media_prep_source_scan`, `media_prep_selection_prepare`, `media_prep_privacy_gate`, `media_prep_doctor`. Schemas: `image-readiness-v1`, `image-manifest-v1`, `media-prep-v1` (JSON Schema, package-data).

## Official source capture (real output remains private)

    python scripts/capture_official_source.py \
      --url "https://learn.microsoft.com/en-us/example" \
      --allow-host learn.microsoft.com \
      --id q001-optionA-doc1 \
      --quote "Exact short passage copied from the downloaded page" \
      --private-output-dir /path/to/PRIVATE/raw-exam/exams/AB-900/evidence/official-pages/

The script requires the quote to actually occur in the downloaded visible text, then saves source bytes and a JSON receipt. The receipt includes final URL, SHA-256, content length, timestamp, quote and capture mode. It does not approve an answer. If downloaded pages are unavailable, --offline-file marks the origin as unverified rather than pretending a live fetch took place. No automated source claims should be made from offline mode alone. Redirects must remain inside the explicitly allowed domain set.

**Important:** Avoid running this on the public CI runner with real owner question evidence or saving snapshots in this public repository. Downloading source bytes establishes provenance of the bytes; it does not establish that the page makes a correct answer.

## Option-by-option dossier (JSON schema example; synthetic only)

    {
      "exam_code": "SYN-100",
      "official_hosts": ["learn.microsoft.com"],
      "questions": [{
        "id": "q001",
        "options": [
          {"id": "A", "text": "Synthetic option A"},
          {"id": "B", "text": "Synthetic option B"}
        ],
        "option_order": ["A", "B"],
        "selected_option_ids": ["A"],
        "option_reviews": [
          {"option_id": "A", "verdict": "supported", "rationale": "Why selected",
           "sources": [{"url": "https://learn.microsoft.com/example",
                        "sha256": "<64 lowercase hex characters>",
                        "quote": "Literal matching vendor excerpt",
                        "capture_mode": "downloaded"}]},
          {"option_id": "B", "verdict": "contradicted", "rationale": "Why not selected",
           "sources": [{"url": "https://learn.microsoft.com/example",
                        "sha256": "<64 lowercase hex characters>",
                        "quote": "Literal supporting vendor excerpt",
                        "capture_mode": "downloaded"}]}
        ]
      }]
    }

Every option requires its own documented rationale and vendor source fields. A selected option must have a supported verdict; a nonselected option must have a contradicted verdict. Ambiguous or undocumented choices remain blocked. **The tool checks structure, not whether a quote is genuine or a rationale is scientifically correct.** Official source receipts and explicit reviewer checks provide the next layers of verification.

For screenshot-based questions, add the optional "visual" object in the same question:

    "visual": {
      "question_prompt_sha256": "<64 lowercase hex>",
      "answer_reference_sha256": "<64 lowercase hex>",
      "original_row_order": ["r1", "r2"],
      "reviewed_row_order": ["r1", "r2"],
      "obscured_answer": false,
      "image_meaning_reviewed": true
    }

These are assertions to audit against private image evidence. The script does not inspect image pixels or establish who reviewed them. Never infer obscured dropdown or matrix selections.

## Active versus superseded image reconciliation

    {
      "exam_code": "SYN-100",
      "active_questions": [{"id": "q001", "expected_roles": ["question_prompt", "answer_reference"]}],
      "images": [
        {"id": "active-question", "owner_question": "q001", "role": "question_prompt",
         "sha256": "<64 lowercase hex>", "owner_state": "active", "learner_visible": true},
        {"id": "active-answer", "owner_question": "q001", "role": "answer_reference",
         "sha256": "<64 lowercase hex>", "owner_state": "active", "learner_visible": false,
         "reviewer_only": true, "visual_answer_verified": true},
        {"id": "old-answer", "owner_question": "q999", "role": "answer_reference",
         "sha256": "<64 lowercase hex>", "owner_state": "superseded", "learner_visible": false}
      ]
    }

Superseded images are inventoried separately, never counted as active. Any active owner mismatch, absent expected role, answer-reference learner leak, or unreviewed answer meaning blocks. Image metadata consistency is not image authenticity, content accuracy, reviewer approval, or permission to publish.

## What counts as verification?

A green unit test proves only code behavior on synthetic fixtures. A source hash proves the saved bytes were hashed, not that a fact is correct. Matching owner screenshots proves image integrity, not answer truth. An AI-supported choice check is not independent human review. A private ready-exams draft requires all original technical gates, source and option evidence, visual checks, an independent verifier and the required real reviewer approvals. The live website is a separate process.

## Build once, reuse everywhere

For each new tool:

1. Search the tool registry and existing modules for equivalent behavior.
2. Write a short failure case using synthetic inputs first; do not publish private fixtures.
3. Implement the smallest generic adapter or module, with no implicit release authority.
4. Add tests in tests/test_<tool>.py and tool-registry entry with dependency info.
5. Run PYTHONPATH=src python -m unittest discover -s tests -v, python scripts/verify_tool_registry.py, and python scripts/check_public_safety.py.
6. Commit the source, regression test and corrected guide; confirm green CI at the exact commit.
7. Update knowledge/ with real failure, root cause, proof and follow-up; update private handover only with confidential evidence pointers.
8. Review and explicitly approve new dependency versions and any private workflow pin changes; never silently replace protected release gates.

No special cloud service, background monitor, live importer or hidden GitHub permission is provided by installing these tools.
