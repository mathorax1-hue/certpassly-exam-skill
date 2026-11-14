# AB-900 source-fidelity difference audit (technical phase only)

This generic tool belongs in the public reusable skill. **Never commit private PDF, questions, answers, per-question reports or reviewer images here.**

## What it checks

`scripts/audit_pilot_source_fidelity.py` compares the archived and freshly extracted `split.json` by question key and by `stem`, `options`, and `answer_raw`. Its JSON report emits fingerprints rather than private text. Answer-key differences are recorded for later research/key verification; they are not auto-corrected. It inventories V2 files and detects some missing learner content or reviewer-media references. Existing source flags are retained, never automatically cleared.

This is **not** a PDF visual verifier, official source check, schema validator, complete renderer audit, or website importer test. A 0 exit status indicates only that the scripted comparison found no outstanding issues; it does not imply independent PDF fidelity.

## Run locally against private data

```bash
python scripts/audit_pilot_source_fidelity.py \
  --archive-split /private/raw/exams/AB-900/research-archive/AB-900-package/AB-900-package/AB-900/extracted/split.json \
  --fresh-split /private/ab900-fresh/extracted/split.json \
  --v2-dir /private/raw/exams/AB-900/technical-v2-pilot/question-v2 \
  --cannot-convert /private/raw/exams/AB-900/technical-v2-pilot/cannot-convert.json \
  --output /private/raw/exams/AB-900/technical-v2-pilot/source-field-diff.json
```

The tool intentionally exits 2 with unresolved fidelity flags, which is a **correct safety outcome**, not a reason to mark the workflow publication-ready.

Run synthetic tests:

```bash
python -m unittest tests/test_audit_pilot_source_fidelity.py -v
```

## Human-readable technical verification queue

1. Review all differences by original PDF page, question, stem and options. Record PDF page number, exact corrected structure and source evidence, preserving original values until adjudicated.
2. For every blocked dropdown, matrix, hotspot or image-based question, verify all text, labels, cells, choices, slot IDs, interaction targets and semantic order against private source evidence. Represent it with native HTML/CSS/SVG and Question Format V2, not an answer-area screenshot.
3. Preserve answer-related warnings separately; do not research, replace, infer or expose answer keys in the current technical-only pass.
4. Run pinned upstream JSON schema and registry validation, snapshot reproducibility checks, HTML/SVG sanitization, private reference exclusions, accessibility and interaction tests, and importer contract dry-run.
5. Only after individually resolving source-fidelity flags in the **private** manifest can draft technical eligibility be recomputed. Schema success or a green workflow alone never grants approval.

## Boundaries

No live import, main-branch merge, editorial approval, answer research, release promotion or publication. Keep evidence and exact question text in `raw-exam`; keep only generic code and synthetic fixtures in `certpassly-exam-skill`.

## Additional interaction checker

The reusable command below checks every V2 draft's learner payload, type-specific
choice/dropdown/matrix structure, slot-marker correspondence, unsafe HTML
patterns, and possible private answer-media exposure. It creates a technical
inventory in the private pilot directory without altering keys or source text.

```bash
python scripts/audit_v2_interaction_structure.py \
  --v2-dir /private/raw/exams/AB-900/technical-v2-pilot/question-v2 \
  --output /private/raw/exams/AB-900/technical-v2-pilot/interaction-structure-audit.json
python -m unittest tests/test_audit_v2_interaction_structure.py -v
```

A zero-error automated interaction inventory is necessary but not sufficient:
browser rendering, accessibility, original source comparison, server-side answer
separation and the actual website importer still require separate verification.

## Private PDF text evidence (source-check assistance, not fidelity approval)

For flagged questions with recorded PDF page numbers, the tool
`scripts/audit_private_pdf_text_evidence.py` reads the PDF text layer and
uses OCR only when the page text layer is sparse. It compares significant
tokens from the archived structured learner content with those pages.
No screenshot is emitted to the simulator. The report keeps page number,
PDF/OCR method, overlap statistics and a small unmatched-token sample.

```bash
python scripts/audit_private_pdf_text_evidence.py \
  --pdf "/private/raw/exams/AB-900/source/AB-900 (89 Questions).pdf" \
  --questions "/private/raw/exams/AB-900/research-archive/AB-900-package/AB-900-package/AB-900/questions.json" \
  --cannot-convert "/private/raw/exams/AB-900/technical-v2-pilot/cannot-convert.json" \
  --output "/private/raw/exams/AB-900/technical-v2-pilot/pdf-source-text-evidence.json"
```

