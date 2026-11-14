# Non-AI image subsystem: operator runbook (Linux/WSL + Windows)

Everything below is executable as written. All fixtures in this repo are 100% synthetic; real owner PDFs and real extractions stay in PRIVATE workspaces (`raw-exam`), never in this public repository.

## 1. Install (once per machine / per pinned commit)

### Linux / WSL / macOS

```bash
mkdir -p certpassly-image-work && cd certpassly-image-work
git clone https://github.com/mathorax1-hue/certpassly-exam-skill.git skill
cd skill
git checkout zai/nonai-clean-simulator-media   # or the reviewed merge commit later
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[phase1,visual,dev]"
python -m pip check
python -m certpassly.media_prep doctor
```

### Windows (PowerShell)

```powershell
git clone https://github.com/mathorax1-hue/certpassly-exam-skill.git skill
cd skill
git checkout zai/nonai-clean-simulator-media
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[phase1,visual,dev]"
python -m pip check
python -m certpassly.media_prep doctor
```

If `Activate.ps1` is blocked: `Set-ExecutionPolicy -Scope Process RemoteSigned`, or call `.\.venv\Scripts\python.exe -m certpassly.media_prep ...` directly.

**System prerequisites** (not pip): Poppler (`pdftohtml`, `pdftoppm`) — needed only when `upstream.run_extract=true`; Tesseract — optional, advisory QC only; Git. On Debian/Ubuntu: `sudo apt-get install poppler-utils tesseract-ocr`. On Windows: install Poppler for Windows and add its `bin` to PATH, or use WSL.

**Do not** upgrade PyMuPDF past 1.26.x for convenience (1.28+ has a known rotated-page reading-order regression; see `docs/DEPENDENCIES.md`).

### Optional: the pinned upstream checkout (needed only for run_extract)

```bash
git clone https://github.com/msaqlainhaneef1/certpassly-exam-pipeline.git upstream
git -C upstream checkout --detach 13dea6bab662ab1c4bbf87017e912e519907c8bc
git -C upstream rev-parse HEAD   # must print 13dea6bab662ab1c4bbf87017e912e519907c8bc
```

The checkout is READ-ONLY: this skill calls `extract_owner_pdf.py` by subprocess and never copies or modifies upstream source (no confirmed redistributable LICENSE).

## 2. Verify the installation

```bash
python -m certpassly.media_prep doctor --json      # modules + system tools + pins
python -m unittest discover -s tests -v            # full suite (image extras installed)
python scripts/verify_tool_registry.py
python scripts/check_public_safety.py
python -m compileall -q scripts src
```

## 3. Try it on the synthetic example (no real exam data)

```bash
# build the synthetic workspace + config (prints nothing private; all fake)
python tests/media_prep_fixture.py --out /tmp/mp-demo

# doctor / scan / prepare / verify on the synthetic exam
python -m certpassly.media_prep doctor --json
python -m certpassly.media_prep scan    --config /tmp/mp-demo/media-prep-config.json --explain
python -m certpassly.media_prep prepare --config /tmp/mp-demo/media-prep-config.json --explain
```

Expected synthetic result (13 questions): 5 clean files written (`q002/q005/q007/q008/q012.png`), 7 blocked with reasons (`q003 MARKED_ONLY_REVIEW_REQUIRED`, `q004 SOURCE_IMAGE_LOW_RESOLUTION`, `q006 SOURCE_IMAGE_AMBIGUOUS`, `q009 SOURCE_IMAGE_BLURRY`, `q010 SOURCE_IMAGE_CORRUPT`, `q011 CLEAN_ASSET_MISSING`, `q013 SOURCE_IMAGE_LOW_CONTRAST`), and both `scan` and `prepare` exit **2** (blocked questions exist — that is the honest outcome, not an error).

One reproduce-a-block and one reproduce-a-pass, scripted end to end, live in `tests/test_media_prep_e2e.py` (`test_d01_scan_exit_code_and_counts`, `test_d06_offline_draft_zip_passes`, `test_d09_blocked_case_package_refused`).

## 4. Real (private) usage — one config per exam

Create `media-prep-config.json` in a PRIVATE workspace (never commit it or its outputs to this public repo):

```json
{
  "schema_version": "media-prep-v1",
  "exam_code": "XX-000",
  "source": {"pdf": "source.pdf", "expected_sha256": "<64 hex from the private manifest>", "expected_bytes": 123456},
  "upstream": {
    "repo": "msaqlainhaneef1/certpassly-exam-pipeline",
    "commit": "13dea6bab662ab1c4bbf87017e912e519907c8bc",
    "scripts_dir": "../upstream/scripts",
    "out_dir": "out",
    "run_extract": false
  },
  "output": {
    "clean_dir": "prepared/clean",
    "private_dir": "prepared/private",
    "manifest": "prepared/image-manifest.json",
    "inventory": "prepared/image-inventory.json"
  },
  "display": {"default_css_width": 640, "pixel_density_goal": 2.0},
  "privacy": {
    "allow_external_urls": false,
    "allowed_hosts": [],
    "require_package_integrity": true,
    "require_receipt": false,
    "manifest_key_env": "CERTPASSLY_MANIFEST_KEY",
    "source_receipt": "../exams/XX-000/manifest.json"
  }
}
```

