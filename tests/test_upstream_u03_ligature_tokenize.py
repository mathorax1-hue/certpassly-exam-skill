"""Tests for upstream patch v1.3.1-u03-ligature-tokenize.

Observed failure (SC-900, run 46058365849): lettered-choice questions are
held for missing/extra words that are only a ligature loss. The PDF text
layer lost the "fi" glyph, so the coverage source has fragments ("speci c",
"de ne", "rst") while the export has the whole word ("specific", "define",
"first"). The fidelity coverage check then reports the fragments as missing
and the whole word as extra, and the question is held.

Cause: fidelity.tokenize() only expanded typographic ligature characters
(ﬁ -> fi). It never ran the gap-merge repair that joins split fragments,
so the fragment tokens and the whole-word tokens never compared equal.

Fix: tokenize() runs text_repair.repair() after the typographic expansion
and before lowercasing, so fragments are joined back into the whole word
on both sides of every comparison. The repair is a no-op on complete words
and never touches ordinals ("2nd", "3rd").

Synthetic only: no exam text, keys, or images.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "certpassly-exam-pipeline" / "scripts"))

import fidelity


def test_tokenize_joins_ligature_fragments():
    assert fidelity.tokenize("Choose the speci c setting") == [
        "choose", "the", "specific", "setting",
    ]
    assert fidelity.tokenize("de ne the term") == ["define", "the", "term"]
    assert fidelity.tokenize("the o ce policy") == ["the", "office", "policy"]
    assert fidelity.tokenize("veri cation steps") == ["verification", "steps"]
    assert fidelity.tokenize("the rst option") == ["the", "first", "option"]


def test_tokenize_leaves_complete_words_and_ordinals_alone():
    assert fidelity.tokenize("Define the specific term") == [
        "define", "the", "specific", "term",
    ]
    assert fidelity.tokenize("the 2nd or 3rd parameter") == [
        "the", "2nd", "or", "3rd", "parameter",
    ]
    assert fidelity.tokenize("the first office") == ["the", "first", "office"]


def test_coverage_report_has_no_missing_or_extra_after_repair():
    pdf_tokens = fidelity.tokenize("Choose the speci c setting for the policy")
    export_tokens = fidelity.tokenize("Choose the specific setting for the policy")
    report = fidelity.coverage_report(pdf_tokens, export_tokens)
    assert report["missing_words"] == []
    assert report["extra_words"] == []
    assert report["complete"] is True