Requires `pdftotext`, `pdftoppm` and, for OCR fallback, `tesseract`.
Retain the output only in the private exam repository. This is a weak
machine-generated text-evidence signal; **never** clear a question's source
review flag solely because a high proportion of words matched. Verify
all cells, choices, full question instructions, diagrams, and interaction
semantics directly against the original PDF.

## Documented source replacements

Use `--archive-question-bank /private/.../questions.json` with the
`audit_pilot_source_fidelity.py` command to classify explicit
`owner_question_replaced` + `SUPERSEDED` + `original_editorial_id`
metadata as documented original CertPassly editorial replacements.
An authored replacement does not need to match the PDF question it
superseded. Neither the replacement provenance nor passing schema
checks constitutes factual answer approval.

## Offline V2 importer-contract projection

The reusable `scripts/dry_run_question_v2_import_contract.py` creates an
identity-and-hash report for all V2 questions. It maps `learner` into a
candidate-only public-view shape and computes a separate server-answer digest.
It deliberately emits **no answer keys** and does not import into the site.
Every question on `cannot-convert.json` remains `source_review_blocked`.

```bash
python scripts/dry_run_question_v2_import_contract.py \
  --v2-dir /private/raw/exams/AB-900/technical-v2-pilot/question-v2 \
  --cannot-convert /private/raw/exams/AB-900/technical-v2-pilot/cannot-convert.json \
  --output /private/raw/exams/AB-900/technical-v2-pilot/offline-importer-projection.json
```

Run the synthetic tests with
`python -m unittest tests/test_dry_run_question_v2_import_contract.py -v`.
Passing the offline projection proves neither a real site importer nor
database persistence, encryption, browser interaction, deployment, or release
security. Those tests must be performed against the actual authorized
website/staging contract in a later controlled step.

## Reproducible source-image repairs and scoped screenshot-shape evidence

Keep **all** source images, correction ledgers, and generated reports in the
private raw-exam repository. The publicly reusable scripts are:

- `scripts/apply_source_visual_fidelity_patches.py`: validates each original
  answer-area image SHA-256 before correcting the native learner prompt, matrix
  rows, or converting a source navigation menu to an explicit single-choice
  control. The menu migration retains the pre-existing owner answer selection
  through an audited ID remap; it does not independently research its accuracy.
- `scripts/apply_verified_exhibit_transcriptions.py`: validates original
  exhibit image bytes against SHA-256 in the private transcription ledger,
  then adds inspected source facts as HTML without modifying the answer.
- `scripts/audit_source_screenshot_shapes.py`: validates the **original
  owner PDF SHA-256**, source screenshot existence/hashes, reviewer-recorded
  question type, option/row counts and key learner-visible source facts.
  Its `scoped_shape_pass` does not assert full source PDF transcription.
- `scripts/audit_visual_transcription_crosscheck.py`: compares generated V2
  structures against the **historical** authored visual-transcription ledger.
  When a new, source-pixel-reviewed correction replaces an old inaccurate
  ledger entry, the historical crosscheck reports an expected difference.
  Preserve the old baseline and the new correction receipt rather than
  reverting the corrected learner content.

Private pilot repeatability is implemented in
`raw-exam/.github/workflows/ab900-one-pdf-technical-v2.yml`. Its workflow
checks private evidence under `exams/AB-900/evidence/` and saves generated
receipts under `exams/AB-900/technical-v2-pilot/`.

Run the public synthetic tests with:

```bash
python -m unittest tests.test_apply_source_visual_fidelity_patches \
  tests.test_apply_verified_exhibit_transcriptions \
  tests.test_audit_source_screenshot_shapes \
  tests.test_audit_visual_transcription_crosscheck -v
```

**Scope boundary:** historical answer-area screenshot matching, visible
exhibit transcriptions, V2 schema and local importer projections do not prove
complete question wording, browser accessibility, site API reveal security,
database imports, or server-side encryption. Keep source-fidelity and website
staging gates explicitly blocked until those properties are actually tested.
No production deployment, approval or answer research is authorized here.
