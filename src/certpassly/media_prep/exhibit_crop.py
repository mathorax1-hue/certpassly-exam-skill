"""Source-verified question/exhibit bounding regions (P0 security correction).

The 2026-11-14 director audit proved that a WHOLE-PAGE vector render can be
approved as a "clean learner image" while actually showing neighbouring
questions and their ``Correct Answer:`` key lines (real case: AB-730 q074,
page 59 whole-page render). This module is the corrective core: it NEVER
returns a page-sized region. An exhibit crop is only ever the union of the
question's OWN vector drawings, bounded on both sides by source-verified
text geometry:

  flow start   the target question's own ``QUESTION <n>`` marker line
  flow end     the NEXT ``QUESTION <m>`` marker line, the question's own
               ``Correct Answer:`` line, or the end of page content -
               whichever comes first in the verified reading direction

Reading direction ("flow axis") is established EMPIRICALLY from the source,
never assumed from /Rotate: when a page carries >= 2 question markers, the
axis is the one along which marker numbers strictly increase; otherwise it
is inferred from how consecutive text lines stack inside blocks, with the
page rotation mapping as a last-resort fallback. If the axis cannot be
established, bounds are UNVERIFIED and the question is blocked
(``QUESTION_CROP_UNVERIFIED``) - the engine fails closed.

Background chrome (near-white, un-stroked filled rectangles, page-wide
boxes) is excluded from the drawing union so that "86% vector coverage"
white backgrounds can never masquerade as an exhibit again.

Every crop is finally verified against the page text layer: no question
marker (its own or any neighbour's) and no ``Correct Answer:`` /
``Explanation`` / ``Section`` line may intersect the crop, and no word
inside the crop may match those patterns. Any violation blocks the
question (``ANSWER_TEXT_IN_RENDER``). The text-layer check is a fail-closed
guard on top of the geometric bounds - it is NOT sufficient for text
flattened into pixels, which is why the geometric bounds come first and
the whole-page fallback no longer exists.
"""
from __future__ import annotations

import re

# Status codes (stable contract; mirrored in roles.py blocked reasons).
CROP_OK = "ok"
CROP_NO_EXHIBIT = "no_exhibit"          # path not applicable on this page
CROP_UNVERIFIED = "unverified"          # -> QUESTION_CROP_UNVERIFIED
CROP_ANSWER_TEXT = "answer_text"        # -> ANSWER_TEXT_IN_RENDER

QUESTION_MARKER_RX = re.compile(r"^question\s+(\d+)\s*[.:)]?\s*$", re.I)
ANSWER_LINE_RX = re.compile(
    r"^correct\s+answers?\s*[:.]?\s*\S+", re.I)
EXPLANATION_LINE_RX = re.compile(
    r"^(explanation|section|references?|explanation\s*/\s*reference)\b", re.I)

# A drawing is background chrome when it is a near-white UNSTROKED fill that
# is large (>= 2% of the page) or hugs marker/answer text, or page-wide.
_NEAR_WHITE = 0.97
_BG_AREA_FRAC = 0.02
_PAGEWIDE_FRAC = 0.85
# A verifiable exhibit crop must be a bounded region, not the page.
_MAX_CROP_AREA_FRAC = 0.60
_MAX_AXIS_COVER_FRAC = 0.98
_MIN_CROP_PT = 40.0
_MARGIN_PT = 2.0


