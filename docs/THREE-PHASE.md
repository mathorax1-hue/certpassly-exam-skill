# Three-phase exam workflow

This is the permanent path from an owner PDF to a CertPassly site v2 draft. Scripts run first. AI is a later, bounded hook.

## Repository roles

1. Public `mathorax1-hue/certpassly-exam-skill` holds shared scripts, tests and rules only. No owner PDFs, keys, OCR text or run outputs.
2. Public `mathorax1-hue/exam` is the working Actions repo. The heavy job runs there so minutes bill to the public repository. It checks out private raw-exam with a PAT secret stored in exam, this skill, and the pinned upstream pipeline. Public logs print only counts and pass/fail. A leak-check step scans the captured run log and the published job log for question text, PDF media names, and secret prefixes, and fails the run if a match is found. It never prints the matching text. Start a run from private raw-exam (default) or by owner dispatch on exam. There is no pull_request trigger.
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

Items held only for OCR quality get one automatic retry: the cropped image is enhanced at about 3x (or a PDF page is rasterised at 350 dpi when there is no image), then both OCR passes run again. The item is exported only if the same strict fidelity gate passes. Each attempt is logged in `export/ocr-retry.json`. If that enhance retry still holds the item, a second scripted pass crops the question region from a 400 dpi PDF page render and reruns the same gate. If both scripted passes still hold the item, the AI vision hook may transcribe the held images. The hook stays off by default (`provider` none). The private raw-exam caller can enable provider groq. Groq uses model `qwen/qwen3.8-27b` at temperature 0, a strict transcription prompt, a timeout, retries, and a per-run call cap (default 50). On HTTP 429 it reads Retry-After or x-ratelimit-reset-tokens, or parses a "try again in Xs" message, waits that long (capped at 65 seconds, at most two waits per item), and retries. Calls are paced to a 6000 input-tokens-per-minute budget (of Groq's 7000 ITPM). Wait counts are stored in `export/ai-vision.json`. The API key is read only from `GROQ_API_KEY` and is never logged. Committed `exams/CODE/review/ai-reads.json` files are used unless the run sets `use_committed_ai_reads=false` (or `CERTPASSLY_USE_COMMITTED_AI_READS=false`). AI text is accepted only when every OCR word at confidence 90 or above from both passes appears in the AI text in order, the PDF text-layer words are covered, and type and key rules pass. Accepted items export with `reviewer_needed` true. The provenance note is stored in `export/ai-vision.json`, not in site-file fields the schema forbids. Otherwise the item stays on the review sheet with the AI text as a suggestion only. Every item that is still held is written to `export/review-sheet.json`, `.md` and `.html`, with the image path, OCR text, PDF text, hold reason, and empty `owner_text` / `owner_decision` fields. Those fields are never auto-filled.

Owner corrections are committed at `exams/CODE/review/owner-corrections.json` in raw-exam and are copied into the workspace `review/` folder. A row is applied only when `owner_decision` and a structured stem are both filled. Corrected items are exported as `owner_checked` and must still pass schema and type rules.

## Phase 2: research worklist (AI is a hook)

```
python scripts/build_research_worklist.py --exam CODE --export-dir /path/work/out/CODE/export --output /path/work/out/CODE/phase-reports/research-worklist.json
```

This lists held items, `answer_not_found` questions, and exam facts that still lack a saved official URL, sha256 and verbatim quote. It does not call a paid model. If an official URL is already known, `scripts/capture_official_source.py` may download that allowlisted page into private storage. Drive and social links are not official sources.

## Phase 3: content gate, site import gate, promotion

```
python scripts/check_content_gate.py --site-file /path/work/out/CODE/CODE.site-format.v2.json --output /path/work/out/CODE/phase-reports/content-gate.json
python scripts/map_exam_domains.py --site-file /path/work/out/CODE/CODE.site-format.v2.json --raw-dir /path/raw-exam/exams/CODE --output /path/work/out/CODE/phase-reports/domain-mapping.json
python scripts/run_site_import_gate.py --sandbox /path/import-sandbox --site-file /path/work/out/CODE/CODE.site-format.v2.json --output /path/work/out/CODE/phase-reports/import-gate.json
python scripts/promote_ready_exam.py --exam CODE --site-file /path/work/out/CODE/CODE.site-format.v2.json --ready-root /path/ready-exams --raw-commit RAW_SHA --worklist ... --content-gate ... --domain-gate ... --import-gate ... --output ... --promote
```

Content writing is a documented hook. The gate checks authored explanations and page prose only, for typographic dashes, emoji, seller or competitor names, and review markup. Missing authored content blocks promotion.

Domain mapping uses only an official domain list that is already saved with a URL, sha256 and a verbatim quote (for example `official/domains.csv` plus `official/receipt.json`). If that list is not saved, every question is kept and flagged `domain_unmapped`, and promotion is blocked. The script never guesses a domain name silently.

The site import gate is a required local pre-promotion step. It is not run in GitHub Actions, because the website code must not be stored in the user's GitHub repositories. Run it on a throwaway copy of site commit `a3009daa5758a4401ceadd9cf765d8a36bff22bc`. That sandbox uses sqlite only, with `SITE_FORMAT_EXAM_V2=true` in its own `.env`. It must never use port 3306, the 8330 audit, production, or the original worktree. The importer command is `site-format:import` / `SiteFormatImporter`. Every exported question must be saved as a draft. A few questions are graded per type with `SiteFormatGrader`. The import-gate report must include the sha256 of the exact site v2 file being promoted. `promote_ready_exam.py` refuses promotion if the report is missing, is not `passed`, or the sha256 does not match that file.

Promotion still requires `--promote` after every gate passes, including zero held items, official exam facts, a passing local import-gate report with a matching sha256, and no `domain_unmapped` questions. Destination files include `provenance.json` and `PROVENANCE.md` with the raw-exam commit. `published` and `ready_for_publication` stay false.

## One-shot private runner

```
python scripts/run_three_phase.py --exam CODE --workspace /path/work --upstream vendor/certpassly-exam-pipeline --raw-dir /path/raw-exam/exams/CODE --sandbox /path/import-sandbox
```

Stdout is a counts summary only.

## Upstream patch applied in Actions

The public three-phase workflow (and the disabled-by-default private fallback) checks out pinned upstream `v1.3.0` (`d9b6bf67efb870019dd88caeffa90952b7e000d3`) and then applies every `patches/upstream/v1.3.0-*.patch` in name order:

1. `v1.3.0-lead-ligature-complete-words.patch` stops `text_repair.lead()` from turning complete words such as `replace` into `fireplace`.
2. `v1.3.0-ocr-retry-review-sheet.patch` adds the OCR retry pass, the review sheet, and owner-corrections support.
3. `v1.3.0-page-region-ai-vision.patch` adds the 400 dpi page-region retry and the AI vision hook (off by default; committed `ai-reads.json` files are still read). The AI acceptance rule uses high-confidence words from the original OCR passes, not a later failed retry.
4. `v1.3.0-page-region-ai-vision2-groq.patch` adds the Groq provider. It stays off unless a private runner sets provider groq. Public exam dispatch stays refused and does not enable Groq.
5. `v1.3.0-page-region-ai-vision3-groq-images.patch` stitches more than 3 held crops into one image, because the Qwen model rejects a request with more than 3 images, and prefers the 400 dpi crop files.
6. `v1.3.0-question-type-builders.patch` reads every question type the site accepts from the PDF, scripts only: Yes/No and choice grids, drop-down answer areas, image hotspots, ordering, matching, categorization, drag and drop, scenario and case study groups. See [question types](QUESTION-TYPES.md).
7. `v1.3.0-ratelimit-groq-429.patch` waits and retries on Groq HTTP 429 using Retry-After, x-ratelimit-reset-tokens, or a try-again message (capped, at most two waits per item), and paces calls to a 6000 ITPM budget so later items are less likely to hit the limit.

The fidelity coverage gate stays strict. The same patches are bundled for a push to `msaqlainhaneef1/certpassly-exam-pipeline`.
