"""Media-layout-v1: fail-closed, source-provenanced simulator geometry contracts.

Technical media adapter, NOT a website renderer, answer scorer, key store, or
release approval. Uses the pinned upstream question_types.json at runtime;
does not duplicate or redistribute the upstream conversion engine.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath

SUPPORTED_ROTATIONS = (0, 90, 180, 270)
ALLOWED_ROLES = {"neutral_stimulus", "interactive_background", "shared_stimulus"}
FORBIDDEN_FIELDS = {
    "answer_key", "correct_answer", "correct_answers", "correct_option_id",
    "correct_option_ids", "correct_rows", "answer_letters", "answer_raw",
    "is_correct", "selected_answer", "selected_option", "selected_option_ids",
    "scoring_key", "solution", "explanation",
}
HEX = set("0123456789abcdef")

# Minimal compatibility facts (type identifiers/flags), not upstream source code.
# Exact key sets prevent a forged registry from swapping a disabled type for a
# publishable type while preserving only the 16/7/7 counts.
PINNED_PUBLISHABLE = frozenset((
    "single_choice", "multiple_select", "true_false", "image_based_choice",
    "scenario_standalone", "yes_no_matrix", "single_choice_matrix",
    "inline_dropdown", "multi_blank_dropdown", "ordering", "matching",
    "categorization", "drag_drop", "hotspot_single", "hotspot_multi",
    "case_study_group",
))
PINNED_NONPUBLISHABLE = frozenset((
    "multi_select_matrix", "text_cloze", "active_screen", "short_text",
    "numeric", "multimedia_stimulus", "testlet",
))
PINNED_DISABLED = frozenset((
    "sectioned_delivery", "unscored_pretest", "adaptive_delivery",
    "simulation_ui", "terminal_task", "lab_task", "code_answer",
))



def _sha_ok(value):
    return isinstance(value, str) and len(value) == 64 and all(c in HEX for c in value)


def load_type_registry(path):
    """Read the unchanged, pinned original upstream question-type registry."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data.get("types"), dict) or len(data["types"]) != 30:
        raise ValueError("expected exact 30-type upstream question registry")
    counts = (
        sum(bool(t.get("enabled")) and bool(t.get("publishable")) for t in data["types"].values()),
        sum(bool(t.get("enabled")) and not bool(t.get("publishable")) for t in data["types"].values()),
        sum(not bool(t.get("enabled")) for t in data["types"].values()),
    )
    if counts != (16, 7, 7):
        raise ValueError(f"unexpected enabled/publishable registry flags: {counts}")
    actual_pub = {k for k, t in data["types"].items()
                  if t.get("enabled") and t.get("publishable")}
    actual_nonpub = {k for k, t in data["types"].items()
                     if t.get("enabled") and not t.get("publishable")}
    actual_disabled = {k for k, t in data["types"].items()
                       if not t.get("enabled")}
    if (actual_pub != PINNED_PUBLISHABLE or
        actual_nonpub != PINNED_NONPUBLISHABLE or
        actual_disabled != PINNED_DISABLED):
        raise ValueError("upstream type key/flag assignment differs from pinned v1; "
                         "review a deliberate registry update before using it")
    return data


