# Non-AI clean simulator images: design, roles and security boundary

**Module:** `certpassly.media_prep` (toolkit `certpassly-media-prep` 1.1.0)
**Upstream pin:** `msaqlainhaneef1/certpassly-exam-pipeline@13dea6bab662ab1c4bbf87017e912e519907c8bc` (read-only; never vendored — its root has no confirmed redistributable LICENSE)
**Schemas:** `image-readiness-v1` (scan), `image-manifest-v1` (prepare), `media-prep-v1` (config)

> **2026-11-14 P0 SECURITY CORRECTION** (director audit, order
> `ZAI-PIPELINE-001-T1-IMG-SKILL-P0`): the old Priority-B *vector variant*
> rendered the WHOLE PAGE and a real AB-730 learner image (q074, page 59)
> was proven to expose neighbouring questions' `Correct Answer:` key lines.
> Whole-page renders are now categorically impossible: every rendered
> learner image is an EXACT, source-verified exhibit crop (see Priority B
> below), the render-region verifier blocks `QUESTION_CROP_UNVERIFIED` /
> `ANSWER_TEXT_IN_RENDER` (exit 2), a latent rotated-page clip bug was fixed,
> the privacy gate now FAILS (not just flags) on scoring keys, and manifest
> trust was rebuilt on package-level digests + optional external HMAC
> receipts + pinned-source CONTENT re-verification of every allowlisted
> member. Full details inline below.

This module is a SMALL, DETERMINISTIC image-quality/privacy extension on top of the pinned 15-stage upstream conversion engine. It does NOT replace that engine, does not re-extract PDFs itself, and does not authorize anything. Where this document says BLOCK, the CLI says exit 2 with a stable reason code — never a guess, never a silent pass.

## Purpose and non-goals

Goal: for every question in an upstream extraction, produce a **provably unmarked, genuinely high-resolution learner image** or an **honest blocker** — and make it mechanically impossible for marked/reviewer-only media to reach a learner package.

Hard non-goals (violating any of these is a bug, not a feature):

- No AI, no OCR-created answer content, no generative restoration, no inpainting (OpenCV or otherwise), no upscaling presented as restored detail, no blind erasure of circles/check marks.
- No reimplementation of the upstream extractor. `scan` either consumes an existing `<out>/extracted/split.json` or runs the pinned `extract_owner_pdf.py` itself via subprocess (config `upstream.run_extract`).
- No research, no answer writing, no publication, no release authority, no network access.

## The four immutable roles

Every source image gets exactly one `verified_role` in the manifest:

| Role | Meaning | Learner package |
| --- | --- | --- |
| `source_original_private` | The original source binary (SHA-256, bytes, native size, PDF page/xref, usage role). | Never directly |
| `answer_marked_reviewer_only` | Marked answer reference (detected marks, answer-area role, or marked member of a pair). | NEVER — private dir only |
| `question_clean_candidate` | Verified unmarked source, or a clean member of a verified pair, or a self-verified annotation-free render. | Yes, via allowlist |
| `unknown_unverified` | Ambiguous role, broken provenance, heuristic-swap uncertainty, undecodable image. | No — BLOCK |

Role precedence (implemented in `selection._finalize_roles`): decode/xref failure → chosen candidate → unmarked verified question image → clean pair member → detected marks → assigned answer role → unknown.

## The strict Priority A/B/C/D selection hierarchy

