"""CertPassly Phase 1 PDF extraction toolkit (public, reusable, config-driven).

Promoted from the private raw-exam pilot toolkit by ZAI-EXTRACT-003 after the
ZAI-EXTRACT-001/002 pilots (see knowledge/ENGINEERING-HISTORY.md). The engine is
fully config-driven: no exam code, count, page number, path or narrative is
hardcoded. One JSON config per exam drives every stage.

Scope and honest limitations:
  - This toolkit is the Phase-1 SOURCE-EXTRACTION layer (questions, pages, exact
    source image binaries, usage/xref provenance, fail-closed exports, QA). It
    does NOT replace the pinned upstream 15-stage authoring pipeline, does NOT
    verify answer truth, and grants no release/publication authority.
  - Strictly local: no network access, no upload, no publication. All outputs
    are private workspace files; answer-reference material is fail-closed
    (private_reviewer_only) and never enters learner-facing exports.

Compatibility:
  - structured/v1 schema (templates/extraction-schema.v1.json), with the
    versioned ``typed_text_with_answer_image`` answer source-kind extension.
  - Pinned external upstream extractor commit (see UPSTREAM_PIN below); the
    upstream checkout is used read-only and is never vendored here.

Module map (each runnable as ``python -m certpassly.phase1.<name>``):
  audit_source.py          read-only source PDF audit (identity/integrity gate)
  make_pmap.py             pdftohtml media -> PDF xref mapping
  build_structured_v1.py   build the structured/v1 layer for one exam
  build_exports.py         deterministic, fail-closed export adapters
  make_source_manifest.py  read-only artifact inventory + PDF verification block
  validate_structured_v1.py config-driven validation/completeness contract
  reconcile.py             cross-walk of every count system and prior audits
  visual_qa.py             page renders, contact sheets, image visibility
  run_all.py               stage orchestrator (checkpoints, resume)
  adversarial.py           27 synthetic adversarial scenarios (no real exam data)

See docs/PHASE1-EXTRACTION.md for installation, exact commands, caching and
troubleshooting.
"""
from __future__ import annotations

TOOLKIT_NAME = "certpassly-phase1-extraction"
TOOLKIT_VERSION = "1.0.0"
STRUCTURED_SCHEMA_VERSION = "structured-v1"
# Full pinned SHA of the external upstream extractor this toolkit integrates with
# (read-only external dependency; never modified or vendored here).
UPSTREAM_REPO = "msaqlainhaneef1/certpassly-exam-pipeline"
UPSTREAM_PIN = "13dea6bab662ab1c4bbf87017e912e519907c8bc"
# Compatible optional config extension for answers that carry both a typed key
# and an answer-reference screenshot (declared per exam in config.schema).
SCHEMA_COMPATIBLE_EXTENSIONS = ("typed_text_with_answer_image",)

__all__ = [
    "TOOLKIT_NAME", "TOOLKIT_VERSION", "STRUCTURED_SCHEMA_VERSION",
    "UPSTREAM_REPO", "UPSTREAM_PIN", "SCHEMA_COMPATIBLE_EXTENSIONS",
]
