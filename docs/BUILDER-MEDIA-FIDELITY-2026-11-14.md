# CertPassly technical media builder — source-fidelity gate (2026-11-14)

**Status: DEVELOPMENT ONLY. This branch, its CI, its tests and its proposed
media-layout contract do not approve any actual exam, answer key, simulator
renderer, site importer or publication. Do not merge/promote before independent
private source replay and authorized release decisions.**

## Reproducible foundation

* Public code base: `mathorax1-hue/certpassly-exam-skill`, draft PR #4,
  stacked onto `zai/nonai-clean-simulator-media` live head `5a02e741c48d039b58046fc28e6d9b9c6bffeea9`.
* Original external 15-stage conversion engine remains
  `msaqlainhaneef1/certpassly-exam-pipeline` at
  `13dea6bab662ab1c4bbf87017e912e519907c8bc`. It is **not vendored** or
  replaced in this public repository; there is no upstream LICENSE grant
  established for redistribution.
* Pinned source-PDF processing dependency is `PyMuPDF>=1.26,<1.27`
  (validated 1.26.7); use `python -m pip install -e ".[phase1,visual]"`.
  Python >=3.11, Pillow >=10,<13, numpy >=1.26,<3, OpenCV headless >=4.9,<5,
  jsonschema >=4.20,<5. Reuse cached environments; do not repin silently.
* All committed images/fixtures in this public change are newly generated
  synthetic geometry. No real question, answer, PDF, key or screenshot.

## B0: actual red-baseline proof

