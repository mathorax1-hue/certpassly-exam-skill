"""Original-PDF screenshot region OCR integrated into canonical extraction.

This is Stage 2 SOURCE extraction, not question classification or answer
inference. Retain full-image OCR and all strict fidelity checks unchanged.
New OCR text is stored only as a traceable source-region candidate and NEVER
overwrites source text or silently promotes a held item.

Input-side region preparation only: small crops are grown before the unchanged
two-pass OCR, and regions are split/localized by pure ink geometry. The pass
settings, confidence floors and agreement rules always stay exactly as the
canonical upstream config defines them.
"""
from __future__ import annotations

import hashlib
import os
import tempfile

import cv2
import numpy as np

try:
    from .segment_ui_ocr_regions import regions
except ImportError:
    # Canonical upstream imports scripts directly from its scripts/ directory.
    from segment_ui_ocr_regions import regions


def _norm(text):
    import re
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))



def text_row_subregions(image, parent, max_bands=8):
    """Isolate individual source text bands inside a detected control.

    Detect actual ink rows geometrically; never infer a question type, word or
    selected answer. Only supplemental OCR candidates are produced.
    """
    x0, y0, x1, y1 = map(int, parent["bbox"])
    h, w = image.shape[:2]
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return []
    # The detector's enclosed-control bbox is already inset from its rule.
    # Cropping an additional 7 horizontal pixels deleted leading characters
    # (e.g. "install" -> "nstall") in the original AB-900 screenshots.
    # Keep a small inner margin for row analysis, but restore the full text
    # width when emitting the actual OCR crop.
    pad_y = 7
    pad_x = 2
    if x1 - x0 < 100 or y1 - y0 < 50:
        return []
    gray = cv2.cvtColor(image[y0 + pad_y:y1 - pad_y,
                              x0 + pad_x:x1 - pad_x],
                        cv2.COLOR_BGR2GRAY)
    if gray.size == 0:
        return []
    # Remove major enclosing edges by insetting. Counting ink in the
    # horizontal direction preserves multiword statements and dropdown options.
    ink = (gray < 170).sum(axis=1)
    needed = max(4, int(gray.shape[1] * .012))
    active = np.flatnonzero(ink >= needed)
    if len(active) < 10:
        return []
    bands = []
    start = last = int(active[0])
    for current in active[1:]:
        current = int(current)
        if current - last <= 5:
            last = current
        else:
            if last - start >= 6:
                bands.append((start, last))
            start = last = current
    if last - start >= 6:
        bands.append((start, last))
    if not 2 <= len(bands) <= max_bands:
        return []
    return [
        {"kind": parent["kind"] + "_text_band",
         # Give OCR its original first/last character and ~3 px top/bottom
         # breathing room; keep the crop inside the source image bounds.
         "bbox": [x0, y0 + pad_y + max(0, a - 7),
                  x1, y0 + pad_y + min(gray.shape[0], b + 8)]}
        for a, b in bands
    ]


def _area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _iou(one, two):
    dx = max(0, min(one[2], two[2]) - max(one[0], two[0]))
    dy = max(0, min(one[3], two[3]) - max(one[1], two[1]))
    intersection = dx * dy
    union = _area(one) + _area(two) - intersection
    return intersection / union if union else 0.0


def deduplicate_source_regions(found, overlap_threshold=0.82):
    """Drop near-identical nested OCR panels without merging distinct UI boxes."""
    kept = []
    # Favor the source crop preserving MORE original text, not an inset copy
    # that clips leading/trailing letters. Compare only the same region kind.
    for row in sorted(found, key=lambda r: (-_area(r["bbox"]),
                                            r["bbox"][1], r["bbox"][0],
                                            r["kind"])):
        if any(row["kind"] == prev["kind"] and
               _iou(row["bbox"], prev["bbox"]) >= overlap_threshold
               for prev in kept):
            continue
        kept.append(row)
    return sorted(kept, key=lambda r: (r["bbox"][1], r["bbox"][0],
                                      r["kind"]))


