"""Tests for upstream patch v1.3.1-u04-pale-green-marks.

Observed failure (SC-900, run 46058365849): 41 yes_no_matrix questions are
held because no pixel method reads the answer key. The correct answers are
marked by a pale green fill in the answer image (BGR about [191, 221, 192]).
That fill is almost invisible in grayscale (max difference about 53, below
the diff_threshold of 60), its saturation (about 35) is below the green
highlight range minimum (60), and the highlight marks that are collected
are never wired into the key at all. So image_diff finds nothing, highlight
finds nothing, and the key needs two agreeing methods.

Fix (three parts, all needed for the two-family agreement):
- answer_area.diff_marks unions a green-excess mask (G minus the larger of
  R and B, threshold diff_green_threshold 15) with the grayscale mask, so
  the pale fill counts as an image_diff mark (family 'difference').
- config/ocr.json green highlight s_min lowered 60 -> 30, so the pale fill
  (saturation about 35) counts as a highlight mark (family 'colour').
- analyze_visual wires the collected highlight marks into the marks dict,
  so highlight can agree with image_diff. A noisy highlight that does not
  give exactly one marked cell per row does not vote and cannot veto.

Measured on SC-900: 21 of 41 held yes_no_matrix questions now get a visual
key, each from two agreeing methods. Two were eye-checked against the page
image (q001 r1 no / r2 yes / r3 no; q006 all three yes) and match.

Synthetic only: no exam text, keys, or images. The greenness test uses
fabricated pixel values, not a real image.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "certpassly-exam-pipeline" / "scripts"))

import numpy as np

import answer_area as A


def test_greenness_separates_pale_green_fill_from_white_and_text():
    # BGR: pale green fill, white paper, near-neutral grey text.
    bgr = np.array(
        [
            [[191, 221, 192], [251, 251, 251], [100, 100, 100]],
            [[191, 221, 192], [250, 250, 250], [120, 120, 120]],
        ],
        dtype=np.uint8,
    )
    g = A._greenness(bgr)
    assert g[0, 0] > 25 and g[1, 0] > 25
    assert abs(g[0, 1]) < 2 and abs(g[0, 2]) < 2
    assert abs(g[1, 1]) < 2 and abs(g[1, 2]) < 2


def test_diff_green_threshold_default_is_15():
    assert A.DEFAULTS["diff_green_threshold"] == 15
    assert A.DEFAULTS["diff_threshold"] == 60


def test_green_highlight_range_accepts_pale_fill():
    import json

    cfg = json.load(
        open(
            Path(__file__).resolve().parents[1]
            / "vendor"
            / "certpassly-exam-pipeline"
            / "config"
            / "ocr.json"
        )
    )
    green = next(
        r for r in cfg["highlight"]["hsv_ranges"] if r["name"] == "green"
    )
    # The pale fill has saturation about 35; the old minimum of 60 rejected it.
    assert green["s_min"] <= 35
    assert green["h_min"] <= 59 <= green["h_max"]


def test_highlight_is_wired_into_answer_area_marks():
    import analyze_visual as AV
    import inspect

    src = inspect.getsource(AV)
    assert "'highlight': methods.get('highlight')" in src
