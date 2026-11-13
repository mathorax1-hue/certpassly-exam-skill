# Phase 1 PDF extraction toolkit (certpassly.phase1)

Config-driven, source-faithful extraction of owner exam PDFs into a private
`structured/v1` layer: question records, per-page records, exact source image
binaries with usage/xref provenance, fail-closed exports, validation,
reconciliation and machine visual QA. Promoted from the reviewed private pilot
toolkit (ZAI-EXTRACT-001/002) by ZAI-EXTRACT-003; see the sanitized history
entry in [knowledge/ENGINEERING-HISTORY.md](../knowledge/ENGINEERING-HISTORY.md).

**Honest scope.** This is the Phase-1 *source-extraction* layer only. It does
NOT replace the pinned upstream 15-stage authoring pipeline (that pipeline
remains an external, read-only dependency), does NOT verify answer truth, and
has **no release authority**: every answer/unknown stays unapproved, all
answer-reference media is `private_reviewer_only`, and nothing here publishes,
uploads or imports to any website. All outputs are private workspace files.

## Safety model (fail-closed everywhere)

- **Strictly local.** No network module is imported anywhere in the package
  (enforced by `tests/test_phase1_safety.py`). No upload, no publication, no
  GitHub API calls.
- **Source immutability.** The engine never writes to the source PDF, answer
  keys, research archives or the pinned upstream checkout.
- **Identity gate.** `phase1-audit` verifies SHA-256/bytes/encryption before
  anything else and exits `2` (BLOCKED) on mismatch; advertised filename
  question counts are never trusted. BLOCK criteria are hard (director audit
  2026-11-13): encrypted sources, identity-ambiguous geometry, missing /
  noncontiguous / duplicate question markers and unextractable source image
  streams all exit `2` with explicit reasons - an audit is never "complete"
  while a blocking defect is present.
- **Typed-letter discipline (P0-A).** On image-based questions the typed text
  (e.g. the template `A` observed across combined-key VCE-style items) is a
  **source literal only**: it is preserved verbatim in
  `answer.raw_text` and marked `answer.typed_key_status =
  source_literal_only_key_status_unknown`. The interaction type comes from
  visual evidence (pinned OCR kind / prior drafts), and when no visual kind
  exists the type stays `unknown` with low confidence - a typed letter never
  implies `single_choice`. Text-only questions keep the high-confidence
  typed-key classification.
- **Honest blocker counters (P0-D).** Every `export-blockers.json` row carries
  at least one explicit reason (a standalone independent-review reason when no
  specific gate applies); `blocked_questions_with_reasons` must equal
  `blocked_questions`, and the validator recomputes the count from the items
  rather than trusting stored counters.
- **Answer privacy.** Answer-reference images and combined typed+image answers
  are classified `private_reviewer_only` and are provably absent from every
  learner-facing export (`export/site-format-v1-draft` contains types and
  blockers only).
- **No guessing.** Unknown layouts, corrupt image streams, duplicate markers
  and unresolvable items fail LOUDLY (BLOCKED with reason codes) or stay
  `unknown` + `unresolved`; nothing is silently dropped or fabricated.

## Installation (once per commit), caching and reuse

The toolkit is part of the `certpassly-exam-skill` package. Install **once**
and reuse the environment; do not reinstall on every run.

```bash
git clone https://github.com/mathorax1-hue/certpassly-exam-skill.git
cd certpassly-exam-skill
git checkout <reviewed-full-commit-sha>          # pin, never floating main

python3 -m venv .venv                             # create ONLY if absent
. .venv/bin/activate                              # Windows: .venv\Scripts\activate
python -m pip install -e ".[phase1]"              # PyMuPDF + Pillow + numpy + jsonschema

certpassly doctor --json                          # environment inventory
certpassly phase1-info                            # toolkit version + upstream pin
python -m unittest discover -s tests -v           # full synthetic suite
python scripts/verify_tool_registry.py
python scripts/check_public_safety.py
```

Notes:

- **Reinstall only when** the pinned dependency set, Python version or the
  checked-out commit's `pyproject.toml` changes. Source edits in an
  editable install do not require reinstalling. Check what is installed with
  `python -m pip show certpassly-exam-skill` and `python -m pip check`.
- **Wheel cache**: pip's download cache (`python -m pip cache dir`) is reused
  automatically across environments on the same machine; do not delete it
  between runs.
- **Pinned upstream checkout** (external dependency, read-only, never vendored
  here — its root has no confirmed redistributable LICENSE):

```bash
bash scripts/bootstrap_upstream.sh                 # creates vendor/certpassly-exam-pipeline
git -C vendor/certpassly-exam-pipeline rev-parse HEAD
# must print: 13dea6bab662ab1c4bbf87017e912e519907c8bc
```

  `bootstrap_upstream.sh` refuses to overwrite an existing checkout; call it
  only when the directory is absent. A wrong/missing pin is a stop-and-report
  condition, never a silent update.

- **System prerequisites** (not pip): Poppler `pdftohtml` (engine used by the
  pinned extractor) and Tesseract OCR (visual drafts). Git LFS is required
  only for private repositories that store source PDFs in LFS.
