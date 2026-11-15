#!/usr/bin/env python3
"""Fail-closed Phase 2 source-region integration into pinned upstream extractor.

No competing converter: installs one deterministic OCR helper alongside
canonical modules and patches the existing ocr_extract.py question-image path.
Does not alter existing answers, OCR pass settings, fidelity gates or exports.
"""
from pathlib import Path
import argparse
import shutil

IMPORT_ANCHOR = "import analyze_visual as AV\n"
IMPORT_REPLACE = IMPORT_ANCHOR + "import phase2_source_region_ocr as PHASE2_SR\n"

QUESTION_ANCHOR = """        images.append(rec_img)
        all_q_lines.extend(lines)
        if rec_img['mean_confidence'] is not None:"""
QUESTION_REPLACE = """        images.append(rec_img)
        all_q_lines.extend(lines)
        if cfg.get('source_region_extraction', False):
            # Output is source evidence attached to the existing canonical
            # question, not an inferred answer or a publishable replacement.
            source_candidates = PHASE2_SR.extract(
                os.path.join(media, fn), fn, ocr_pass,
                fidelity_passes(cfg), cfg)
            rec_img['source_region_candidates'] = source_candidates
            region_candidates.extend(source_candidates)
        if rec_img['mean_confidence'] is not None:"""

SETUP_ANCHOR = """    all_q_lines = []
    confs = []
    if not tess_ok:"""
SETUP_REPLACE = """    all_q_lines = []
    confs = []
    region_candidates = []
    if not tess_ok:"""

FINISH_ANCHOR = """    rec['ocr_confidence'] = mean
    rec['ocr_min_confidence'] = minc
    return item_ocr, rec"""
FINISH_REPLACE = """    rec['ocr_confidence'] = mean
    rec['ocr_min_confidence'] = minc
    if cfg.get('source_region_extraction', False):
        rec['source_region_candidates'] = region_candidates
        item_ocr['source_region_candidate_count'] = len(region_candidates)
        item_ocr['source_region_agree_count'] = sum(
            bool(c.get('two_pass_agreement')) for c in region_candidates)
        item_ocr['source_region_strict_count'] = sum(
            bool(c.get('usable_as_verified_source')) for c in region_candidates)
    return item_ocr, rec"""


def replace_exact(s, old, new, name):
    if new in s:
        return s
    if s.count(old) != 1:
        raise ValueError("Pinned canonical upstream mismatch: " + name)
    return s.replace(old, new, 1)


def patch(upstream: Path, helper_root: Path):
    original = upstream / "scripts" / "ocr_extract.py"
    dest = upstream / "scripts" / "phase2_source_region_ocr.py"
    seg_dest = upstream / "scripts" / "segment_ui_ocr_regions.py"
    helper = helper_root / "phase2_source_region_ocr.py"
    segmentation = helper_root / "segment_ui_ocr_regions.py"
    for p in (original, helper, segmentation):
        if not p.is_file():
            raise FileNotFoundError(p)
    s = original.read_text(encoding="utf-8")
    for old, new, desc in (
        (IMPORT_ANCHOR, IMPORT_REPLACE, "exact import"),
        (SETUP_ANCHOR, SETUP_REPLACE, "setup"),
        (QUESTION_ANCHOR, QUESTION_REPLACE, "question image OCR"),
        (FINISH_ANCHOR, FINISH_REPLACE, "source candidate output"),
    ):
        s = replace_exact(s, old, new, desc)
    original.write_text(s, encoding="utf-8")
    shutil.copyfile(helper, dest)
    shutil.copyfile(segmentation, seg_dest)
    return original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--helper-root", required=True)
    args = parser.parse_args()
    print(patch(Path(args.upstream), Path(args.helper_root)))


if __name__ == "__main__":
    main()