All relative paths resolve against the CONFIG FILE's directory (not the CWD), so the same config works from any shell on Linux and Windows. `run_extract: false` reuses an existing upstream extraction; `true` (plus `scripts_dir`) lets `scan` run the pinned extractor itself.

The `privacy` keys added by the 2026-11-14 P0 correction: `require_package_integrity` (default true) refuses manifests without a valid package-level digest over ALL security-critical fields; `require_receipt` (default false) additionally demands a valid HMAC-SHA256 receipt - the key is read from the environment variable named by `manifest_key_env` (default `CERTPASSLY_MANIFEST_KEY`) and NEVER lives in code or the package; `source_receipt` optionally points at the exam's independently pinned source manifest (e.g. the private repository's `exams/<code>/manifest.json`) so the gate can bind the manifest's source PDF identity to it. To emit a receipt, export the key before `prepare`:

```bash
export CERTPASSLY_MANIFEST_KEY="<secret from your password manager>"   # Linux/WSL
# PowerShell: $env:CERTPASSLY_MANIFEST_KEY = "<secret>"
python -m certpassly.media_prep prepare --config media-prep-config.json  # writes integrity.receipt_sha256_hmac
```

Regardless of receipts, `verify-package` CONTENT-RE-VERIFIES every allowlisted member against the pinned source PDF: rendered crops are re-checked for answer/marker text (whole-page clips categorically refused) and raster members are re-matched to embedded PDF images and re-run through mark detection. A regenerated manifest wrapped around a leaky or marked image is therefore still refused.

Then:

```bash
python -m certpassly.media_prep scan    --config media-prep-config.json --output readiness.json --explain
python -m certpassly.media_prep prepare --config media-prep-config.json --explain
# build the draft package from prepared/clean + the manifest allowlist, then:
python -m certpassly.media_prep verify-package --config media-prep-config.json --package draft.zip --report vp-report.json
```

## 5. CLI reference and exit codes

| Command | Reads | Writes | Exit 0 | Exit 1 | Exit 2 | Exit 3 |
| --- | --- | --- | --- | --- | --- | --- |
| `doctor [--json] [--config C]` | environment, optional config | nothing | ready (or `--json`) | not ready | — | — |
| `scan --config C [--output F] [--json] [--explain] [--force-extract]` | PDF + upstream out | optional `--output` JSON | no blocked questions | bad config / missing PDF / SHA mismatch / extractor failure | ≥1 blocked question | — |
| `prepare --config C [--out-dir D] [--dry-run] [--json] [--explain]` | PDF + upstream out | `clean/`, `private/reviewer-only/`, manifest, inventory (nothing on `--dry-run`) | all eligible written | bad config / output inside upstream workspace | ≥1 blocked question | — |
| `verify-package --config C --package Z [--site-format DIR] [--report F] [--json]` | manifest + ZIP | optional `--report` JSON | package clean AND no scoring-key flags | missing package / not a ZIP | — | any privacy problem, manifest tamper, or learner-visible scoring keys |

Per-question details always come with `--explain`; machine JSON with `--json`.

## 6. Output directory tree (prepare)

```
prepared/
├── clean/                    # learner-eligible images ONLY (qNNN.png / qNNN.<ext>)
├── private/
│   └── reviewer-only/        # every answer_marked_reviewer_only source image
├── image-manifest.json       # image-manifest-v1 + integrity (entries_sha256 legacy, package_integrity_sha256, optional receipt_sha256_hmac)
└── image-inventory.json      # immutable per-file provenance (xref, pages, usages)
```

`prepare` is deterministic: re-running with the same inputs reproduces byte-identical manifest and image files (verified by test `test_d07_repeat_run_byte_identical`). Verify any two runs yourself:

```bash
sha256sum prepared/image-manifest.json prepared/clean/*
# run prepare again, then repeat; the hashes must match exactly
```

## 7. Troubleshooting / common mistakes

