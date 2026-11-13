# Non-AI clean simulator images: design, roles and security boundary

**Module:** `certpassly.media_prep` (toolkit `certpassly-media-prep` 1.0.0)
**Upstream pin:** `msaqlainhaneef1/certpassly-exam-pipeline@13dea6bab662ab1c4bbf87017e912e519907c8bc` (read-only; never vendored — its root has no confirmed redistributable LICENSE)
**Schemas:** `image-readiness-v1` (scan), `image-manifest-v1` (prepare), `media-prep-v1` (config)

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

**Priority B — annotation-free render (self-verified).** Two variants:

- *Annotation variant*: the question image is marked AND its PDF page carries real annotations overlapping the image placement. The clip is rendered at 300 DPI with `annots=False`; the render must (a) differ from the with-annotations render (the annotations actually contributed pixels) and (b) contain no detected marks itself. If the marks were flattened INTO the raster, the render still shows them, both checks fail, and Priority B is honestly recorded as not applicable — `annots=False` does nothing for flattened marks and this toolkit never claims otherwise.
- *Vector variant*: the question's page carries substantial vector drawings (≥20% of page area) — the exhibit is DRAWN in the PDF, not embedded. The page renders at 300 DPI (true added pixels for vector/text content, unlike an embedded raster, which cannot gain source pixels by re-rendering — the native embedded resolution is a hard ceiling, recorded per candidate). When the page has annotations, the render must differ from the with-annotations render. Vector-DRAWN pen marks cannot be distinguished from legitimate table borders and are a documented out-of-scope limitation (`VECTOR_PEN_MARK_UNDETECTABLE`) — they are recorded, never assumed clean.

**Priority C — paired clean member.** When the same exhibit appears twice (typically question + answer copy), conservative ORB+RANSAC registration (≥25 inliers, ≥0.55 inlier ratio, bounded scale/translation) proves the pair, mark detection identifies the marked member, and the ALREADY-CLEAN member becomes the learner candidate with the role correction recorded (`PAIR_ROLE_CORRECTION`). The pair diff is ADVISORY: it can never erase anything and never fabricates a clean image from a marked one.

**Priority D — block.** No provable clean source → no learner image, one of: `CLEAN_ASSET_MISSING`, `MARKED_ONLY_REVIEW_REQUIRED`, `SOURCE_IMAGE_AMBIGUOUS`, `SOURCE_IMAGE_LOW_RESOLUTION`, `SOURCE_IMAGE_BLURRY`, `SOURCE_IMAGE_LOW_CONTRAST`, `SOURCE_IMAGE_TINY`, `SOURCE_IMAGE_ASPECT_EXTREME`, `SOURCE_ASSET_SHA_MISMATCH`, `SOURCE_IMAGE_CORRUPT`.

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

- Learner archives are built from an EXPLICIT ALLOWLIST of verified `question_clean_candidate` entries (basename → written SHA) taken from the tamper-evident manifest (`integrity.entries_sha256` = SHA-256 of the canonical JSON of the questions array; any post-hoc edit of roles/eligibility/SHAs breaks it → exit 3).
- Marked / reviewer-only binaries live in an isolated `private_dir/reviewer-only` completely outside any import/package/web root; `prepare` refuses output paths inside the upstream workspace.
- `verify-package` refuses (exit 3) with per-member reasons: `REVIEWER_ONLY_BINARY_IN_PACKAGE` (bytes match a known marked asset — catches renames, re-embeddings, unrelated paths), `SHA_MISMATCH_VS_MANIFEST`, `UNALLOWED_IMAGE_MEMBER`, `PATH_TRAVERSAL_OR_ABSOLUTE`, `SYMLINK_MEMBER`, `NESTED_ZIP_REJECTED`, `EXTERNAL_URL`, `IMAGE_REF_NOT_ALLOWLISTED` (every image reference in questions.json / import CSVs incl. `question_media_assets.csv` / simulator settings / HTML/JS must resolve to an allowlisted member), `MISSING_CLEAN_IMAGE`, `DUPLICATE_ASSET_IDENTITY`, `PUBLISH_FLAG_IN_DRAFT`.
- Re-encoded marked images (changed bytes) are caught by PROVENANCE: only a manifest entry that itself records the verified source SHA + method can mint eligibility. Perceptual hashes can alert but never prove — the tool does not pretend otherwise.
- Learner-visible scoring keys (`correct_option_ids`, `answer_key`, ...) do not leak silently: the gate flags `SITE_SCORING_ARCHITECTURE_REVIEW_REQUIRED` and refuses to certify. This module cannot prove the live site's server behavior from a static package — staging review is a separate gate.

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