def _has_forbidden_key(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in FORBIDDEN_FIELDS or k.lower().startswith("correct_"):
                return True
            if _has_forbidden_key(v):
                return True
    elif isinstance(obj, list):
        return any(_has_forbidden_key(x) for x in obj)
    return False


def _unique_ids(things, label, errors, *, needed=True):
    if things is None:
        things = []
    if not isinstance(things, list):
        errors.append(f"{label} must be a list")
        return []
    ids = []
    for item in things:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            errors.append(f"{label} entries require stable nonempty id")
            continue
        ids.append(item["id"])
    if len(ids) != len(set(ids)):
        errors.append(f"{label} contains duplicate IDs")
    if needed and not ids:
        errors.append(f"{label} must not be empty")
    return ids


def _rect(rect):
    if not isinstance(rect, list) or len(rect) != 4:
        return False
    if any(not isinstance(x, (int, float)) or isinstance(x, bool) or
           not math.isfinite(x) or x < 0 or x > 1 for x in rect):
        return False
    x0, y0, x1, y1 = rect
    return x0 < x1 and y0 < y1


def _point(p):
    return isinstance(p, list) and len(p) == 2 and all(
        isinstance(x, (int, float)) and not isinstance(x, bool) and
        math.isfinite(x) and 0 <= x <= 1 for x in p)


def _regions(items, label, errors):
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        if "rect" in item and not _rect(item["rect"]):
            errors.append(f"{label} invalid normalized rect")
        if "polygon" in item:
            poly = item["polygon"]
            if not isinstance(poly, list) or len(poly) < 3 or not all(_point(p) for p in poly):
                errors.append(f"{label} invalid normalized polygon")
        if label in ("hotspots", "drop_zones", "blanks") and not (
            _rect(item.get("rect")) or
            (label == "hotspots" and isinstance(item.get("polygon"), list) and
             len(item["polygon"]) >= 3 and all(_point(p) for p in item["polygon"]))
        ):
            errors.append(f"{label} lacks a valid target region")


def _validate_source(layout, errors):
    src = layout.get("source")
    if not isinstance(src, dict):
        errors.append("source must contain independently pinned PDF and crop provenance")
        return
    if not _sha_ok(src.get("pdf_sha256")):
        errors.append("source.pdf_sha256 must be a full SHA-256")
    if not isinstance(src.get("page"), int) or src["page"] < 1:
        errors.append("source.page must be a positive 1-based integer")
    if src.get("rotation_deg") not in SUPPORTED_ROTATIONS:
        errors.append("source.rotation_deg must be 0/90/180/270")
    if not _rect(src.get("crop")):
        errors.append("source.crop must be a normalized, nonempty page region")
    if "xref" in src and (not isinstance(src["xref"], int) or src["xref"] < 1):
        errors.append("source.xref must be positive when supplied")


def validate_layout(layout: dict, registry: dict, *, for_learner=True) -> dict:
    """Machine media contract; always leaves real site UI as UNTESTED.

    Returns PASS or BLOCKED and stable reasons; never infers any answer key.
    """
    errors = []
    if not isinstance(layout, dict):
        return {"status": "BLOCKED", "reasons": ["layout must be an object"],
                "site_ui_status": "UNTESTED"}
    types = registry.get("types") if isinstance(registry, dict) else None
    if not isinstance(types, dict) or len(types) != 30:
        errors.append("original 30-type registry missing or changed")
        types = {}
    if layout.get("schema_version") != "media-layout-v1":
        errors.append("schema_version must be media-layout-v1")
    if _has_forbidden_key(layout):
        errors.append("learner media layout includes scoring/selection/answer field")
    typ = layout.get("type_key")
    meta = types.get(typ)
    if meta is None:
        errors.append("unknown type_key; never downgrade to single_choice")
        meta = {}
    if for_learner and not (meta.get("enabled") and meta.get("publishable")):
        errors.append("type is disabled or not publishable in original registry")
    if not isinstance(layout.get("question_id"), str) or not layout["question_id"]:
        errors.append("question_id required")
    _validate_source(layout, errors)
    media = layout.get("media", [])
    if not isinstance(media, list):
        errors.append("media must be a list")
        media = []
    seen_files = set()
    for item in media:
        if not isinstance(item, dict):
            errors.append("media record must be an object")
            continue
        p = item.get("file")
        if not isinstance(p, str) or not p or p.startswith("/") or "://" in p or ":" in p or "\\" in p or (
            ".." in PurePosixPath(p).parts
        ) or PurePosixPath(p).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            errors.append("media.file must be safe local raster path")
        elif p in seen_files:
            errors.append("media.file duplicated")
        else:
            seen_files.add(p)
        if item.get("role") not in ALLOWED_ROLES:
            errors.append("media.role must be neutral, shared, or interactive background")
        if not _sha_ok(item.get("sha256")) or not _sha_ok(item.get("source_sha256")):
            errors.append("media must contain output and source SHA-256")
        if item.get("role") == "shared_stimulus" and not item.get("shared_stimulus_id"):
            errors.append("shared stimulus must have stable ownership ID")
    controls = layout.get("controls", {})
    if not isinstance(controls, dict):
        errors.append("controls must be an object")
        controls = {}
    family = meta.get("family")
    if typ == "image_based_choice" and not media:
        errors.append("image_based_choice requires clean source-verified exhibit media")
    if family == "matrix":
        _unique_ids(controls.get("rows"), "rows", errors)
        _unique_ids(controls.get("columns"), "columns", errors)
    if family == "cloze":
        _unique_ids(controls.get("blanks"), "blanks", errors)
        _regions(controls.get("blanks"), "blanks", errors)
    if family in ("association", "interaction"):
        _unique_ids(controls.get("draggable_items"), "draggable_items", errors)
        _unique_ids(controls.get("drop_zones"), "drop_zones", errors)
        _regions(controls.get("drop_zones"), "drop_zones", errors)
    if family == "image_regions":
        _unique_ids(controls.get("hotspots"), "hotspots", errors)
        _regions(controls.get("hotspots"), "hotspots", errors)
        if not media:
            errors.append("image_regions question has no verified background media")
    if family == "sequence":
        _unique_ids(controls.get("items"), "items", errors)
    if family == "container":
        if not layout.get("shared_stimulus_id") or not layout.get("child_question_ids"):
            errors.append("container requires shared stimulus ID and child IDs")
    return {
        "status": "BLOCKED" if errors else "PASS",
        "reasons": sorted(set(errors)),
        "site_ui_status": "UNTESTED",
        "type_key": typ,
        "publishable_in_registry": bool(meta.get("enabled") and meta.get("publishable")),
    }


def rotate_point(x, y, degrees=0):
    """Clockwise image-space rotation about the unit-square center."""
    if degrees not in SUPPORTED_ROTATIONS:
        raise ValueError("unsupported orientation")
    return {
        0: (x, y), 90: (1-y, x), 180: (1-x, 1-y), 270: (y, 1-x)
    }[degrees]


def css_rect(rect, *, width, height, rotation_deg=0, zoom=1.0, dpr=1.0):
    """Map normalized source rect to displayed CSS/device pixels.

    Width/height describe the *displayed* image box after orientation;
    no browser UI or clipping is inferred from this coordinate transform.
    """
    if not _rect(rect):
        raise ValueError("invalid source rect")
    for value in (width, height, zoom, dpr):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or (
            not math.isfinite(value) or value <= 0
        ):
            raise ValueError("width, height, zoom and DPR must be finite and positive")
    x0, y0, x1, y1 = rect
    corners = [rotate_point(x, y, rotation_deg) for x, y in
               ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
    xs = [x for x, _ in corners]
    ys = [y for _, y in corners]
    box = [min(xs) * width * zoom, min(ys) * height * zoom,
           max(xs) * width * zoom, max(ys) * height * zoom]
    return {"css": [round(v, 4) for v in box],
            "device": [round(v * dpr, 4) for v in box],
            "touch_target_44_css_px": ((box[2]-box[0]) >= 44 and
                                       (box[3]-box[1]) >= 44)}


def layout_fingerprint(layout):
    """Deterministic, SHA-256 checksum over canonical UTF-8 layout JSON."""
    raw = json.dumps(layout, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def project_upstream_question(question: dict, *, source: dict, media: list,
                              registry: dict, geometry: dict | None = None) -> dict:
    """B4 safe adapter from the pinned upstream bank response_schema to media-layout.

    Input is the upstream question bank's response_schema.content, plus
    INDEPENDENTLY VERIFIED source crop/clean media and geometric annotations.
    NEVER infer geometry from an answer image or trust question.media paths.
    The upstream bank may have answer_key/marked data, but only explicit
    safe fields are selected into the learner-facing layout. The whole
    original bank object is NEVER serialized into media-layout.
    Missing coordinates block the layout instead of guessing.
    """
    if not isinstance(question, dict):
        raise ValueError("question must be a mapping")
    response = question.get("response_schema") or {}
    if not isinstance(response, dict):
        raise ValueError("question.response_schema must be a mapping")
    typ = question.get("question_type") or response.get("type")
    if (question.get("question_type") and response.get("type") and
            question["question_type"] != response["type"]):
        raise ValueError("question_type and response_schema.type disagree")
    if not isinstance(typ, str) or typ not in registry.get("types", {}):
        raise ValueError("unsupported question type, no silent downgrade")
    content = response.get("content") or {}
    if not isinstance(content, dict):
        raise ValueError("response_schema.content must be a mapping")
    geometry = geometry or {}
    if not isinstance(geometry, dict):
        raise ValueError("geometry must be a mapping")
    # The caller must supply original-source facts and clean-media proof from
    # its private manifest; never take a learner asset from answer_images.
    if not isinstance(source, dict) or not isinstance(media, list):
        raise ValueError("source and clean-media records are required")
    allowed_source = ("pdf_sha256", "page", "rotation_deg", "crop", "xref")
    allowed_media = ("file", "role", "sha256", "source_sha256",
                     "source_page", "source_xref", "shared_stimulus_id")
    src = {k: source[k] for k in allowed_source if k in source}
    safe_media = [{k: m[k] for k in allowed_media if k in m}
                  for m in media if isinstance(m, dict)]
    if len(safe_media) != len(media):
        raise ValueError("invalid media record")
    qid = question.get("question_key") or question.get("question_id")
    layout = {"schema_version": "media-layout-v1",
              "question_id": qid, "type_key": typ,
              "source": src, "media": safe_media, "controls": {}}
    family = registry["types"][typ].get("family")

    def safe_ids(raw):
        """Copy an upstream label/id, but never an answer or scoring field."""
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            # upstream ids are preserved exactly (no index-based reordering)
            rec = {k: item[k] for k in ("id",) if k in item}
            if isinstance(item.get("text"), str):
                rec["label"] = item["text"]
            elif isinstance(item.get("label"), str):
                rec["label"] = item["label"]
            out.append(rec)
        return out

    def with_rect(items, slot_name):
        where = geometry.get(slot_name) or {}
        if not isinstance(where, dict):
            raise ValueError(f"geometry.{slot_name} must map stable IDs to regions")
        for rec in items:
            identity = rec.get("id")
            shape = where.get(identity)
            if isinstance(shape, dict):
                if "rect" in shape:
                    rec["rect"] = shape["rect"]
                if "polygon" in shape:
                    rec["polygon"] = shape["polygon"]
            elif shape is not None:
                rec["rect"] = shape
        return items

    if family == "matrix":
        layout["controls"]["rows"] = safe_ids(content.get("rows"))
        layout["controls"]["columns"] = safe_ids(content.get("columns"))
    elif family == "cloze":
        layout["controls"]["blanks"] = with_rect(safe_ids(content.get("blanks")), "blanks")
    elif family == "sequence":
        layout["controls"]["items"] = safe_ids(content.get("items"))
    elif family in ("association", "interaction"):
        layout["controls"]["draggable_items"] = safe_ids(
            content.get("left") or content.get("items"))
        layout["controls"]["drop_zones"] = with_rect(
            safe_ids(content.get("right") or content.get("bins") or content.get("zones")),
            "drop_zones")
    elif family == "image_regions":
        regions = safe_ids(content.get("regions"))
        # original upstream content.regions may include normalized_coordinates.
        by_id = {item["id"]: item for item in (content.get("regions") or [])
                 if isinstance(item, dict) and isinstance(item.get("id"), str)}
        for rec in regions:
            item = by_id.get(rec.get("id")) or {}
            if "normalized_coordinates" in item:
                rec["rect"] = item["normalized_coordinates"]
        layout["controls"]["hotspots"] = with_rect(regions, "hotspots")
    elif family == "container":
        if isinstance(question.get("shared_stimulus_id"), str):
            layout["shared_stimulus_id"] = question["shared_stimulus_id"]
        if isinstance(question.get("child_question_ids"), list):
            layout["child_question_ids"] = question["child_question_ids"]
    result = validate_layout(layout, registry)
    # Never mark a layout as UI-rendered, reviewer-signed or release ready.
    return {"layout": layout, "verification": result,
            "provenance": "upstream_response_schema_plus_verified_media_only",
            "site_ui_status": "UNTESTED"}
