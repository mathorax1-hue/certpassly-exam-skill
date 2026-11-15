#!/usr/bin/env python3
"""Patch pinned upstream visual classification, without a second converter.

Fail closed if the reviewed upstream code changed. The only behavior added is
source-image-text evidence for Yes/No and dropdown category recognition.
No OCR confidence, answer certainty, or fidelity thresholds are altered.
"""
from pathlib import Path
import argparse

EXPECTED_OLD = """def kind_of(stem):
    s = stem.lower()
    if 'select yes if the statement is true' in s: return 'yes_no'
    if 'completes the sentence' in s or 'drop-down' in s or 'answer area' in s: return 'dropdown'
    return 'unknown'
"""

NEW = """def kind_of(stem, ocr_lines=None):
    # Use original source-image OCR as corroborating type evidence, never
    # as a substitute for answer-key, word coverage or confidence gates.
    s = (stem or '').lower()
    lines = [str(line.get('text') or '').strip().lower() for line in (ocr_lines or [])]
    source = ' '.join(lines)
    has_yes = any(line in ('yes', 'yes.') for line in lines)
    has_no = any(line in ('no', 'no.') for line in lines)
    yes_no_instruction = ('select yes if the statement is true' in s or
                          'select yes if the statement is true' in source or
                          'select yes if true' in s or
                          'select yes if true' in source)
    if yes_no_instruction or (has_yes and has_no and
                            ('statement' in s or 'statement' in source)):
        return 'yes_no'
    if ('completes the sentence' in s or 'completes the sentence' in source or
        'drop-down' in s or 'drop-down' in source or
        'dropdown' in s or 'dropdown' in source):
        return 'dropdown'
    # "Answer Area" alone is not sufficient: the same heading appears
    # on matrices, hotspot questions, and drag/drop items.
    return 'unknown'
"""

OLD_INIT = "d = dict(kind=kind_of(r.get('stem') or ''), qimg=qimg, exhibits=r['question_images'][:-1], aimg=r.get('answer_images') or [], notes=[])"
NEW_INIT = "d = dict(kind='unknown', qimg=qimg, exhibits=r['question_images'][:-1], aimg=r.get('answer_images') or [], notes=[])"

OLD_LINES = "L, (W, H) = V.ocr_lines(img_path); d['ocr'] = [dict(t=l['text'], x=round(l['x'], 3), y=round(l['y'], 3), c=int(l['minconf'])) for l in L]"
NEW_LINES = OLD_LINES + "\n        d['kind'] = kind_of(r.get('stem') or '', L)"

def patch(path: Path):
    before = path.read_text(encoding="utf-8")
    if NEW in before and NEW_INIT in before and NEW_LINES in before:
        return "already_patched"
    expected = [(EXPECTED_OLD, NEW), (OLD_INIT, NEW_INIT), (OLD_LINES, NEW_LINES)]
    for old, new in expected:
        if before.count(old) != 1:
            raise ValueError("Refusing unsupported upstream visual source layout: " + old[:52])
        before = before.replace(old, new, 1)
    path.write_text(before, encoding="utf-8")
    return "patched"

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--upstream", required=True, help="Verified clone of canonical upstream")
    args = p.parse_args()
    target = Path(args.upstream) / "scripts/analyze_visual.py"
    if not target.is_file():
        raise SystemExit("Original upstream visual analyzer missing")
    print(patch(target))
if __name__ == "__main__":
    main()
