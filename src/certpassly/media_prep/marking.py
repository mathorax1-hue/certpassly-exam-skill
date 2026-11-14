"""Raster answer-mark detection (deterministic OpenCV heuristics; NO AI, NO OCR).

Purpose: catch selection marks (drawn circles/rings around options, X marks,
pen strokes, highlight rectangles) that were FLATTENED into a raster question
image. This is a machine advisory used by the selection engine to REFUSE a
question image that looks marked; it is deliberately conservative:

  - it is tuned to minimize FALSE NEGATIVES (a missed mark could leak an
    answer highlight to learners), accepting some false positives (a false
    mark only sends the image to review, never to learners);
  - detection NEVER erases, inpaints or "cleans" anything. The only permitted
    learner output is a different, provably-unmarked source image or a
    re-render of vector/annotation-free PDF content.

Shape model (why ordinary UI borders and text do not trip it):
  pen_shape    hollow component whose dark pixels span >=80% of bbox rows AND
               columns (a drawn circle/ellipse/box/X has edges everywhere;
               words have inter-letter gaps), >=24x16 px, >=0.08% of image,
               AND whose stroke is PEN-LIKE in color: much darker than UI
               chrome (min gray <= 60) or clearly colored (channel spread
               >= 60, e.g. red/blue/green pen). Mid-gray UI borders
               (~90-150 gray, low saturation) are excluded by this rule.
  solid_stroke near-solid elongated component (fill>=0.75, thickness>=4px,
               length>=6% of a dimension, aspect>=3.5) with pen-like color -
               an underline or pen line; word glyphs are sparse (fill~0.2-0.35)
               and 1-2px thin, gray dividers fail the color rule
  filled_dot   compact near-solid near-square blob 8-28px with pen-like
               color (a pen dot); letters have counters/holes (fill<0.85)

Everything is computed on the alpha-flattened RGB image with OpenCV only.
Known limitation (recorded honestly): heavy blur can fade pen marks below
the dark threshold; the independent blur quality gate blocks such images
anyway, and the operator runbook documents it. Vector-drawn marks on a PDF
page (not raster, not annotations) are OUT OF SCOPE for this detector and
are recorded as a documented limitation of the vector render path.
"""
from __future__ import annotations


def _lazy_cv2():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment guard
        from .errors import OperationalError
        raise OperationalError(
            "media-prep marking checks require the visual extra (opencv-python-headless): "
            "python -m pip install -e '.[phase1,visual]'") from exc
    return cv2, np


def _components(mask):
    """Connected components with stats; [(x, y, w, h, sub-mask)]."""
    cv2, np = _lazy_cv2()
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, _area = stats[i]
        if w < 6 or h < 6:
            continue  # speck noise / antialias dust
        sub = (labels[y:y + h, x:x + w] == i)
        out.append((int(x), int(y), int(w), int(h), sub))
    return out


def _hollow_core_fraction(sub):
    """Fraction of the central 40% box that is NOT dark (hollow ring -> high)."""
    h, w = sub.shape
    y0, y1 = int(h * 0.3), max(int(h * 0.7) + 1, int(h * 0.3) + 1)
    x0, x1 = int(w * 0.3), max(int(w * 0.7) + 1, int(w * 0.3) + 1)
    return float(1.0 - sub[y0:y1, x0:x1].mean())


def _coverage(sub):
    rows = float(sub.any(axis=1).mean())
    cols = float(sub.any(axis=0).mean())
    return rows, cols