def light_ui_rectangles(image):
    """Find low-contrast rectangular source text controls in admin UI shots.

    Canny contour geometry permits real source-gray controls that binary
    threshold=115 misses. It never reads selected answers or infers keys.
    Source crops are later passed through BOTH original OCR confidence gates.
    """
    h, w = image.shape[:2]
    if h < 60 or w < 150:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 30, 90)
    controls = []
    for contour in cv2.findContours(edges, cv2.RETR_LIST,
                                    cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, ww, hh = cv2.boundingRect(contour)
        if not (80 <= ww <= w * .95 and 17 <= hh <= h * .30
                and 2.2 <= ww / max(hh, 1) <= 40):
            continue
        approx = cv2.approxPolyDP(contour,
                                 .025 * cv2.arcLength(contour, True), True)
        if len(approx) > 7:
            continue
        # A small inner inset removes gray UI strokes but retains all text.
        box = [x + 3, y + 3, x + ww - 3, y + hh - 3]
        if box[2] <= box[0] + 65 or box[3] <= box[1] + 10:
            continue
        controls.append({"kind": "light_ui_text_control",
                         "bbox": box,
                         "method": "source_canny_low_contrast_rectangle"})
    return deduplicate_source_regions(controls)


def localized_text_region(image, source_band):
    """Tightly bound ink words inside original screenshot rows, not guessed text.

    Vertical dropdown edges are removed from detection, preventing huge blank
    source crops and preserving the original word pixels inside the crop.
    """
    x0, y0, x1, y1 = map(int, source_band["bbox"])
    h, w = image.shape[:2]
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        return None
    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    if gray.shape[0] < 10 or gray.shape[1] < 55:
        return None
    mask = gray < 160
    # Exclude long control edges before measuring horizontal word extent.
    vertical_edges = mask.sum(axis=0) >= gray.shape[0] * .75
    mask[:, vertical_edges] = False
    active = np.flatnonzero(mask.sum(axis=0) >= 2)
    if len(active) < 8:
        return None
    left = max(x0, x0 + int(active[0]) - 3)
    right = min(x1, x0 + int(active[-1]) + 4)
    if right - left < 34 or right - left >= (x1-x0)*.96:
        return None
    return {
        "kind": source_band["kind"] + "_localized",
        "bbox": [left, y0, right, y1],
        "method": "source_ink_extent_without_dropdown_borders",
    }


def word_cluster_regions(image, band, *, min_gap=18, min_width=40,
                         max_clusters=6):
    """Split one source text band at wide ink gaps into word-cluster crops.

    Pure geometry: runs of ink columns separated by >= min_gap blank columns
    are separate source elements (for example a navigation label next to
    toolbar icons). Cropping each cluster separately lets the unchanged
    two-pass OCR read clean source words instead of mixed UI chrome. No text,
    word or meaning is inferred here; every crop still faces both original
    confidence gates.
    """
    x0, y0, x1, y1 = map(int, band["bbox"])
    h, w = image.shape[:2]
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        return []
    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    if gray.shape[0] < 8 or gray.shape[1] < 120:
        return []
    mask = gray < 160
    vertical_edges = mask.sum(axis=0) >= gray.shape[0] * .75
    mask[:, vertical_edges] = False
    active = mask.sum(axis=0) >= 2
    clusters = []
    start = None
    gap = 0
    for i, on in enumerate(active):
        if on:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                clusters.append((start, i - gap))
                start = None
    if start is not None:
        clusters.append((start, len(active) - 1))
    clusters = [(a, b) for a, b in clusters
                if b - a + 1 >= min_width]
    if len(clusters) < 2:
        return []
    out = []
    for a, b in clusters[:max_clusters]:
        left = max(x0, x0 + a - 3)
        right = min(x1, x0 + b + 4)
        if right - left < 30:
            continue
        out.append({
            "kind": band["kind"] + "_word_cluster",
            "bbox": [left, y0, right, y1],
            "method": "source_ink_gap_word_cluster",
        })
    return out


def _prepare_region_crop(image, bbox, small_height=48):
    """Return (native_crop, ocr_crop, prescale) for one source region.

    The canonical OCR passes scale every input by their configured factor
    only. Original AB-900 UI crops can be as small as 13 px tall; at that
    size both unchanged passes misread clear source words. Growing a small
    crop 2x beforehand gives Tesseract the glyph size it needs while the
    90/95 word/overall floors and the two-pass agreement stay untouched.
    Large regions are passed at native size. The native crop is returned
    separately so its hash still verifies against the source image pixels.
    """
    x0, y0, x1, y1 = bbox
    native = image[y0:y1, x0:x1]
    if native.shape[0] and native.shape[0] < small_height:
        return (native, cv2.resize(native, None, fx=2, fy=2,
                                   interpolation=cv2.INTER_CUBIC), 2)
    return native, native, 1


def source_regions(image, *, max_regions=40):
    """Return the canonical prioritized source regions for one source image.

    Pure ink geometry: detected controls, their text bands, localizations,
    word clusters and surviving unboxed rows, in the converter's exact
    source-first priority order and bounded by the same crop budget. This is
    the single region definition shared by the integrated converter and any
    verification tooling; it never infers text, words or meaning.
    """
    H, W = image.shape[:2]
    if H == 0 or W == 0:
        return []
    original_panels = deduplicate_source_regions(regions(image))
    novel_panels = deduplicate_source_regions(light_ui_rectangles(image))
    # Mixed screenshots may contain both boxed controls and unboxed text.
    # Historically the unboxed detector ran only when there were NO controls,
    # silently omitting any standalone source lines in mixed layouts. Keep
    # original panels first and add only non-overlapping unboxed row evidence.
    unboxed_bands = text_row_subregions(
        image, {"kind": "unboxed_source_text", "bbox": [0, 0, W, H]},
        max_bands=16)
    localized_unboxed = []
    if original_panels or novel_panels:
        controls = original_panels + novel_panels
        def overlaps_control(candidate):
            # A full-width detected text row can overlap a UI box even when
            # its actual ink is outside that box. Use measured source pixels,
            # never the row's assumed full-image width, for the collision
            # decision.
            rx0, ry0, rx1, ry1 = candidate["bbox"]
            row_area = max(1, (rx1-rx0)*(ry1-ry0))
            for control in controls:
                x0, y0, x1, y1 = control["bbox"]
                overlap = max(0, min(rx1, x1)-max(rx0, x0)) * max(
                    0, min(ry1, y1)-max(ry0, y0))
                control_area = max(1, (x1-x0)*(y1-y0))
                if overlap / min(row_area, control_area) >= .4:
                    return True
            return False
        kept_unboxed = []
        for row in unboxed_bands:
            # Keep the tight crop the collision decision already measured:
            # without it the surviving full-width row still carries UI chrome
            # that defeats the unchanged strict OCR passes.
            tight = localized_text_region(image, row)
            candidate = tight if tight is not None else row
            if not overlaps_control(candidate):
                kept_unboxed.append(row)
                if tight is not None:
                    localized_unboxed.append(tight)
        unboxed_bands = kept_unboxed
    else:
        original_panels = unboxed_bands
        unboxed_bands = []
    # Source-first priority is mandatory. Otherwise low-contrast newly found
    # UI rectangles can evict formerly verified source OCR for q056/q082.
    original_bands = []
    for panel in original_panels:
        if not panel["kind"].endswith("_text_band"):
            original_bands.extend(text_row_subregions(image, panel))
    other_bands = []
    for panel in novel_panels:
        other_bands.extend(text_row_subregions(image, panel))
    original_bands = deduplicate_source_regions(original_bands)
    # A detected low-contrast control often duplicates an original panel's
    # crop. Drop near-identical light-UI bands so the bounded crop budget is
    # not spent reading the same source pixels twice.
    other_bands = [band for band in other_bands
                   if not any(_iou(band["bbox"], prev["bbox"]) >= 0.82
                              for prev in original_bands)]
    other_bands = deduplicate_source_regions(other_bands)
    localizations = []
    for band in original_panels + original_bands + other_bands:
        if band["kind"].endswith("_text_band"):
            tight = localized_text_region(image, band)
            if tight:
                localizations.append(tight)
    localizations.extend(localized_unboxed)
    localizations = deduplicate_source_regions(localizations)
    # A localized or full-width band can still mix several source elements
    # separated by wide blank gaps; each cluster is its own strict candidate.
    cluster_bands = []
    for band in localizations + other_bands + unboxed_bands:
        cluster_bands.extend(word_cluster_regions(image, band))
    cluster_bands = deduplicate_source_regions(cluster_bands)
    prioritized = (
        original_panels + original_bands + other_bands +
        novel_panels + localizations + cluster_bands + unboxed_bands)
    found = prioritized[:max_regions]
    return sorted(found, key=lambda d: (d["bbox"][1],
                                        d["bbox"][0], d["kind"]))


def extract(image_path, filename, ocr_pass, pass_specs, cfg, *, max_regions=40):
    """Return source-region candidates with strict two-pass OCR evidence."""
    with open(image_path, "rb") as fh:
        raw = fh.read()
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return []
    H, W = image.shape[:2]
    if H == 0 or W == 0:
        return []
    found = source_regions(image, max_regions=max_regions)
    if not found or len(pass_specs) < 2:
        return []
    candidates = []
    for item in found:
        x0, y0, x1, y1 = map(int, item["bbox"])
        if x0 < 0 or y0 < 0 or x1 > W or y1 > H or x0 >= x1 or y0 >= y1:
            continue
        native, ocr_crop, prescale = _prepare_region_crop(
            image, (x0, y0, x1, y1))
        ok, encoded = cv2.imencode(".png", ocr_crop)
        ok_native, encoded_native = cv2.imencode(".png", native)
        if not ok or not ok_native:
            continue
        with tempfile.TemporaryDirectory(prefix="certpassly-phase2-") as t:
            path = os.path.join(t, "source-crop.png")
            with open(path, "wb") as fh:
                fh.write(encoded.tobytes())
            passes = [ocr_pass(path, cfg, spec) for spec in pass_specs[:2]]
        normalized = [_norm(p.get("text")) for p in passes]
        agreed = bool(normalized[0]) and normalized[0] == normalized[1]
        minconfs = [p.get("min_confidence") for p in passes]
        means = [p.get("mean_confidence") for p in passes]
        threshold = (cfg.get("fidelity") or {})
        minword = float(threshold.get("min_word_confidence", 90))
        minoverall = float(threshold.get("min_overall_confidence", 95))
        confidence_pass = all(
            lo is not None and mean is not None and
            float(lo) >= minword and float(mean) >= minoverall
            for lo, mean in zip(minconfs, means)
        )
        candidates.append({
            "source_file": filename,
            "source_image_sha256": hashlib.sha256(raw).hexdigest(),
            # Native source-crop hash: crop the bbox out of the hashed source
            # image and this digest verifies it. ocr_prescale separately
            # records how the OCR input was grown from these exact pixels.
            "crop_sha256": hashlib.sha256(encoded_native.tobytes()).hexdigest(),
            "kind": item["kind"],
            "bbox_pixels": [x0, y0, x1, y1],
            "source_dimensions": [W, H],
            "ocr_prescale": prescale,
            "ocr_text_candidate": passes[0].get("text") or "",
            "two_pass_agreement": agreed,
            # Verified word-level evidence for agreed regions: the primary
            # pass read these words at these confidences and the second
            # pass agreed on the text. Empty for non-agreed regions.
            "verified_words": list(passes[0].get("words") or []) if agreed else [],
            "confidence_pass": confidence_pass,
            "passes": [
                {"id": str(p.get("id")), "min_confidence": p.get("min_confidence"),
                 "mean_confidence": p.get("mean_confidence"),
                 "word_count": len(p.get("words") or [])}
                for p in passes
            ],
            "usable_as_verified_source": agreed and confidence_pass,
            "auto_approved_for_release": False,
        })
    return candidates
