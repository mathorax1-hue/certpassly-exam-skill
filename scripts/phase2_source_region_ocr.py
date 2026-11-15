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
    pad = 7
    if x1 - x0 < 100 or y1 - y0 < 50:
        return []
    gray = cv2.cvtColor(image[y0 + pad:y1 - pad, x0 + pad:x1 - pad],
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
         "bbox": [x0 + pad, y0 + pad + max(0, a - 4),
                  x1 - pad, y0 + pad + min(gray.shape[0], b + 5)]}
        for a, b in bands
    ]

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
    found = regions(image)
    # Keep canonical full-image OCR as before. Extra text-band candidates
    # supplement source extraction without replacing existing evidence.
    derived = []
    for parent in found:
        derived.extend(text_row_subregions(image, parent))
    found = sorted(found + derived,
                   key=lambda d: (d["bbox"][1], d["bbox"][0], d["kind"]))
    if len(found) > max_regions:
        # Do not discard the already-known parent controls when the image
        # contains too many supplemental text bands.
        found = sorted(regions(image),
                       key=lambda d: (d["bbox"][1], d["bbox"][0], d["kind"]))
    if len(found) > max_regions or len(pass_specs) < 2:
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
