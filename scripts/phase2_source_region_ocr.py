"""Original-PDF screenshot region OCR integrated into canonical extraction.

This is Stage 2 SOURCE extraction, not question classification or answer
inference. Retain full-image OCR and all strict fidelity checks unchanged.
New OCR text is stored only as a traceable source-region candidate and NEVER
overwrites source text or silently promotes a held item.
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


def deduplicate_source_regions(found, overlap_threshold=0.82):
    """Drop near-identical nested OCR panels without merging distinct UI boxes."""
    def area(box):
        return max(0, box[2] - box[0]) * max(0, box[3] - box[1])

    def iou(one, two):
        dx = max(0, min(one[2], two[2]) - max(one[0], two[0]))
        dy = max(0, min(one[3], two[3]) - max(one[1], two[1]))
        intersection = dx * dy
        union = area(one) + area(two) - intersection
        return intersection / union if union else 0.0

    kept = []
    # Favor the source crop preserving MORE original text, not an inset copy
    # that clips leading/trailing letters. Compare only the same region kind.
    for row in sorted(found, key=lambda r: (-area(r["bbox"]),
                                            r["bbox"][1], r["bbox"][0],
                                            r["kind"])):
        if any(row["kind"] == prev["kind"] and
               iou(row["bbox"], prev["bbox"]) >= overlap_threshold
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

def extract(image_path, filename, ocr_pass, pass_specs, cfg, *, max_regions=24):
    """Return source-region candidates with strict two-pass OCR evidence."""
    with open(image_path, "rb") as fh:
        raw = fh.read()
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return []
    H, W = image.shape[:2]
    if H == 0 or W == 0:
        return []
    found = deduplicate_source_regions(regions(image) + light_ui_rectangles(image))
    if not found:
        # Some screenshots have source text without a bordered control.
        # Extract actual ink-line bands as source candidates only.
        found = text_row_subregions(
            image, {"kind": "unboxed_source_text", "bbox": [0, 0, W, H]},
            max_bands=16)
    # Keep canonical full-image OCR as before. Extra text-band candidates
    # supplement source extraction without replacing existing evidence.
    derived = []
    for parent in found:
        if parent["kind"].endswith("_text_band"):
            continue
        derived.extend(text_row_subregions(image, parent))
    # Reserve room for each distinct original panel, then use remaining
    # OCR budget for individual text bands. The previous all-or-nothing cap
    # discarded every text band on busy SharePoint screenshots (q007).
    parents = sorted(found, key=lambda d: (d["bbox"][1], d["bbox"][0], d["kind"]))
    child_bands = deduplicate_source_regions(derived)
    if len(parents) >= max_regions:
        found = parents[:max_regions]
    else:
        found = sorted(parents + child_bands[:max_regions-len(parents)],
                       key=lambda d: (d["bbox"][1], d["bbox"][0], d["kind"]))
    if not found or len(pass_specs) < 2:
        return []
    candidates = []
    for item in found:
        x0, y0, x1, y1 = map(int, item["bbox"])
        if x0 < 0 or y0 < 0 or x1 > W or y1 > H or x0 >= x1 or y0 >= y1:
            continue
        crop = image[y0:y1, x0:x1]
        ok, encoded = cv2.imencode(".png", crop)
        if not ok:
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
            "crop_sha256": hashlib.sha256(encoded.tobytes()).hexdigest(),
            "kind": item["kind"],
            "bbox_pixels": [x0, y0, x1, y1],
            "source_dimensions": [W, H],
            "ocr_text_candidate": passes[0].get("text") or "",
            "two_pass_agreement": agreed,
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