def _lines_of(page):
    """[(text, fitz.Rect, block_index)] in content order (text layer)."""
    out = []
    d = page.get_text("dict")
    for bno, block in enumerate(d.get("blocks") or []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines") or []:
            texts = [s.get("text", "") for s in line.get("spans") or []]
            txt = " ".join(t.strip() for t in texts if t.strip()).strip()
            if not txt:
                continue
            out.append((txt, line["bbox"], bno))
    return out


def _rect(bbox):
    import fitz
    return fitz.Rect(bbox)


class _Axis:
    """Reading-direction model: maps a rect to its flow coordinate."""

    def __init__(self, name):
        self.name = name

    def start(self, r):
        """Leading edge of a rect along the flow axis."""
        return self.forward_key(r)[0]

    def end(self, r):
        """Trailing edge of a rect along the flow axis."""
        return self.forward_key(r)[1]

    def forward_key(self, rect):
        """(leading, trailing) components of the rect along the flow axis."""
        if self.name == "+x":
            return (rect.x0, rect.x1)
        if self.name == "-x":
            return (-rect.x1, -rect.x0)
        if self.name == "+y":
            return (rect.y0, rect.y1)
        return (-rect.y1, -rect.y0)


def _detect_axis_from_markers(markers):
    """markers: [(number, rect)]. Axis along which numbers strictly increase."""
    if len(markers) < 2:
        return None
    for name in ("+x", "-x", "+y", "-y"):
        ax = _Axis(name)
        starts = [ax.start(r) for _, r in markers]
        if all(starts[i] < starts[i + 1] for i in range(len(starts) - 1)):
            return ax
    return None


def _detect_axis_from_lines(lines):
    """Infer flow from how consecutive lines inside one block stack."""
    votes = {"+x": 0, "-x": 0, "+y": 0, "-y": 0}
    for (t1, b1, bn1), (t2, b2, bn2) in zip(lines, lines[1:]):
        if bn1 != bn2:
            continue
        r1, r2 = _rect(b1), _rect(b2)
        dx, dy = r2.x0 - r1.x0, r2.y0 - r1.y0
        if abs(dx) > 2 * abs(dy) and abs(dx) > 1.0:
            votes["+x" if dx > 0 else "-x"] += 1
        elif abs(dy) > 2 * abs(dx) and abs(dy) > 1.0:
            votes["+y" if dy > 0 else "-y"] += 1
    best = max(votes, key=votes.get)
    return _Axis(best) if votes[best] >= 2 else None


def _detect_axis_from_rotation(page):
    rot = getattr(page, "rotation", 0) or 0
    return _Axis({0: "+y", 90: "+x", 180: "-y", 270: "-x"}.get(rot, "+y"))


def detect_flow_axis(page, lines, markers):
    """Source-verified reading direction (markers > line stacking > rotation)."""
    ax = _detect_axis_from_markers(markers)
    if ax is not None:
        return ax, "marker-order"
    ax = _detect_axis_from_lines(lines)
    if ax is not None:
        return ax, "line-stacking"
    return _detect_axis_from_rotation(page), "rotation-fallback"


def _drawing_facts(d, page_area, text_safe_rects, annot_rects=()):
    """Classify one vector drawing: (is_background, reason).

    - no rect / infinite: unusable, skip
    - zero-area rects are LINES/POINTS: stroked content, never background
    - page-wide boxes: background chrome
    - near-white UNSTROKED fills that are large or hug marker/answer text:
      background chrome (the "86% white coverage" trap from the audit)
    - drawings CONTAINED in a real annotation rect are annotation APPEARANCES
      (PyMuPDF includes them in get_drawings): the render excludes
      annotations, so the crop union must exclude them too. Containment, not
      intersection: a large content drawing that merely contains/underlaps an
      annotation is still content.
    """
    r = d.get("rect")
    if r is None:
        return True, "no-rect"
    rect = _rect(r)
    area = abs(rect)
    if area < 0:
        return True, "negative-area"
    if area >= _PAGEWIDE_FRAC * page_area:
        return True, "page-wide"
    for ar in annot_rects:
        if (rect.x0 >= ar.x0 - _MARGIN_PT and rect.x1 <= ar.x1 + _MARGIN_PT
                and rect.y0 >= ar.y0 - _MARGIN_PT
                and rect.y1 <= ar.y1 + _MARGIN_PT):
            return True, "annotation-appearance"
    if area <= 0:
        return False, ""  # a stroked line/point is content, not background
    fill = d.get("fill")
    stroke = d.get("color")
    near_white_fill = fill is not None and all(
        c is not None and c >= _NEAR_WHITE for c in fill)
    if near_white_fill and stroke is None:
        if area >= _BG_AREA_FRAC * page_area:
            return True, "near-white-large-fill"
        for tr in text_safe_rects:
            if rect.intersects(tr):
                return True, "near-white-text-backdrop"
    return False, ""


def _intersects_any(rect, rects):
    return any(rect.intersects(r) for r in rects)


def question_exhibit_crop(page, source_number):
    """Compute the source-verified exhibit crop for one question on one page.

    Returns a facts dict; ``status`` is one of CROP_OK / CROP_NO_EXHIBIT /
    CROP_UNVERIFIED / CROP_ANSWER_TEXT. On CROP_OK, ``clip_unrotated`` is the
    (x0, y0, x1, y1) crop in UNROTATED page points (the same space as
    get_image_rects / get_drawings).
    """
    lines = _lines_of(page)
    markers, answer_lines, explanation_lines = [], [], []
    for txt, bbox, _bno in lines:
        r = _rect(bbox)
        m = QUESTION_MARKER_RX.match(txt)
        if m:
            markers.append((int(m.group(1)), r))
        elif ANSWER_LINE_RX.match(txt):
            answer_lines.append(r)
        elif EXPLANATION_LINE_RX.match(txt):
            explanation_lines.append(r)

    our = next((r for n, r in markers if n == source_number), None)
    if our is None:
        return {"status": CROP_NO_EXHIBIT,
                "detail": f"QUESTION {source_number} marker not on this page"}

    axis, axis_basis = detect_flow_axis(page, lines, markers)
    if axis is None:  # pragma: no cover - defensive
        return {"status": CROP_UNVERIFIED,
                "detail": "reading direction could not be established"}

    forbidden = [r for _, r in markers] + answer_lines + explanation_lines

    # flow interval: (our marker end, first boundary after it)
    start = axis.end(our)
    boundaries = []
    for n, r in markers:
        if axis.start(r) > start + 1e-6:
            boundaries.append((axis.start(r), f"next-marker QUESTION {n}"))
    for r in answer_lines:
        if axis.start(r) > start + 1e-6:
            boundaries.append((axis.start(r), "correct-answer line"))
    for r in explanation_lines:
        if axis.start(r) > start + 1e-6:
            boundaries.append((axis.start(r), "explanation/section line"))
    if not boundaries:
        # question runs to the end of page CONTENT (not the media box):
        content_end = max(axis.end(_rect(b)) for _, b, _ in lines) if lines else start
        boundaries = [(content_end, "end-of-page-content")]

    end, end_reason = min(boundaries, key=lambda t: t[0])
    if end <= start + _MIN_CROP_PT / 2:
        return {"status": CROP_UNVERIFIED,
                "detail": f"question region after QUESTION {source_number} is "
                          f"too small to bound an exhibit (flow {axis.name})"}

    page_area = abs(page.rect)
    text_safe_rects = forbidden
    # annotation rects (unrotated space): drawings intersecting them are
    # annotation appearances (get_drawings includes them); the annotation-
    # free render must not let them extend the crop union
    annot_rects = []
    try:
        for a in page.annots() or []:
            annot_rects.append(_rect(a.rect))
    except Exception:
        annot_rects = []
    drawings = []
    backgrounds = 0
    try:
        raw_drawings = page.get_drawings()
    except Exception:
        raw_drawings = []
    for d in raw_drawings:
        r = d.get("rect")
        if r is None:
            continue
        rect = _rect(r)
        lo, hi = axis.forward_key(rect)
        # drawing must lie (mostly) inside the open flow interval
        if hi <= start + 1e-6 or lo >= end - 1e-6:
            continue
        is_bg, why = _drawing_facts(d, page_area, text_safe_rects, annot_rects)
        if is_bg:
            backgrounds += 1
            continue
        if _intersects_any(rect, forbidden):
            # a non-background drawing touching marker/answer text cannot be
            # verified as exhibit-only content
            continue
        drawings.append(rect)

    if not drawings:
        return {"status": CROP_NO_EXHIBIT,
                "detail": f"no non-background vector drawings inside the "
                          f"QUESTION {source_number} region "
                          f"({backgrounds} background shapes excluded)"}

    crop = drawings[0]
    for r in drawings[1:]:
        crop = crop | r  # union

    # clamp the union to the question's flow band (never bleed past the
    # answer/next-marker boundary or back over the marker); the axis-key
    # math works for all four flow directions
    lo, hi = axis.forward_key(crop)
    lo = max(lo, start)
    hi = min(hi, end)
    if axis.name == "+x":
        crop = _rect((lo, crop.y0, hi, crop.y1))
    elif axis.name == "-x":
        crop = _rect((-hi, crop.y0, -lo, crop.y1))
    elif axis.name == "+y":
        crop = _rect((crop.x0, lo, crop.x1, hi))
    else:
        crop = _rect((crop.x0, -hi, crop.x1, -lo))

    if crop.is_empty or abs(crop) <= 0:
        return {"status": CROP_NO_EXHIBIT,
                "detail": "exhibit crop collapsed to empty after band clamping"}

    # --- verification: nothing forbidden may touch the final crop ----------
    for r in forbidden:
        if crop.intersects(r):
            kind = ("answer" if r in answer_lines or r in explanation_lines
                    else "marker")
            if kind == "answer":
                return {"status": CROP_ANSWER_TEXT,
                        "detail": "exhibit crop intersects a Correct Answer/"
                                  "Explanation/Section line"}
            return {"status": CROP_UNVERIFIED,
                    "detail": "exhibit crop intersects a QUESTION marker line"}

    # text-layer guard INSIDE the crop (fail-closed regex, additional to the
    # geometric bounds)
    for txt, bbox, _bno in lines:
        r = _rect(bbox)
        if not (crop.x0 - 1 <= r.x1 and r.x0 <= crop.x1 + 1
                and crop.y0 - 1 <= r.y1 and r.y0 <= crop.y1 + 1):
            continue
        if QUESTION_MARKER_RX.match(txt):
            return {"status": CROP_UNVERIFIED,
                    "detail": f"question marker text {txt!r} inside the crop"}
        if ANSWER_LINE_RX.match(txt) or EXPLANATION_LINE_RX.match(txt):
            return {"status": CROP_ANSWER_TEXT,
                    "detail": f"answer/explanation text {txt!r} inside the crop"}

    # boundedness: a crop that is basically the page is NOT a verified exhibit
    if abs(crop) > _MAX_CROP_AREA_FRAC * page_area:
        return {"status": CROP_UNVERIFIED,
                "detail": f"exhibit region covers {abs(crop) / page_area:.0%} "
                          f"of the page; too large to verify as exhibit-only"}
    pr = page.rect
    if (crop.width >= _MAX_AXIS_COVER_FRAC * pr.width
            and crop.height >= _MAX_AXIS_COVER_FRAC * pr.height):
        return {"status": CROP_UNVERIFIED,
                "detail": "exhibit region spans the whole page in both axes"}

    return {
        "status": CROP_OK,
        "clip_unrotated": (round(crop.x0, 2), round(crop.y0, 2),
                           round(crop.x1, 2), round(crop.y1, 2)),
        "crop_width_pt": round(crop.width, 2),
        "crop_height_pt": round(crop.height, 2),
        "axis": axis.name,
        "axis_basis": axis_basis,
        "page_rotation_deg": getattr(page, "rotation", 0) or 0,
        "marker_rect": [round(v, 2) for v in our],
        "end_bound_reason": end_reason,
        "drawings_used": len(drawings),
        "backgrounds_excluded": backgrounds,
        "margin_note": f"crop is the exact union of the question's own "
                       f"{len(drawings)} non-background vector drawings, "
                       f"clamped to its marker/answer-verified band",
    }


def display_clip(page, clip_unrotated):
    """Map an UNROTATED-space clip to the DISPLAY space get_pixmap expects.

    PyMuPDF's page.get_pixmap(clip=...) interprets the rect in the ROTATED
    (display) coordinate system, while text/image/drawing geometry is
    reported in UNROTATED points. Rendering an unrotated rect directly is
    silently WRONG on rotated pages (the 2026-11-14 audit's q074 render was
    only accidentally correct because it used the whole page). This mapping
    is the fix.
    """
    import fitz
    r = fitz.Rect(*clip_unrotated)
    rot = getattr(page, "rotation", 0) or 0
    if rot == 0:
        return (round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2))
    d = r * page.rotation_matrix
    return (round(min(d.x0, d.x1), 2), round(min(d.y0, d.y1), 2),
            round(max(d.x0, d.x1), 2), round(max(d.y0, d.y1), 2))