def detect_marks(pil_rgb) -> dict:
    """Detect pen-like answer marks on an alpha-flattened RGB PIL image.

    Returns a marking summary dict:
      {"detected_mark_boxes": int, "marks": [{x,y,w,h,kind} normalized],
       "dark_fraction": float, "method": "opencv-connected-components-v5",
       "note": "..."}
    Coordinates are normalized to [0,1].
    """
    cv2, np = _lazy_cv2()
    img = np.asarray(pil_rgb.convert("RGB"))
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

    # Dark mask: fixed floor plus adaptive margin below the image median so a
    # dark-theme screenshot (median ~40) only flags true pen-dark marks.
    median = float(np.median(gray))
    thresh = max(70.0, min(110.0, median * 0.55))
    dark = (gray < thresh).astype(np.uint8())
    dark_fraction = float(dark.mean())

    # Pen-like color facts per component: darkest gray value and channel spread.
    chan_spread = img.max(axis=2).astype(int) - img.min(axis=2).astype(int)

    def pen_like(x, y, w, h, sub):
        ys, xs = np.nonzero(sub)
        gs = gray[y:y + h, x:x + w][ys, xs]
        sp = chan_spread[y:y + h, x:x + w][ys, xs]
        return bool(gs.min() <= 60 or sp.max() >= 60)

    min_area_rel = 0.0008
    min_area = min_area_rel * W * H

    marks = []
    for x, y, w, h, sub in _components(dark):
        area = float(sub.sum())
        if area < min_area and not (w >= 24 and h >= 16 and area >= 0.5 * min_area):
            continue
        if not pen_like(x, y, w, h, sub):
            continue  # mid-gray low-saturation UI chrome, not a pen stroke
        fill = area / float(w * h)
        rows, cols = _coverage(sub)
        hollow = _hollow_core_fraction(sub)
        aspect = w / float(h) if h else 0.0
        rel_w, rel_h = w / float(W), h / float(H)
        kind = None
        thickness = area / float(max(w, h)) if max(w, h) else 0.0
        # (a) hollow spanning shape: circle / ellipse / box drawn on top
        if (hollow >= 0.50 and rows >= 0.80 and cols >= 0.80
                and w >= 24 and h >= 16 and 0.25 <= aspect <= 20.0
                and (rel_w >= 0.01 or rel_h >= 0.01)):
            kind = "pen_shape"
        # (a2) thin spanning shape: X marks / crossed strokes fill their core
        # (not hollow) but still span the whole bbox with thin strokes; text
        # words fail the column-coverage rule (inter-letter gaps)
        elif (rows >= 0.85 and cols >= 0.85 and 0.03 <= fill <= 0.5
                and w >= 24 and h >= 16 and thickness <= 18.0
                and (rel_w >= 0.01 or rel_h >= 0.01)):
            kind = "pen_shape"
        # (b) solid elongated stroke: underline / pen line
        elif (fill >= 0.75 and min(w, h) >= 4 and aspect >= 3.5
              and (rel_w >= 0.06 or rel_h >= 0.06)):
            kind = "solid_stroke"
        # (c) compact solid near-square dot: pen dot / filled checkbox
        elif (fill >= 0.85 and 8 <= w <= 28 and 8 <= h <= 28
              and 0.7 <= aspect <= 1.4 and rel_w <= 0.12):
            kind = "filled_dot"
        if kind:
            marks.append(dict(x=round(x / W, 4), y=round(y / H, 4),
                              w=round(w / W, 4), h=round(h / H, 4),
                              kind=kind, px=[x, y, w, h]))

    # B2: selected color UI states can be brighter than the grayscale floor.
    # A blue filled radio (e.g. RGB 20,104,207) has intensity above the
    # dark-mask threshold, so the former detector returned ZERO marks.
    # Search saturated filled controls, hollow selection rings and highlight bars separately.
    # A gray/white hollow radio or dropdown border does not meet this test.
    # A similar-looking colored chart dot is intentionally AMBIGUOUS and
    # blocked rather than mislabeled a proven clean learner answer area.
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    chromatic = ((hsv[:, :, 1] >= 85) & (hsv[:, :, 2] >= 40)).astype(np.uint8)
    for x, y, w, h, sub in _components(chromatic):
        area = int(sub.sum())
        fill = area / float(w * h)
        ratio = w / float(h)
        rows_covered, cols_covered = _coverage(sub)
        hollow = _hollow_core_fraction(sub)
        kind = None
        if (8 <= w <= 36 and 8 <= h <= 36 and
                0.58 <= ratio <= 1.72 and fill >= 0.58 and
                area >= 40 and w / float(W) <= 0.08 and h / float(H) <= 0.08):
            kind = "filled_chromatic_control"
        elif (w >= 24 and h >= 16 and area >= 55 and
              rows_covered >= 0.8 and cols_covered >= 0.8 and
              0.02 <= fill <= 0.56 and hollow >= 0.5 and
              w / float(W) <= 0.65 and h / float(H) <= 0.50):
            kind = "chromatic_pen_ring_or_box"
        elif (w >= 40 and h >= 8 and ratio >= 2.5 and
              area >= 0.0008 * W * H and fill >= 0.65 and
              w / float(W) <= 0.8 and h / float(H) <= 0.2):
            kind = "chromatic_highlight_bar"
        if kind is None:
            continue
        # The dark detector may have caught the same colored component.
        # Avoid inflating a mark count without losing the fail-closed result.
        if any(
            abs((m["px"][0] + m["px"][2] / 2) - (x + w / 2)) < 4 and
            abs((m["px"][1] + m["px"][3] / 2) - (y + h / 2)) < 4
            for m in marks
        ):
            continue
        marks.append({
            "x": round(x / W, 4), "y": round(y / H, 4),
            "w": round(w / W, 4), "h": round(h / H, 4),
            "kind": kind, "px": [x, y, w, h],
        })

    # Deterministic order (top-left first) regardless of component numbering.
    marks.sort(key=lambda m: (m["y"], m["x"], m["w"], m["h"]))
    return {
        "detected_mark_boxes": len(marks),
        "marks": marks,
        "dark_fraction": round(dark_fraction, 6),
        "method": "opencv-connected-components-v4",
        "note": ("advisory machine detection of pen-like selection marks "
                 "(dark/colored hollow shapes, colored filled controls/rings/highlights, solid strokes, pen dots); "
                 "never used to erase or reconstruct content; a detection "
                 "refuses learner eligibility, it does not clean anything; "
                 "heavy blur can fade marks below the dark threshold - the "
                 "blur quality gate independently blocks such images"),
    }


def looks_marked(marking: dict) -> bool:
    """Conservative gate: any detected mark box -> treat as potentially marked."""
    return bool(marking and marking.get("detected_mark_boxes", 0) > 0)
