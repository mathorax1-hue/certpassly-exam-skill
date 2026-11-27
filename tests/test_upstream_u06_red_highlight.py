"""Tests for upstream patch v1.3.1-u06-red-highlight.

Observed failure (SC-900, run 46058365849): 4 yes_no_matrix questions
(q133, q151, q175, q177) and 6 inline_dropdown questions have their correct
answers marked by a red rectangle drawn around the circle or the choice.
Only image_diff reads them (the rectangle outline changes the grayscale
image), so there is no second method to agree and no key is set. The
highlight detector has ranges for yellow, green and cyan but none for red,
so it finds nothing.

Fix: add a red range to config/ocr.json highlight hsv_ranges (hue 170-179,
saturation at least 50, value at least 80). The red rectangles in these
images have hue about 175. The range is narrow on purpose: red ink is
common in PDFs, and the grid and dropdown key rules (exactly one marked
cell or choice per row or blank) plus the noisy-veto rule (u05) keep stray
red marks from voting or vetoing.

Measured on SC-900 (on top of u04 and u05): yes_no_matrix visual keys go
from 28 to 32 of 41, and inline_dropdown from 29 to 35 of 57. All four
gained matrix keys were eye-checked against the page image and match
(q133 r1 yes / r2 yes / r3 no; q151 r1 no / r2 yes / r3 yes; q175 r1 yes /
r2 no / r3 no; q177 r1 yes / r2 yes / r3 no).

Synthetic only: no exam text, keys, or images.
"""

import json
from pathlib import Path


def _ocr_cfg():
    return json.load(
        open(
            Path(__file__).resolve().parents[1]
            / "vendor"
            / "certpassly-exam-pipeline"
            / "config"
            / "ocr.json"
        )
    )


def test_red_highlight_range_exists():
    cfg = _ocr_cfg()
    red = next(
        (r for r in cfg["highlight"]["hsv_ranges"] if r["name"] == "red"),
        None,
    )
    assert red is not None
    # The red rectangles have hue about 175 (OpenCV HSV wraps red at 179).
    assert red["h_min"] <= 175 <= red["h_max"]
    assert red["s_min"] <= 100
    assert red["v_min"] <= 200


def test_green_highlight_range_still_accepts_pale_fill():
    # u04: the pale green fill has saturation about 35.
    cfg = _ocr_cfg()
    green = next(
        r for r in cfg["highlight"]["hsv_ranges"] if r["name"] == "green"
    )
    assert green["s_min"] <= 35


def test_highlight_ranges_do_not_overlap():
    # Ranges must not overlap in their interior, or one colour would be read
    # as another. Touching at a boundary hue (yellow ends at 40, green starts
    # at 40) is pre-existing and left alone.
    cfg = _ocr_cfg()
    spans = sorted(
        (r["h_min"], r["h_max"], r["name"])
        for r in cfg["highlight"]["hsv_ranges"]
    )
    for (lo1, hi1, n1), (lo2, hi2, n2) in zip(spans, spans[1:]):
        assert hi1 <= lo2, f"{n1} and {n2} overlap"
