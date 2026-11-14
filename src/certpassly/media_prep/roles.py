"""Role constants and decision-record helpers (immutable provenance records)."""
from __future__ import annotations

# The four immutable roles. Every record carries exactly one of these.
SOURCE_ORIGINAL_PRIVATE = "source_original_private"
ANSWER_MARKED_REVIEWER_ONLY = "answer_marked_reviewer_only"
QUESTION_CLEAN_CANDIDATE = "question_clean_candidate"
UNKNOWN_UNVERIFIED = "unknown_unverified"
ROLES = (SOURCE_ORIGINAL_PRIVATE, ANSWER_MARKED_REVIEWER_ONLY,
         QUESTION_CLEAN_CANDIDATE, UNKNOWN_UNVERIFIED)

# Selection methods (Priority hierarchy from the operator order).
METHOD_PRIORITY_A = "priority_a_direct_clean_source"
METHOD_PRIORITY_B = "priority_b_annotation_free_render"
METHOD_PRIORITY_C = "priority_c_paired_clean_member"
METHOD_NONE = "none"
METHODS = (METHOD_PRIORITY_A, METHOD_PRIORITY_B, METHOD_PRIORITY_C, METHOD_NONE)

# Review status values.
REVIEW_CLEAN_READY = "clean_ready"
REVIEW_CLEAN_LOW_RESOLUTION = "clean_low_resolution"
REVIEW_BLOCKED = "blocked"
REVIEW_STATUSES = (REVIEW_CLEAN_READY, REVIEW_CLEAN_LOW_RESOLUTION, REVIEW_BLOCKED)

# Blocked reason codes (stable contract; docs reference these).
R_CLEAN_ASSET_MISSING = "CLEAN_ASSET_MISSING"
R_MARKED_ONLY_REVIEW_REQUIRED = "MARKED_ONLY_REVIEW_REQUIRED"
R_SOURCE_IMAGE_LOW_RESOLUTION = "SOURCE_IMAGE_LOW_RESOLUTION"
R_SOURCE_IMAGE_AMBIGUOUS = "SOURCE_IMAGE_AMBIGUOUS"
R_SOURCE_IMAGE_BLURRY = "SOURCE_IMAGE_BLURRY"
R_SOURCE_IMAGE_LOW_CONTRAST = "SOURCE_IMAGE_LOW_CONTRAST"
R_SOURCE_IMAGE_CLIPPED = "SOURCE_IMAGE_CLIPPED"
R_SOURCE_IMAGE_TINY = "SOURCE_IMAGE_TINY"
R_SOURCE_IMAGE_ASPECT_EXTREME = "SOURCE_IMAGE_ASPECT_EXTREME"
R_SOURCE_SHA_MISMATCH = "SOURCE_ASSET_SHA_MISMATCH"
R_SOURCE_IMAGE_CORRUPT = "SOURCE_IMAGE_CORRUPT"
# 2026-11-14 P0 security correction (director audit: real AB-730 q074
# whole-page render exposed neighbouring questions' Correct Answer lines).
# Whole-page renders are never learner images; a learner render must be an
# exact, source-verified question/exhibit crop with zero answer/marker text.
R_QUESTION_CROP_UNVERIFIED = "QUESTION_CROP_UNVERIFIED"
R_ANSWER_TEXT_IN_RENDER = "ANSWER_TEXT_IN_RENDER"
R_MULTI_EXHIBIT_MAPPING_REQUIRED = "MULTI_EXHIBIT_MAPPING_REQUIRED"
BLOCK_REASONS = (R_CLEAN_ASSET_MISSING, R_MARKED_ONLY_REVIEW_REQUIRED,
                 R_SOURCE_IMAGE_LOW_RESOLUTION, R_SOURCE_IMAGE_AMBIGUOUS,
                 R_SOURCE_IMAGE_BLURRY, R_SOURCE_IMAGE_LOW_CONTRAST,
                 R_SOURCE_IMAGE_CLIPPED, R_SOURCE_IMAGE_TINY,
                 R_SOURCE_IMAGE_ASPECT_EXTREME, R_SOURCE_SHA_MISMATCH,
                 R_SOURCE_IMAGE_CORRUPT, R_QUESTION_CROP_UNVERIFIED,
                 R_ANSWER_TEXT_IN_RENDER, R_MULTI_EXHIBIT_MAPPING_REQUIRED)


def decision_record(*, source_file, source_sha256, source_bytes, page, xref,
                    assigned_role, verified_role, method, marking,
                    native_width=None, native_height=None, issues=None,
                    answer_image_inferred=False, render_note=None):
    """Build one immutable source-image decision record."""
    return {
        "source_file": source_file,
        "source_sha256": source_sha256,
        "source_bytes": source_bytes,
        "page": page,
        "xref": xref,
        "assigned_role": assigned_role,
        "answer_image_inferred": bool(answer_image_inferred),
        "verified_role": verified_role,
        "method": method,
        "marking": marking,
        "native_width": native_width,
        "native_height": native_height,
        "issues": list(issues or []),
        "render_note": render_note,
    }