- **Windows (PowerShell)**: same commands with `python -m venv .venv`,
  `.venv\Scripts\Activate.ps1`, and `$env:PYTHONPATH = "src"` if running from
  a checkout without installing. The upstream bootstrap script needs Git Bash
  or WSL.

## What is cached / how to resume

- **Determinism**: the same config + pinned upstream commit + source PDF
  always reproduces the same `structured/v1` tree byte-identically (data
  files). Re-running a stage is therefore always safe.
- **Stage checkpoints**: `certpassly phase1-extract` writes
  `run-checkpoint.json` next to the config, including the verified
  `source_fingerprint` (actual PDF SHA-256/bytes, config content hash, pinned
  upstream scripts tree hash, engine) and the stage-0 audit summary.
  `--resume` skips stages that already exited 0 for the same config AND the
  same verified source fingerprint, and continues at the first incomplete
  stage; `--start-from <stage>` begins at a named stage over a verified
  checkpoint whose earlier stages all exited 0; `--dry-run` prints the
  planned commands and executes nothing (the guard still reports its
  verdict).
- **Resume cannot bypass the source checks** (director final correction,
  2026-11-13): before ANY stage may be skipped, a fail-closed source guard
  re-verifies at resume time that the source PDF still exists and hashes to
  the config-pinned `expected_pdf_sha256`/`expected_bytes`, that the
  checkpoint embeds an `AUDIT_COMPLETE`/non-ambiguous audit of that exact
  source, and (for `--start-from`) that every earlier stage passed. A
  changed/missing PDF, an edited config, a swapped upstream pin or a stale
  checkpoint refuses with **exit 3** before any stage runs, leaving the
  checkpoint untouched; re-run from stage 0 so the audit re-verifies.
  `--resume` with a missing/foreign checkpoint cannot authorize skipping and
  degrades to a FULL run from stage 0 (audit re-runs, nothing is skipped).
- **Per-stage idempotence**: each stage only reads its declared inputs
  (source PDF, pinned extractor output, config) and rewrites its own outputs.

## Exact command sequence (one exam)

`PRIVATE/...` paths live in your private workspace — never in this public
repository. One JSON config (template: [config/phase1-config.example.json](
../config/phase1-config.example.json)) is the single source of truth: paths,
expected SHA-256/bytes, layout rules, expected counts, notes and provenance.

```bash
# 0. workspace layout (private):
#    <ws>/owner-files/<EXAM>/<pdf>      LFS-pulled original (immutable)
#    <ws>/out/<EXAM>/                   pinned-upstream extraction output
#    <upstream>/                        pinned checkout (13dea6bab...)
#    <config>.json                      per-exam config (single source of truth)

# 1. read-only identity/integrity audit (BLOCKS on mismatch)
certpassly phase1-audit --pdf "<ws>/owner-files/<EXAM>/<pdf>.pdf" \
    --expected-sha256 <sha256-from-manifest> --expected-bytes <n> \
    --tool-label "certpassly.phase1.audit_source (certpassly-exam-skill @ <sha>)" \
    --out <ws>/source-audit.json

# 2. pinned upstream extraction (unmodified external scripts) + media/xref map
python "<upstream>/scripts/extract_owner_pdf.py" "<pdf>" "<ws>/out/<EXAM>"
python "<upstream>/scripts/analyze_visual.py" "<ws>/out/<EXAM>"
python -m certpassly.phase1.make_pmap "<pdf>" "<ws>/out/<EXAM>/media/src" "<ws>/pmap.json"

# 3. build the structured/v1 layer (config-driven)
python -m certpassly.phase1.build_structured_v1 <config>.json

# 4. exports, manifest, validation, reconciliation, visual QA
python -m certpassly.phase1.build_exports <config>.json
python -m certpassly.phase1.make_source_manifest <config>.json
python -m certpassly.phase1.validate_structured_v1 <config>.json
python -m certpassly.phase1.reconcile <config>.json
python -m certpassly.phase1.visual_qa <config>.json

# 5. 27-scenario synthetic adversarial suite (independent of any real exam)
python -m certpassly.phase1.adversarial --base <scratch> \
    --upstream "<upstream>/scripts" --report-out <structured>/qa/adversarial-tests.json

# or everything at once (stages 3-4 orchestrated, with checkpoints):
certpassly phase1-extract --config <config>.json --upstream-scripts "<upstream>/scripts"
certpassly phase1-extract --config <config>.json --upstream-scripts "<upstream>/scripts" --dry-run
certpassly phase1-extract --config <config>.json --upstream-scripts "<upstream>/scripts" --resume   # guarded: re-verifies the source fingerprint first
```

Every command supports `--help`. `certpassly phase1-info` prints the toolkit
version, structured/v1 schema compatibility (including the
`typed_text_with_answer_image` extension) and the full pinned upstream SHA.

## Module map

