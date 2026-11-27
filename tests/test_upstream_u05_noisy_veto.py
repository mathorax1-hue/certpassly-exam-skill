"""Tests for upstream patch v1.3.1-u05-noisy-veto.

Observed failure (SC-900, run 46058365849): 7 yes_no_matrix questions
(q019, q020, q044, q069, q073, q099, q101) have two pixel methods that agree
on the correct key (highlight and image_diff, both reading the pale green
fill), but a third method, checked_box, produces a different key and vetoes
them, because _agreed requires no method to disagree. The checked_box key
is noise: it reads text letters as boxes, so most of its marks fall outside
any cell (for example 121 outside and 5 inside on q019), while the real
methods have all of their marks inside cells.

Fix: before _agreed runs, _drop_noisy_disagreements drops a method's key
only when the methods disagree AND that method's marks are mostly outside
the cells (more than 3x as many outside as inside). A noisy-looking method
that agrees with the others is left alone, so a correct vote is never lost.
The rule covers the matrix detail (marks_in_cells) and the dropdown detail
(marks_on_choices).

Measured on SC-900 (on top of u04): yes_no_matrix visual keys go from 21
to 28 of 41, and inline_dropdown from 28 to 29 of 57. One gained key was
eye-checked against the page image (q019: r1 no, r2 yes, r3 yes) and matches.

Synthetic only: no exam text, keys, or images.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "certpassly-exam-pipeline" / "scripts"))

import analyze_visual as AV


def test_noisy_detail_matrix_counts():
    # Noise: far more marks outside than inside.
    assert AV._noisy_detail({'marks_in_cells': 5, 'marks_outside': 121})
    assert AV._noisy_detail({'marks_in_cells': 3, 'marks_outside': 82})
    # A real method: most marks inside, a few strays outside.
    assert not AV._noisy_detail({'marks_in_cells': 3, 'marks_outside': 0})
    assert not AV._noisy_detail({'marks_in_cells': 3, 'marks_outside': 4})
    # No marks at all is not noise to drop (nothing to veto with).
    assert not AV._noisy_detail({'marks_in_cells': 0, 'marks_outside': 0})


def test_noisy_detail_dropdown_counts():
    assert AV._noisy_detail({'marks_on_choices': 1, 'marks_outside': 50})
    assert not AV._noisy_detail({'marks_on_choices': 2, 'marks_outside': 0})


def test_drop_noisy_disagreements_keeps_agreement():
    # All methods agree: nothing is dropped, even a noisy-looking one.
    keys = {
        'highlight': {'r1': 'no', 'r2': 'yes'},
        'image_diff': {'r1': 'no', 'r2': 'yes'},
        'checked_box': {'r1': 'no', 'r2': 'yes'},
    }
    detail = {'checked_box': {'marks_in_cells': 3, 'marks_outside': 100}}
    assert AV._drop_noisy_disagreements(keys, detail) == keys


def test_drop_noisy_disagreements_drops_only_the_noisy_veto():
    # highlight and image_diff agree; checked_box disagrees and is noisy.
    keys = {
        'highlight': {'r1': 'no', 'r2': 'yes', 'r3': 'yes'},
        'image_diff': {'r1': 'no', 'r2': 'yes', 'r3': 'yes'},
        'checked_box': {'r1': ['no'], 'r2': ['no', 'yes'], 'r3': ['no', 'yes']},
    }
    detail = {
        'highlight': {'marks_in_cells': 3, 'marks_outside': 0},
        'image_diff': {'marks_in_cells': 3, 'marks_outside': 0},
        'checked_box': {'marks_in_cells': 5, 'marks_outside': 121},
    }
    kept = AV._drop_noisy_disagreements(keys, detail)
    assert kept == {
        'highlight': {'r1': 'no', 'r2': 'yes', 'r3': 'yes'},
        'image_diff': {'r1': 'no', 'r2': 'yes', 'r3': 'yes'},
    }


def test_drop_noisy_disagreements_keeps_all_when_no_noisy_method():
    # The methods disagree but none is noisy: nothing is dropped.
    keys = {
        'highlight': {'r1': 'no', 'r2': 'yes'},
        'image_diff': {'r1': 'yes', 'r2': 'no'},
    }
    detail = {
        'highlight': {'marks_in_cells': 2, 'marks_outside': 0},
        'image_diff': {'marks_in_cells': 2, 'marks_outside': 0},
    }
    assert AV._drop_noisy_disagreements(keys, detail) == keys