The preceding detector labeled a **blue filled radio/checkbox** as clean,
because blue selection ink had grayscale intensity above the detector's dark
threshold. Repro: `python -m unittest tests.test_builder_b0_marks -v`.
Before the B2 fix, mandatory image CI
[`43536698422`](https://github.com/mathorax1-hue/certpassly-exam-skill/actions/runs/43536698422)
on commit `0bd2a080fcb50422aebdc169aa0b16f90ff7bcab` yielded **3 failed
color-state tests of 91 total, 2 environment-gated skips** on the Linux
3.11 matrix; all three OS/Python jobs failed. Trace shows
`detected_mark_boxes: 0` for a selected control. The empty-gray-control
test passed. This red checkpoint is intentional and preserved in Git
history, not waived or hidden.

## B1: precise question-only crop inherited from live base

Current PR3 base already introduced `media_prep/exhibit_crop.py`, corrected
rotated PDF clip mapping, refused whole-page vector fallback and added synthetic
q074-style neighboring-key tests plus pinned-source package crop rechecking.
B1 is **implemented in the stacked base**, but a green synthetic test is not
a complete pixel-level proof that private AB-730 q074 is now safe.
The original q074 `Correct Answer:` leakage remains a private P0 hold
until the original source PDF is rehashed, cropped, and compared by a separate
verifier against actual page 59. If segmentation or original flattening is
uncertain, block with `QUESTION_CROP_UNVERIFIED` / `ANSWER_TEXT_IN_RENDER`.

## B2: selected-control state guard (new patch)

`media_prep/marking.py` now supplements dark connected-components analysis
with a color-saturated compact-filled-component test. Its synthetic targets are
a blue filled radio, a filled checkbox and the JPEG-compressed counterpart;
unselected gray UI chrome must not be marked. **This is conservative and may
false-block small saturated chart legends, badges or other UI elements.** It
does not infer which answer is correct, inpaint, erase or approve a screenshot
solely because its mark count is zero. Real q088 still needs private
source-image pair replay; q004/q005/q006/q025/q027 dropdown-border
false-rejections are **not** claimed resolved without genuine pair evidence.
Use the existing registered pair/role-selection engine conservatively; keep
q012 or any ambiguous pair blocked.

## B3: native image quality (new audit)

`quality.responsive_density_matrix(SourceImage)` evaluates the **native**
pixel width at 320/375/768/1024/1440 CSS px, DPR 1/2 and zoom 1/2,
explicitly recording density and device pixel budget. It never upscales a
613px screenshot to make it appear 1280px-native. `region_blur_matrix`
computes per-tile Laplacian variance on source pixels to expose a fuzzy
footer even if the upper half is sharp. These are diagnostic functions,
not semantic OCR, real CSS screenshots, or permission to publish: micro-font
legibility, clipping and source correctness require independent visual proof.

## B4: answer-free 30-type media-layout-v1

New `src/certpassly/media_prep/media_layout.py`, formal
`schemas/media-layout-v1.schema.json`, and
`scripts/validate_media_layout.py` represent media and
interaction positions separately from scoring keys.

The adapter reads the **original** upstream
`reference/site-format/v1/question_types.json`. It requires exactly the
pinned 30 key/flag assignments: 16 enabled/publishable, 7
enabled/nonpublishable and 7 disabled. Unknown or disabled types fail closed
rather than downgrading to `single_choice`. Publishable synthetic type
families cover selection, matrix row+column IDs, cloze blank IDs and rects,
ordering, association and drag/drop items+zones, hotspot rect/polygon
coordinates, and case-study shared stimuli/child references. Media records
carry source-PDF SHA/page/xref/rotation/crop, output SHA, source SHA and a
neutral/interactive/shared role. No answers, selected state or scoring payload
may enter this contract.

The deterministic `project_upstream_question(...)` adapter consumes the original
upstream `question_type` / `response_schema.content` contract (for example
`rows`, `columns`, `blanks`, `left`, `right`, `regions`). **Original
source facts and clean-media proof must be supplied independently.** It emits
only a whitelisted media layout and an explicit PASS/BLOCKED verification;
`answer_key`, `correct_option_ids`, `answer_raw`, selected state and
explanation fields are never copied into the output. If a dropdown, drag/drop,
matching or hotspot region lacks independently verified normalized
coordinates, the adapter blocks instead of fabricating a location. Separate
30-type synthetic projection tests exercise this path. Source response
compatibility is not the same as observed site UI compatibility.

Normalized rectangles/polygons are in **0..1 source image coordinates**;
`css_rect` maps rotations (0/90/180/270), viewport, zoom, and DPR and
reports the 44-CSS-px touch-target diagnostic. Actual keyboard navigation,
accessibility, label selection, hitbox fidelity and site runtime are
**UNTESTED**: a valid contract proves neither actual import compatibility nor
the app's interactive behavior.

### Responsive interaction audits (B4)

`interaction_audit.audit_interaction_geometry(layout, registry,
native_width=..., native_height=...)` uses **original verified raster**
dimensions and an explicit viewport/DPR/zoom matrix. It checks normalized
hotspot, drop-zone and blank geometry for sub-44px CSS touch targets,
overlapping regions and invalid/missing positions. It blocks undersized
or ambiguous regions; a browser may later add larger CSS hit areas, but
those must be demonstrated in the actual site and cannot be assumed here.
The module always reports site and keyboard behavior **UNTESTED**. See
`tests/test_interaction_audit.py` for rotation, overlap, tiny touch target
and missing-source negative tests.

### CLI example (synthetic or private local paths only)

```bash
python scripts/validate_media_layout.py \
  --registry ../upstream/reference/site-format/v1/question_types.json \
  --layout /PRIVATE/media-layout-v1.json --report /PRIVATE/layout-check.json
```

Exit **0**: structurally valid publishable media *contract*; **2**:
ambiguous/unpublishable or unsafe geometry; **1**: bad input/runtime.
A 0 exit is never a release, site, legal-rights or human-answer approval.

## B5: strict technical privacy preflight

The live base already added full security manifest integrity digest, HMAC
receipt option, a verified pinned source identity, direct API scoring-flag
refusal, a learner clean SHA allowlist and package member source revalidation.
The new **strict library entrypoint** is:

```python
from certpassly.media_prep.privacy_gate import verify_release_candidate, enforce
report = verify_release_candidate(
    "/PRIVATE/image-manifest.json", "/PRIVATE/draft.zip",
    source_pdf="/PRIVATE/original.pdf",
    source_receipt="/PRIVATE/original-source-manifest.json",
    manifest_key_env="CERTPASSLY_MANIFEST_KEY")
enforce(report)
# The result is only technical_privacy_preflight: PASS; site UI and
# human approvals are NOT_APPROVED/UNTESTED.
```

It independently rehashes the **original PDF file bytes**, checks the
manifest's source SHA and byte count, requires an independent source receipt
and an **out-of-package** HMAC signing key supplied by environment. The
ordinary `verify_package` API can be used for synthetic diagnostics with
receipt requirements off; **do not treat its `passed` field as release
authorization**. Supply a genuine private trusted receipt for strict use.
Never put keys, private receipts, original exam images or questions into this
public codebase.

## Synthetic test/review loop

```bash
python -m pip install -e ".[phase1,visual]"
python -m pip check
python -m unittest tests.test_builder_b0_marks \
  tests.test_builder_quality_profiles tests.test_media_layout_contract \
  tests.test_media_layout_schema tests.test_media_layout_cli \
  tests.test_upstream_media_projection tests.test_interaction_audit \
  tests.test_builder_release_gate -v
python -m unittest tests.test_media_prep_inventory \
  tests.test_media_prep_quality tests.test_media_prep_privacy \
  tests.test_media_prep_e2e tests.test_media_prep_cli -v
python scripts/verify_tool_registry.py
python scripts/check_public_safety.py
python -m compileall -q scripts src
```

Mandatory public image CI runs Linux Python 3.11 and 3.13 and Windows
Python 3.11; only two deliberately gated real-upstream integration tests
may skip when `CERTPASSLY_UPSTREAM_SCRIPTS` is unavailable. Linux runs the
exact pinned upstream **synthetic** extractor separately. Generic public
`ci.yml` has no visual extras, so the optional image tests skip there;
**media-prep-ci.yml is the authoritative image test suite**.

## B6: independent verification needed on actual private evidence

No learner-ready original AB-730 image has been newly approved by this
developer branch. Required independent source checks include the original private Git LFS PDF, owner-pinned source byte size and SHA-256 (recorded only in the PRIVATE raw-exam director handover);
all **44** image-requiring question statuses and **87** original source
assets, with a private page/source-vs-output-vs-marked contact sheet.
Specifically re-open q074 page 59, the q088 private source selected-state screenshot, five possible
clean dropdown pairs, low-native-res q035/q059/q078 and mixed widget
geometry, checking exact source xrefs, roles and output SHA for each.
A private pass needs original source-hash and artifact readback, real
pixel/source human inspection and separate authorized human content
approval. Z.ai is the independent engineering replay/verifier; AI review
alone is NOT the owner-designated human signoff.

Any uncertainty, unsupported type, marked content, private source missing
or untested site contract remains **BLOCKED**. Original 35 image candidates,
the five-exam batch, site staging, answer research, ready-exams promotion,
merges and publication stay on HOLD.

## Code ownership and limitation notes

Reusable tools, tests, config and docs belong in this public skill PR.
Real source PDFs, raw extraction, owner selections, marked images, original
source manifests, private contact sheets and progress records belong in
`mathorax1-hue/raw-exam` only. Preserve archival history; append verified
checkpoints, never overwrite the >3 MB canonical conversation master with
a partial reconstruction. Source-fidelity gates must remain independent
from automated score, quality and formal schema gates.