| Module (python -m ...) | Role | Registry ID |
| --- | --- | --- |
| `certpassly.phase1.audit_source` | read-only source audit; identity gate | `phase1_source_audit` |
| `certpassly.phase1.make_pmap` | pdftohtml media -> PDF xref mapping | `phase1_media_pmap` |
| `certpassly.phase1.build_structured_v1` | build questions/pages/assets/indexes | `phase1_structured_builder` |
| `certpassly.phase1.build_exports` | deterministic + fail-closed export adapters | `phase1_export_builder` |
| `certpassly.phase1.make_source_manifest` | read-only artifact inventory | `phase1_source_manifest` |
| `certpassly.phase1.validate_structured_v1` | config-driven validation contract | `phase1_validator` |
| `certpassly.phase1.reconcile` | cross-walk of every count system | `phase1_reconciler` |
| `certpassly.phase1.visual_qa` | renders, contact sheets, visibility correlation | `phase1_visual_qa` |
| `certpassly.phase1.run_all` | stage orchestrator (checkpoint/resume) | `phase1_run_all` |
| `certpassly.phase1.adversarial` | 27 synthetic adversarial scenarios | `phase1_adversarial_suite` |

Shared helpers and version/compatibility metadata live in
`certpassly.phase1.p1common` and `certpassly.phase1.__init__`.

## Provenance labels and backward compatibility

Outputs record provenance labels (emitted README, source-manifest
`extraction_tools`, audit `tool`, export `regeneration_command`). Defaults keep
the **historical private-toolkit labels** so that a config from a previously
accepted extraction reproduces its outputs byte-identically. New runs should
set the optional `provenance` block in the config:

```json
"provenance": {
  "toolkit_label": "the config-driven certpassly.phase1 extraction toolkit (certpassly-exam-skill, candidate commit <full-sha>)",
  "commands_reference": "docs/PHASE1-EXTRACTION.md in mathorax1-hue/certpassly-exam-skill",
  "builder_script": "certpassly.phase1.build_structured_v1 (certpassly-exam-skill @ <full-sha>)",
  "audit_tool": "certpassly.phase1.audit_source (certpassly-exam-skill @ <full-sha>)",
  "exports_regeneration_command": "python -m certpassly.phase1.build_exports <config.json> (certpassly-exam-skill @ <full-sha>)"
}
```

## Migration from the private raw-exam toolkit

The private `tools/phase1-extraction/` scripts (15 files on the review branch)
are superseded by this package: same algorithms, same config schema, same
deterministic outputs (proven by byte-identical replay of accepted extractions
with their original configs). To migrate a private workspace:

1. Pin this public skill commit in the private config/lockfile.
2. Replace `python3 tools/phase1-extraction/<script>.py` invocations with the
   module commands above (or `certpassly phase1-extract`).
3. Keep per-exam configs; optionally add the `provenance` block for new runs.
4. Re-run validation/reconciliation — outputs must match the accepted layer.

The private repository should not keep a separately evolving copy of this
generic code (see the private tool-promotion policy); only narrowly justified
private adapters may remain.

## Troubleshooting and rollback

| Symptom | Cause | Action |
| --- | --- | --- |
| `audit` exit 2, `sha256 mismatch` | wrong/updated PDF, wrong manifest | re-verify the private manifest; never edit expected values to force a pass |
| `audit` exit 2, `encrypted` | password-protected PDF | stop; obtain the unencrypted owner original |
| `ModuleNotFoundError: fitz` | pdf extra not installed | `python -m pip install -e ".[phase1]"` once |
| `FATAL: directory does not exist` (adversarial) | wrong upstream path | pass the pinned checkout's `scripts/` dir; verify the pin SHA |
| `Unapproved upstream version` | checkout pin mismatch | stop and report; do not silently repin |
| stage fails mid-pipeline | genuine source/layout issue | inspect `run-checkpoint.json`; fix the cause; `--resume` after the fix |
| `source guard refused --resume/--start-from` (exit 3) | the source PDF changed/went missing, the config or upstream pin was edited, or the checkpoint is stale | nothing ran and the checkpoint is untouched; re-run from stage 0 WITHOUT the flags so the audit re-verifies the source |
| wrong toolkit version | unpinned checkout | `git checkout <full-sha>`; `certpassly phase1-info` |

**Rollback**: the toolkit only writes into the private `structured/v1` tree
and scratch workspaces; deleting that tree and re-running from the same config
is a complete rollback/rebuild. `git checkout` of the skill repo to the
previously reviewed SHA restores the prior engine. Nothing here touches source
PDFs, answer keys, release workflows or website state.

## Test evidence

- Public CI (stdlib-only): `python -m unittest discover -s tests -v`,
  `python scripts/verify_tool_registry.py`,
  `python scripts/check_public_safety.py` — synthetic fixtures only.
- Full-dependency environments additionally run the fitz-gated tests
  (audit identity gates, encrypted-PDF fail-closed, builder provenance).
- The 27-scenario adversarial suite (`certpassly.phase1.adversarial`) runs the
  REAL pinned extractor + REAL builder on SYNTHETIC PDFs; it requires the
  phase1/visual extras plus Poppler and Tesseract and is executed in a
  full private/local environment, not on the stdlib-only public runner.
- Real-exam acceptance runs happen only in the authorized private workspace
  (see the private raw-exam repository) and never in public CI.