def unrotate_clip(page, clip_display):
    """Inverse of display_clip: DISPLAY-space rect -> UNROTATED points."""
    import fitz
    r = fitz.Rect(*clip_display)
    rot = getattr(page, "rotation", 0) or 0
    if rot == 0:
        return (round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2))
    m = ~page.rotation_matrix
    d = r * m
    return (round(min(d.x0, d.x1), 2), round(min(d.y0, d.y1), 2),
            round(max(d.x0, d.x1), 2), round(max(d.y0, d.y1), 2))


def verify_render_clip(pdf_path, page_no, clip, source_number):
    """Gate-side re-verification of a rendered learner image.

    ``clip`` is the DISPLAY-space rect recorded in the manifest render
    record. Re-derives the question geometry from the PINNED source PDF and
    refuses (status CROP_ANSWER_TEXT / CROP_UNVERIFIED) when the clip region
    contains answer-key text, explanation/section text, any question marker,
    or cannot be tied to the question's own verified band. This is what
    makes "regenerate the manifest around a leaky whole-page render" a
    detected attack instead of a pass.
    """
    import fitz
    doc = fitz.open(pdf_path)
    if not (1 <= page_no <= doc.page_count):
        return {"status": CROP_UNVERIFIED, "detail": "render page out of range"}
    page = doc[page_no - 1]
    clip_unrot = unrotate_clip(page, clip)
    crop = fitz.Rect(*clip_unrot)

    lines = _lines_of(page)
    markers, answer_lines, explanation_lines = [], [], []
    for txt, bbox, _bno in lines:
        r = fitz.Rect(bbox)
        m = QUESTION_MARKER_RX.match(txt)
        if m:
            markers.append((int(m.group(1)), r))
        elif ANSWER_LINE_RX.match(txt):
            answer_lines.append(r)
        elif EXPLANATION_LINE_RX.match(txt):
            explanation_lines.append(r)

    # hard content invariants: NO marker / answer / explanation text may
    # intersect the rendered region, regardless of the claimed question
    for r in [x for _, x in markers] + answer_lines + explanation_lines:
        if crop.intersects(r):
            what = ("question marker" if r in [x for _, x in markers]
                    else "Correct Answer / Explanation / Section")
            return {"status": (CROP_ANSWER_TEXT if what != "question marker"
                               else CROP_UNVERIFIED),
                    "detail": f"rendered region intersects a {what} line"}

    for txt, bbox, _bno in lines:
        r = fitz.Rect(bbox)
        if not (crop.x0 - 1 <= r.x1 and r.x0 <= crop.x1 + 1
                and crop.y0 - 1 <= r.y1 and r.y0 <= crop.y1 + 1):
            continue
        if QUESTION_MARKER_RX.match(txt):
            return {"status": CROP_UNVERIFIED,
                    "detail": f"marker text {txt!r} inside the rendered region"}
        if ANSWER_LINE_RX.match(txt) or EXPLANATION_LINE_RX.match(txt):
            return {"status": CROP_ANSWER_TEXT,
                    "detail": f"answer text {txt!r} inside the rendered region"}

    # whole-page renders are categorically unverifiable as exhibit crops
    pr = page.rect
    if (crop.width >= _MAX_AXIS_COVER_FRAC * pr.width
            and crop.height >= _MAX_AXIS_COVER_FRAC * pr.height):
        return {"status": CROP_UNVERIFIED,
                "detail": "rendered region spans the whole page in both axes "
                          "(whole-page renders are never learner images)"}

    # tie the clip to the question's own band when the marker is on the page
    our = next((r for n, r in markers if n == source_number), None)
    band_fact = None
    if our is not None:
        axis, _basis = detect_flow_axis(page, lines, markers)
        start = axis.end(our)
        bounds = [axis.start(r) for n, r in markers if axis.start(r) > start + 1e-6]
        bounds += [axis.start(r) for r in answer_lines if axis.start(r) > start + 1e-6]
        bounds += [axis.start(r) for r in explanation_lines
                   if axis.start(r) > start + 1e-6]
        end = min(bounds) if bounds else None
        lo, hi = axis.forward_key(crop)
        if lo < start - _MARGIN_PT or (end is not None and hi > end + _MARGIN_PT):
            return {"status": CROP_UNVERIFIED,
                    "detail": "rendered region is not inside the question's "
                              "marker/answer-verified band"}
        band_fact = {"axis": axis.name, "inside_band": True}
    else:
        band_fact = {"axis": None, "inside_band": None,
                     "note": "question marker not on this page; only the "
                             "no-answer/no-marker content invariants applied"}

    return {"status": CROP_OK, "clip_unrotated": clip_unrot,
            "source_number": source_number, "band": band_fact}