| Symptom | Cause and fix |
| --- | --- |
| `ERROR [ConfigError]: config schema_version must be 'media-prep-v1'` | Wrong/old config schema. Copy `examples/media-prep-config.synthetic.json` and adjust. |
| `ERROR [OperationalError]: source identity check failed: sha256 mismatch` | The PDF is not the one pinned in the config (or `expected_bytes` is stale). Re-take the SHA-256/bytes from the private manifest. Never "fix" by editing the expected hash without re-verifying the source. |
| `upstream extraction output missing ... and upstream.run_extract is false` | No `extracted/split.json` in `upstream.out_dir`. Either run the pinned upstream extractor yourself, or set `run_extract: true` + a valid `scripts_dir`. |
| `ERROR [OperationalError]: media-prep scan requires the pdf extra (PyMuPDF)` | Install the extras: `python -m pip install -e ".[phase1,visual]"`. |
| exit 2 with `SOURCE_IMAGE_LOW_RESOLUTION` on many questions | The source rasters are genuinely small. Do NOT "fix" by upscaling — that is refused by design. Options: re-scan at a higher native capture, or lower `display.default_css_width` ONLY if the real learner display is genuinely narrower (record the change in the private config provenance). |
| exit 2 with `SOURCE_IMAGE_AMBIGUOUS` | The upstream `answer_image_inferred` heuristic reassigned roles and no pair could prove which member is clean. Requires human visual review of that question's images (private). |
| `REVIEWER_ONLY_BINARY_IN_PACKAGE` on verify-package | The package contains bytes that match a marked/reviewer-only asset (renamed or re-embedded). Rebuild the package strictly from `prepared/clean/` + the manifest. |
| `NESTED_ZIP_REJECTED` | Nested archives are refused outright; flatten the package. |
| `SITE_SCORING_ARCHITECTURE_REVIEW_REQUIRED` | Learner-visible scoring keys found. This is an architecture issue, not a filter issue: the gate refuses to certify until the staging site's scoring behavior is reviewed. |
| Prepare wrote nothing but exited 0 | Nothing was blocked and nothing required an image? Check `--explain`: text-only questions need no image (`requires_image=false`). |
| Windows path issues | Use forward slashes in the config; all relative paths resolve against the config file's own directory. |
| exit 2 with `QUESTION_CROP_UNVERIFIED` | (P0 correction) The question's exhibit could not be bounded by its own marker/answer geometry (marker missing from the record or page, band too small/ambiguous, or the crop would cover ≥60% of the page). Human review decides; the engine never falls back to a page render. |
| exit 2 with `ANSWER_TEXT_IN_RENDER` | (P0 correction) A would-be render region contains `Correct Answer:` / explanation text. Refused, never blacked out. |
| exit 3 with `RASTER_PROVENANCE_MISMATCH` | An allowlisted raster member's pixels do not match any image embedded in the pinned source PDF. Rebuild the package from a fresh `prepare`. |
| exit 3 with `MARKED_IMAGE_IN_ALLOWLIST` | Mark detection on the SHIPPED pixels found pen-like marks even though the manifest claimed clean. Re-run `prepare`; if it persists, the question needs human review. |
| exit 3 with `RECEIPT_MISSING` / `RECEIPT_HMAC_MISMATCH` | `require_receipt=true` but the manifest has no HMAC receipt, or the key in the `manifest_key_env` variable does not match the one used at `prepare` time. |
| exit 3 with `SOURCE_RECEIPT_MISMATCH` | The manifest's source PDF identity is not the one pinned in `privacy.source_receipt`. Either the manifest came from a different exam or the pinned receipt is stale. |

## 8. Performance notes

Rough single-run cost on the 13-question synthetic workspace: `scan` ≈ 2–3 s, `prepare` ≈ 3–4 s, `verify-package` < 0.5 s (linear in package size). Costs scale with the number of embedded images (per-image decode + mark detection ≈ 20–60 ms at 900×420) and with 300-DPI page renders (≈ 0.3–1 s per rendered page, ~10–30 MB peak per render). The AB-730 real trial (75 pages, 87 images, 92 questions) completes `scan`+`prepare` in well under a minute single-threaded; see the private report for measured numbers.

## 9. Version and registry

- Toolkit version: `certpassly-media-prep 1.1.0` (2026-11-14 P0 security correction; see `docs/NONAI-SIMULATOR-IMAGES.md`) (`src/certpassly/media_prep/__init__.py`).
- Registry entries: `media_prep_source_scan`, `media_prep_selection_prepare`, `media_prep_privacy_gate`, `media_prep_doctor` in `config/tool-registry.json` (validated by `scripts/verify_tool_registry.py`).
- Schema versions: `image-readiness-v1`, `image-manifest-v1`, `media-prep-v1` (`src/certpassly/media_prep/schemas/`, validated by tests `test_d03`/`test_d04`).
- Any change to exit codes, reason codes or schemas is a contract change: update this doc, the test plan, the registry entry and add a `knowledge/ENGINEERING-HISTORY.md` record, then run the full synthetic suite.
