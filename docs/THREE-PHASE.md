# Three-phase exam workflow

This is the permanent path from an owner PDF to a CertPassly site v2 draft. Scripts run first. AI is a later, bounded hook.

## Repository roles

1. Public `mathorax1-hue/certpassly-exam-skill` holds shared scripts, tests and rules only. No owner PDFs, keys, OCR text or run outputs.
2. Public `mathorax1-hue/exam` is the working Actions repo. It checks out this skill and the pinned upstream pipeline. Public logs may contain counts and IDs only. Real owner exams are dispatched from private raw-exam so question text never appears in public logs.
3. Private `mathorax1-hue/raw-exam` stores the owner PDF (Git LFS), rights statement, extract, fidelity reports, research notes and drafts.
4. Private `mathorax1-hue/ready-exams` receives only drafts that passed every gate, each with a provenance note naming the raw-exam commit. Auto promotion is off.

## Upstream pin

The technical runner is the public upstream `msaqlainhaneef1/certpassly-exam-pipeline` at reviewed commit `d9b6bf67efb870019dd88caeffa90952b7e000d3` (tag v1.3.0). Do not vendor that source. Use `scripts/bootstrap_upstream.sh` or `certpassly upstream-run`.

## Phase 1: technical, no AI, no web

```
python scripts/prepare_exam_workspace.py --raw-dir /path/raw-exam/exams/CODE --workspace /path/work --exam CODE
certpassly-pipeline --exam CODE --root /path/work --offline
```

Stages: intake, extract (local Tesseract OCR), export (site v2 plus the fidelity gate), validate_site, package. A question is exported only when word coverage is complete, two OCR passes agree, exactly one type rule matches, and the key comes from the PDF. Held items stay in `export/cannot-convert.json` and `export/fidelity.json`.

## Phase 2: research worklist (AI is a hook)

```
python scripts/build_research_worklist.py --exam CODE --export-dir /path/work/out/CODE/export --output /path/work/out/CODE/phase-reports/research-worklist.json
```

This lists held items, `answer_not_found` questions, and exam facts that still lack a saved official URL, sha256 and verbatim quote. It does not call a paid model. If an official URL is already known, `scripts/capture_official_source.py` may download that allowlisted page into private storage. Drive and social links are not official sources.

## Phase 3: content gate, site import gate, promotion

```
python scripts/check_content_gate.py --site-file /path/work/out/CODE/CODE.site-format.v2.json --output /path/work/out/CODE/phase-reports/content-gate.json
python scripts/run_site_import_gate.py --sandbox /path/import-sandbox --site-file /path/work/out/CODE/CODE.site-format.v2.json --output /path/work/out/CODE/phase-reports/import-gate.json
python scripts/promote_ready_exam.py --exam CODE --site-file /path/work/out/CODE/CODE.site-format.v2.json --ready-root /path/ready-exams --raw-commit RAW_SHA --worklist ... --content-gate ... --import-gate ... --output ... --promote
```

Content writing is a documented hook. The gate checks authored explanations and page prose only, for typographic dashes, emoji, seller or competitor names, and review markup. Missing authored content blocks promotion.

The site import gate uses the real website importer from a throwaway copy of site commit `a3009daa5758a4401ceadd9cf765d8a36bff22bc`. That sandbox uses sqlite only, with `SITE_FORMAT_EXAM_V2=true` in its own `.env`. It must never use port 3306, the 8330 audit, production, or the original worktree. The importer command is `site-format:import` / `SiteFormatImporter`. Every exported question must be saved as a draft. A few questions are graded per type with `SiteFormatGrader`. This gate is required before promotion. GitHub Actions should skip it unless a private sandbox path is provided, because the website code does not belong in the public exam repo.

Promotion still requires `--promote` after every gate passes, including zero held items and official exam facts. Destination files include `provenance.json` and `PROVENANCE.md` with the raw-exam commit. `published` and `ready_for_publication` stay false.

## One-shot private runner

```
python scripts/run_three_phase.py --exam CODE --workspace /path/work --upstream vendor/certpassly-exam-pipeline --raw-dir /path/raw-exam/exams/CODE --sandbox /path/import-sandbox
```

Stdout is a counts summary only.
