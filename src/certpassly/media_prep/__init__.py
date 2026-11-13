"""CertPassly non-AI clean simulator-media preparation toolkit (public, reusable).

Deterministic image-quality/privacy extension on top of the PINNED external
upstream exam-conversion pipeline (msaqlainhaneef1/certpassly-exam-pipeline,
commit 13dea6bab662ab1c4bbf87017e912e519907c8bc). This module NEVER rewrites
the 15-stage engine: it consumes that engine's extraction output
(``extracted/split.json`` + ``media/src/*``) and adds a strict, non-AI
clean-image selection / high-resolution rendering / quality-check /
answer-image-isolation layer.

Scope and honest limitations (read before use):
  - No AI, no OCR-created answer content, no generative restoration, no
    inpainting, no upscaling-as-restoration. When no provable clean source
    exists the question is BLOCKED with an explicit reason code.
  - ``PyMuPDF page.get_pixmap(..., annots=False)`` only removes true PDF
    annotations. Flattened raster selection marks are NOT annotations and are
    NOT cleaned by rendering; the tool records this honestly and never claims
    a cleaned image in that case.
  - Learner packages are built from an EXPLICIT ALLOWLIST of verified
    ``question_clean_candidate`` entries (provenance-based). Marked /
    reviewer-only / private media can never enter a learner package, even
    when renamed or re-encoded (binary SHA comparison against the private
    inventory, plus manifest integrity hashes).
  - Strictly local. No network access, no upload, no publication, no release
    authority. ``verify-package`` inspects a ZIP; it cannot prove the live
    site's server behavior. If a site format ships scoring keys to the client,
    the tool flags ``SITE_SCORING_ARCHITECTURE_REVIEW_REQUIRED`` instead of
    claiming answer security.

Roles (immutable provenance records):
  source_original_private      original source binary (SHA-256, bytes, native
                               size, PDF page/xref, usage role); never learner
  answer_marked_reviewer_only  marked answer reference; checked/private; never
                               learner payload/CDN/ZIP
  question_clean_candidate     learner candidate from a verified unmarked
                               source or a trustworthy annotation-free/vector
                               rendering, with recorded source linkage + method
  unknown_unverified           ambiguous role, unusable crop, marked-only
                               evidence or uncertain content: BLOCK, do not
                               guess

CLI (python -m certpassly.media_prep):
  doctor         dependency/OS/pinned-upstream inventory (read-only)
  scan           read-only source image role inventory + readiness records
  prepare        write ONLY verified clean candidates + evidence manifest
  verify-package strict allowlist role gate for a learner draft ZIP

Exit codes: 0 = applicable machine gates passed; 1 = invalid config or
operational failure; 2 = blocked source / ambiguous / missing clean source;
3 = privacy, integrity or manifest-tamper refusal.

Module map (import-safe without optional extras; heavy imports are lazy):
  config.py           config load/validate + quality profile defaults
  imageio.py          safe image decode, SHA-256, native size, alpha flatten
  roles.py            role constants and decision-record helpers
  source_inventory.py upstream split + PDF xref/page provenance inventory
  upstream_runner.py  subprocess adapter to the pinned upstream extractor
  marking.py          raster mark detection (dark-box connected components)
  pair_and_align.py   conservative clean/marked pair registration (advisory)
  renderer.py         Priority-B high-DPI crop rendering (annots=False)
  quality.py          dimension/density/blur/contrast/clipping/aspect checks
  selection.py        the strict A/B/C/D priority engine
  manifest.py         deterministic canonical manifest writer (atomic)
  privacy_gate.py     allowlist builder + ZIP/site-reference privacy scanner
  cli.py              argparse CLI with the exit-code contract above
"""
from __future__ import annotations

TOOLKIT_NAME = "certpassly-media-prep"
TOOLKIT_VERSION = "1.0.0"
READINESS_SCHEMA_VERSION = "image-readiness-v1"
MANIFEST_SCHEMA_VERSION = "image-manifest-v1"
CONFIG_SCHEMA_VERSION = "media-prep-v1"
UPSTREAM_REPO = "msaqlainhaneef1/certpassly-exam-pipeline"
UPSTREAM_PIN = "13dea6bab662ab1c4bbf87017e912e519907c8bc"

# Exit-code contract (documented; do not change semantics without a registry/
# doc update and full test replay).
EXIT_OK = 0
EXIT_OPERATIONAL = 1
EXIT_BLOCKED = 2
EXIT_TAMPER = 3

__all__ = [
    "TOOLKIT_NAME", "TOOLKIT_VERSION", "READINESS_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION", "CONFIG_SCHEMA_VERSION", "UPSTREAM_REPO",
    "UPSTREAM_PIN", "EXIT_OK", "EXIT_OPERATIONAL", "EXIT_BLOCKED", "EXIT_TAMPER",
]
