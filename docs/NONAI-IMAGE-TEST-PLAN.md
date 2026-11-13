# Non-AI image subsystem: test plan and executed results

**Everything here runs on 100% synthetic data.** No real exam PDF, image, key or private log is used in this repository or in public CI. The real AB-730 source-only trial runs in the PRIVATE `raw-exam` workspace with its own evidence trail.

## How to run

```bash
# full suite (needs image extras: python -m pip install -e ".[phase1,visual]")
python -m unittest discover -s tests -v

# just the media-prep suites
python -m unittest tests.test_media_prep_inventory tests.test_media_prep_quality \
                   tests.test_media_prep_privacy tests.test_media_prep_e2e \
                   tests.test_media_prep_cli -v

# real-pinned-upstream integration (optional; clones the pinned commit first)
git clone https://github.com/msaqlainhaneef1/certpassly-exam-pipeline.git /tmp/upstream
git -C /tmp/upstream checkout --detach 13dea6bab662ab1c4bbf87017e912e519907c8bc
CERTPASSLY_UPSTREAM_SCRIPTS=/tmp/upstream/scripts \
  python -m unittest tests.test_media_prep_e2e.RealUpstreamIntegrationTests -v
```

Without image extras installed the media-prep tests SKIP (never silently pass); the media-prep CI job installs the extras and FAILS if any of them was skipped.

## Matrix A — source/processing (order requires ≥12; 21 executed)

`tests/test_media_prep_inventory.py` — `ProcessingMatrixTests` (a01–a14) + `MarkDetectorUnitTests` (7):

| # | Scenario | Expected |
| --- | --- | --- |
| a01 | clean+marked matched pair chooses clean | Priority C, clean member, role correction recorded |
| a02 | only marked blocks | BLOCKED `MARKED_ONLY_REVIEW_REQUIRED` |
| a03 | clean embedded raster preserved byte-identically | candidate SHA == source SHA |
| a04 | PDF vector rendered at true high resolution | 300-DPI render ≥3100px wide |
| a05 | annotation omitted without dropping content | annotation excluded, render differs |
| a06 | flattened annotation remains flagged | Priority B honestly not applicable → BLOCKED |
| a07 | rotated page crop orientation | /Rotate 90 renders in displayed orientation |
| a08 | multipage item | exhibit on second page still resolves |
| a09 | multiple question and answer images | clean member chosen; roles correct |
| a10 | missing/corrupt image | BLOCKED `SOURCE_IMAGE_CORRUPT`, no crash |
| a11 | image roles ambiguous (heuristic swap) | BLOCKED `SOURCE_IMAGE_AMBIGUOUS` |
| a12 | source asset SHA mismatch (re-encoded media) | BLOCKED `SOURCE_ASSET_SHA_MISMATCH` |
| a13 | typed answer + marked image stays reviewer-only | marked image never learner-eligible |
| a14 | no fake superresolution | native dims preserved; tiny stays tiny |
| u1–u7 | detector units: ring/X/highlight-box/underline detected; clean exhibit, gray-bordered chart and colored pen box classified correctly | conservative, deterministic |

## Matrix B — quality (order requires ≥8; 10 executed)

`tests/test_media_prep_quality.py` (b01–b10): native vs display geometry; pixel-density goal at desktop (640px, advisory `BELOW_PIXEL_DENSITY_GOAL`) vs mobile (450px, goal met); tiny image hard-fail; blur hard-fail; low contrast hard-fail; transparent PNG flattened before measurement; histogram clipping recorded as advisory (legitimate white-background exhibits not failed); extreme aspect hard-fail; lossless output preservation (PNG byte-identical copy, JPEG→PNG single re-encode, same pixel size); Unicode filenames handled (`name_safe=false`, output re-named `qNNN.png`).

## Matrix C — privacy negative/adversarial (order requires ≥12; 17 executed)

`tests/test_media_prep_privacy.py` (c00 baseline PASS + c01–c15): marked screenshot swapped into an exhibit slot (caught by known reviewer SHA before the manifest mismatch); same marked SHA renamed; re-encoded marked image falsely labeled clean (refused by provenance/allowlist, not perceptual hash); manipulated manifest SHA (integrity hash break); private answer binary by unrelated path; nested ZIP; path traversal; symlink member; external URL; unknown checksum image; hidden scoring key (`SITE_SCORING_ARCHITECTURE_REVIEW_REQUIRED`, CLI exit 3); missing image with sidecar reference; duplicate asset identity; raw `media/src` file shipped; `is_published:true` in a draft; plus the legitimate-asset-deduplication negative control (same bytes under two allowlisted names MUST pass).

## Matrix D — end-to-end and reproducibility (order requires ≥8; 13 executed)

`tests/test_media_prep_e2e.py` (d01–d11 + 2 opt-in integration): scan exit code and honest counts; prepare writes manifest + exactly the 5 clean files; manifest validates against `image-manifest-v1`; readiness records validate against `image-readiness-v1`; learner refs point to manifest SHAs (recomputed from bytes); an offline synthetic draft ZIP passes end-to-end (exit 0); a second full prepare is byte-identical (manifest + images); pairing is independent of file naming order; a blocked question's image in a package is refused (exit 3); Windows-style separators and traversal refused (exit 3); manifest integrity hash is canonical. Integration (env-gated): the REAL pinned `extract_owner_pdf.py` runs on the synthetic PDF and `scan`/`prepare` consume its real output; `ensure_upstream_output` fails closed when the extractor is missing and `run_extract` is false.

## Matrix E — integration (honest)

- Existing public suite (23 pre-existing test files) must stay green: `python -m unittest discover -s tests -v`.
- `python scripts/verify_tool_registry.py`, `python scripts/check_public_safety.py`, `python -m compileall -q scripts src`, `certpassly doctor --json` — all in CI.
- **`STAGING_IMPORTER_UNTESTED` / `SIMULATOR_IMAGE_UI_UNTESTED`**: no staging environment was connected for this implementation. Real simulator rendering and live importer acceptance remain separate, explicitly untested gates — no claim is made here.

## Executed result snapshot (this branch)

Run with Python 3.12.16, PyMuPDF 1.26.7, Pillow 11.3.0, numpy 2.1.3, opencv-python-headless 4.13.0, jsonschema 4.26.0 on Linux:

| Suite | Tests | Result |
| --- | --- | --- |
| tests.test_media_prep_inventory | 21 | OK |
| tests.test_media_prep_quality | 10 | OK |
| tests.test_media_prep_privacy | 17 | OK |
| tests.test_media_prep_e2e | 13 (2 skipped without env) / 13 OK with `CERTPASSLY_UPSTREAM_SCRIPTS` | OK |
| tests.test_media_prep_cli | 13 | OK |
| media-prep total | **74** (all executed; 2 env-gated integration tests additionally verified locally with the real pinned checkout) | **OK** |

Determinism: `test_d07_repeat_run_byte_identical` proves a full second `prepare` reproduces byte-identical manifest and image files. The CI job re-runs the whole matrix on every push/PR.