**Priority A — direct clean source.** An upstream `question_images` entry qualifies only when ALL hold: (1) its bytes (or exact pixels) map to a real PDF image xref — same contract as the phase1 pmap; (2) the upstream assignment was NOT produced by the `answer_image_inferred` heuristic swap (that heuristic moves the last question image into `answer_images` when the "Correct Answer:" line is empty — it is upstream's own inference, not ground truth); (3) machine mark detection finds no pen-like selection marks. Lossless sources are copied **byte-identically**; lossy JPEG sources are decoded and re-saved once as PNG (no repeated lossy generations).

**Priority B — annotation-free render (self-verified, EXACT CROP ONLY).** Two variants — both now content-verified against the page text layer so no answer-key text can ever appear in a learner render:

- *Annotation variant*: the question image is marked AND its PDF page carries real annotations overlapping the image placement. The image's own placement rect (rotation-corrected) is rendered at 300 DPI with `annots=False`; the render must (a) differ from the with-annotations render (the annotations actually contributed pixels), (b) contain no detected marks itself, and (c) pass the render-region verifier: no `QUESTION <n>` marker, `Correct Answer:` line or explanation/section text may intersect the rendered region, and the region must lie inside the question's own marker/answer-verified band — else `QUESTION_CROP_UNVERIFIED` / `ANSWER_TEXT_IN_RENDER` (exit 2). If the marks were flattened INTO the raster, the render still shows them, the checks fail, and Priority B is honestly recorded as not applicable — `annots=False` does nothing for flattened marks and this toolkit never claims otherwise.
- *Vector variant (exact exhibit crop — P0 correction)*: the exhibit is DRAWN in the PDF, not embedded. The crop is computed by `exhibit_crop.question_exhibit_crop` from SOURCE geometry, never from a page-sized rect: it is the union of the question's OWN non-background vector drawings (near-white un-stroked page chrome and page-wide boxes are excluded), bounded on both sides by the question's own `QUESTION <n>` marker and the next boundary in the verified reading direction (next marker / its own `Correct Answer:` line / end of content). The reading direction is established EMPIRICALLY (marker-number order first, then line stacking, rotation last). A crop that intersects any marker or answer/explanation line — or covers ≥60% of the page or spans the whole page in both axes — is BLOCKED, not blacked out or trimmed further. The crop renders at 300 DPI (true added pixels for vector/text content, unlike an embedded raster, which cannot gain source pixels by re-rendering — the native embedded resolution is a hard ceiling, recorded per candidate). Mark detection still runs on the rendered pixels: vector-DRAWN pen marks cannot be distinguished from legitimate table borders and are a documented out-of-scope limitation (`VECTOR_PEN_MARK_UNDETECTABLE`) — they are recorded, never assumed clean. Both the display-space and unrotated clip rects are recorded in the manifest so the privacy gate can independently re-verify the geometry against the pinned source PDF.

> The old `clip = tuple(page.rect)` whole-page fallback is REMOVED. Rendering a whole page as a learner image is now impossible by construction: the verifier refuses any region spanning the whole page in both axes (and the synthetic regression `test_d12`/`test_c16` proves a regenerated manifest around a leaky whole-page render is still refused by the gate).

**Priority C — paired clean member.** When the same exhibit appears twice (typically question + answer copy), conservative ORB+RANSAC registration (≥25 inliers, ≥0.55 inlier ratio, bounded scale/translation) proves the pair, mark detection identifies the marked member, and the ALREADY-CLEAN member becomes the learner candidate with the role correction recorded (`PAIR_ROLE_CORRECTION`). The pair diff is ADVISORY: it can never erase anything and never fabricates a clean image from a marked one.

**Priority D — block.** No provable clean source → no learner image, one of: `CLEAN_ASSET_MISSING`, `MARKED_ONLY_REVIEW_REQUIRED`, `SOURCE_IMAGE_AMBIGUOUS`, `SOURCE_IMAGE_LOW_RESOLUTION`, `SOURCE_IMAGE_BLURRY`, `SOURCE_IMAGE_LOW_CONTRAST`, `SOURCE_IMAGE_TINY`, `SOURCE_IMAGE_ASPECT_EXTREME`, `SOURCE_ASSET_SHA_MISMATCH`, `SOURCE_IMAGE_CORRUPT`, `QUESTION_CROP_UNVERIFIED` (exhibit bounds cannot be source-verified: no usable marker/band, missing `source_number`, ambiguous reading direction, or a crop that would swallow markers/neighbours), `ANSWER_TEXT_IN_RENDER` (a would-be render region contains answer-key text).

## Render-region verification (the P0 invariant)

Every would-be learner render — both Priority-B variants — is verified against the PINNED source PDF text layer before a single pixel is shipped, by `exhibit_crop.verify_render_clip`:

1. NO question marker (its own or any neighbour's) may intersect the rendered region;
2. NO `Correct Answer:` / `Explanation` / `Section` / `References` line may intersect it;
3. no answer/marker/explanation TEXT may lie inside it (text-layer regex as an additional fail-closed guard — sufficient here because renders draw the PDF's own vector/text content, not flattened scans);
4. a region spanning the whole page in both axes is categorically unverifiable;
5. when the question's marker is on the page, the region must lie inside the marker/answer-verified band.

The same verifier runs AGAIN inside `verify-package` on every rendered allowlisted member, so a fully regenerated manifest wrapped around a leaky render is still refused (see the trust model below).

## Mark detection model (what it catches and what it cannot)

`marking.detect_marks` (OpenCV connected components, `opencv-connected-components-v3`) flags:

- `pen_shape` — hollow shapes spanning ≥80% of bbox rows AND columns (circles, ellipses, boxes, wide rings) with pen-like color; plus thin crossing strokes (X marks) that fill their core;
- `solid_stroke` — near-solid elongated strokes (underlines, pen lines);
- `filled_dot` — compact solid near-square blobs (pen dots).

Pen-like color = very dark (min gray ≤ 60) or clearly colored (channel spread ≥ 60, e.g. red/blue/green pen). Mid-gray, low-saturation UI chrome (header bands, chart frames, table borders ~90–150 gray) is excluded by this rule. Ordinary text fails the column-coverage rule (inter-letter gaps) and the fill/thickness rules.

Honest limits: heavy blur can fade marks below the dark threshold (the independent blur quality gate blocks such images anyway); black-bordered UI tables can still false-positive (conservative: sends to review, never to learners); vector-drawn marks are out of scope (see Priority B). Detection refuses eligibility — it never erases, inpaints or "cleans" anything.

## Quality: real resolution, not cosmetic

Quality is measured on the SOURCE pixels (a resize can never flip a FAIL to a PASS), with two profiles — `diagram` and `screenshot` — because a vector diagram and a dense UI screenshot are not judged by the same numbers. There is deliberately NO universal "300 DPI" claim for source rasters.

Hard gates: `SOURCE_IMAGE_TINY` (<32px), `SOURCE_IMAGE_LOW_RESOLUTION` (native width below profile minimum, or effective density `native_width / css_width` below the profile floor), `SOURCE_IMAGE_ASPECT_EXTREME` (outside [1/6, 6]), `SOURCE_IMAGE_BLURRY` (Laplacian variance below profile threshold), `SOURCE_IMAGE_LOW_CONTRAST` (RMS contrast below profile threshold).

Advisories (recorded, never silently dropped): `BELOW_PIXEL_DENSITY_GOAL` (eligible but below the 2× display goal), `SOURCE_IMAGE_CLIPPED` (histogram extremes — legitimate black-text-on-white exhibits are not hard-failed), `ADVISORY_TEXT_EDGE_DENSITY`.

## Privacy architecture (hard, not labels)

- Learner archives are built from an EXPLICIT ALLOWLIST of verified `question_clean_candidate` entries (basename → written SHA) taken from the manifest. Manifest trust is LAYERED (2026-11-14 P0 correction):
  - `integrity.entries_sha256` — legacy partial digest over the questions array (kept for continuity; recomputable by anyone);
  - `integrity.package_integrity_sha256` — digest over ALL security-critical fields (exam identity, pinned source, generated_by, questions, `reviewer_only_assets`, counts). A manifest without a valid package digest is REFUSED (`require_package_integrity`, default on);
  - `integrity.receipt_sha256_hmac` — OPTIONAL HMAC-SHA256 receipt keyed by a secret held OUTSIDE the package (environment variable named by `privacy.manifest_key_env`; no key ever lives in public code). With `privacy.require_receipt=true` the gate refuses any manifest without a valid receipt — this is the independent tamper-evidence layer;
  - `privacy.source_receipt` — OPTIONAL independent binding to an externally pinned exam source manifest (e.g. the private repository's `exams/<code>/manifest.json`): the manifest's `source_pdf_sha256`/bytes must match the pinned PDF entry.
  - Honest boundary: the self-declared digests detect partial edits but an attacker regenerating the WHOLE manifest can recompute them — which is why the gate additionally CONTENT-RE-VERIFIES every allowlisted member against the pinned source PDF: rendered members' recorded crops are re-checked for answer/marker text (whole-page clips categorically refused), raster members are re-matched to embedded PDF images (bytes or exact pixels) and re-run through mark detection. A regenerated manifest around a leaky or marked image is therefore REFUSED. No self-signed checksum is presented as adversarial tamper-evidence.
- Marked / reviewer-only binaries live in an isolated `private_dir/reviewer-only` completely outside any import/package/web root; `prepare` refuses output paths inside the upstream workspace.
- `verify-package` refuses (exit 3) with per-member reasons: `REVIEWER_ONLY_BINARY_IN_PACKAGE` (bytes match a known marked asset — catches renames, re-embeddings, unrelated paths), `SHA_MISMATCH_VS_MANIFEST`, `UNALLOWED_IMAGE_MEMBER`, `PATH_TRAVERSAL_OR_ABSOLUTE`, `SYMLINK_MEMBER`, `NESTED_ZIP_REJECTED`, `EXTERNAL_URL`, `IMAGE_REF_NOT_ALLOWLISTED` (every image reference in questions.json / import CSVs incl. `question_media_assets.csv` / simulator settings / HTML/JS must resolve to an allowlisted member), `MISSING_CLEAN_IMAGE`, `DUPLICATE_ASSET_IDENTITY`, `PUBLISH_FLAG_IN_DRAFT`, plus the P0 additions `ANSWER_TEXT_IN_RENDER`, `QUESTION_CROP_UNVERIFIED`, `RENDER_GEOMETRY_MISSING`, `RASTER_PROVENANCE_MISMATCH`, `MARKED_IMAGE_IN_ALLOWLIST`, `MEMBER_UNDECODABLE`, `RECEIPT_MISSING`, `RECEIPT_KEY_UNAVAILABLE`, `RECEIPT_HMAC_MISMATCH`, `SOURCE_RECEIPT_UNREADABLE`, `SOURCE_RECEIPT_MISMATCH`.
- Re-encoded marked images (changed bytes) are caught by PROVENANCE: only a manifest entry that itself records the verified source SHA + method can mint eligibility — and the gate re-runs mark detection on the actual shipped pixels. Perceptual hashes can alert but never prove — the tool does not pretend otherwise.
- Learner-visible scoring keys (`correct_option_ids`, `answer_key`, ...) FAIL the gate outright (P0 correction): `verify_package()` returns `passed=False` and `enforce()` raises — a DIRECT library caller checking `report["passed"]` can no longer accept a key-bearing payload the CLI would refuse (exit 3). `SITE_SCORING_ARCHITECTURE_REVIEW_REQUIRED` is recorded on the report as the reason. This module cannot prove the live site's server behavior from a static package — staging review is a separate gate.

## Integration with the upstream engine (no rewrite)

`media_prep` slots in AFTER the pinned upstream `extract` stage and BEFORE the upstream `bank`/import/package gates:

```
upstream extract (pinned 13dea6b)     -> <out>/extracted/split.json + <out>/media/src/*
certpassly.media_prep scan            -> readiness inventory (read-only)
certpassly.media_prep prepare         -> clean/ + private/reviewer-only/ + manifest
upstream build_bank / emit_import     -> consumes ONLY clean/ + manifest allowlist
certpassly.media_prep verify-package  -> final allowlist gate on the draft ZIP
upstream check_import_conformance / package_guard -> unchanged, still run
```

Nothing in the upstream runner is modified; `scan` may invoke the pinned extractor itself when `upstream.run_extract=true` (recorded in the manifest), otherwise it reuses an existing extraction output.

## Documented limitations / UNTESTED surfaces

- `SIMULATOR_IMAGE_UI_UNTESTED` / `STAGING_IMPORTER_UNTESTED`: no staging site was connected in this implementation; real simulator rendering and the live importer remain separate gates.
- Vector-drawn pen marks: out of scope (recorded, see Priority B).
- The mark detector is conservative: a false positive blocks (review), a false negative is mitigated by the pair check and the independent quality gates — but no claim is made that machine detection proves the absence of marks; human visual review of learner-facing media remains a separate required gate.
- `verify-package` inspects a static ZIP; it cannot prove server-side scoring behavior.
