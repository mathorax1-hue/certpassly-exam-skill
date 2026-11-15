#!/usr/bin/env python3
"""Fail-closed Phase 3 interaction-structure integration into pinned upstream.

No competing converter: installs the deterministic Phase 3 reconstruction
module alongside canonical modules and patches the existing pinned
analyze_visual.py and build_technical_export.py.

analyze_visual.py: when the canonical marker-box flow leaves an item's
rows or blanks empty, the item's Phase 2 strict source regions rebuild the
native layout (matrix rows; drop-down blanks with choices and sentence
text). Structure only: no answer keys, no selected options, no confidence
threshold or fidelity-gate changes.

build_technical_export.py: when a native interaction was built but the item
is held (answer key not reliable, or the fidelity gate failed), the built
structure is recorded on the hold record instead of being discarded, so
every held item shows its native structure or its exact blocker. This also
fixes a latent path where an item with a built learner but no reliable key
could return no hold record at all and crash the export loop.
"""
from pathlib import Path
import argparse
import shutil

ANALYZE_IMPORT_ANCHOR = "import vision_util as V\n"
ANALYZE_IMPORT_REPLACE = ANALYZE_IMPORT_ANCHOR + \
    "import phase3_interaction_reconstruction as PHASE3\n"

ANALYZE_ITEM_ANCHOR = """            for name, marks in methods.items():
                k2, _, _, _ = key_dropdown(L, marks)
                if k2:
                    d['key_by_method'][name] = k2
        res[k] = d
"""
ANALYZE_ITEM_REPLACE = """            for name, marks in methods.items():
                k2, _, _, _ = key_dropdown(L, marks)
                if k2:
                    d['key_by_method'][name] = k2
        # Phase 3: when the canonical marker-box flow found no structure,
        # rebuild the native interaction layout from the integrated Phase 2
        # strict source regions. Structure only: no answer keys, no
        # selected options, no confidence or fidelity threshold changes.
        try:
            d = PHASE3.fill_item_structure(d, r, L)
        except Exception as exc:  # fail closed: keep the canonical draft
            d['notes'].append('phase3 structure reconstruction failed: '
                              '%s' % exc)
        res[k] = d
"""

EXPORT_INIT_ANCHOR = """    q = None
    if not (result['held'] or not result['type']):
        typ = result['type']
        learner, interaction, err = build_learner(typ, item, visual, ocr_item, exam_code)
        if err:
            hold['reason'] = err
        else:"""
EXPORT_INIT_REPLACE = """    q = None
    built_structure = None
    if not (result['held'] or not result['type']):
        typ = result['type']
        learner, interaction, err = build_learner(typ, item, visual, ocr_item, exam_code)
        if err:
            hold['reason'] = err
            hold['structure_blocker'] = err
        else:
            built_structure = {'type': typ, 'interaction': {
                k: v for k, v in (interaction or {}).items()
                if not str(k).startswith('_')}}"""

EXPORT_GATE_ANCHOR = """        if not gate['ok']:
            hold['reason'] = gate['reason'] or hold['reason']
            return None, hold, result, gate
        return q, None, result, gate
"""
EXPORT_GATE_REPLACE = """        if not gate['ok']:
            hold['reason'] = gate['reason'] or hold['reason']
            if built_structure:
                hold['native_structure'] = built_structure
            return None, hold, result, gate
        if q is None:
            # Built learner but no reliable answer key: keep the item held
            # with its native structure instead of returning no hold record.
            if built_structure:
                hold['native_structure'] = built_structure
            return None, hold, result, gate
        return q, None, result, gate
"""

EXPORT_TAIL_ANCHOR = """    if q is None:
        return None, hold, result, None
    return q, None, result, None
"""
EXPORT_TAIL_REPLACE = """    if q is None:
        if built_structure:
            hold['native_structure'] = built_structure
        return None, hold, result, None
    return q, None, result, None
"""


def replace_exact(s, old, new, name):
    if new in s:
        return s
    if s.count(old) != 1:
        raise ValueError("Pinned canonical upstream mismatch: " + name)
    return s.replace(old, new, 1)


def patch(upstream: Path, helper_root: Path):
    analyze = upstream / "scripts" / "analyze_visual.py"
    export = upstream / "scripts" / "build_technical_export.py"
    helper = helper_root / "phase3_interaction_reconstruction.py"
    for p in (analyze, export, helper):
        if not p.is_file():
            raise FileNotFoundError(p)

    a = analyze.read_text(encoding="utf-8")
    a = replace_exact(a, ANALYZE_IMPORT_ANCHOR, ANALYZE_IMPORT_REPLACE,
                      "analyze_visual import")
    a = replace_exact(a, ANALYZE_ITEM_ANCHOR, ANALYZE_ITEM_REPLACE,
                      "analyze_visual item tail")
    analyze.write_text(a, encoding="utf-8")

    e = export.read_text(encoding="utf-8")
    e = replace_exact(e, EXPORT_INIT_ANCHOR, EXPORT_INIT_REPLACE,
                      "export_one built-structure init")
    e = replace_exact(e, EXPORT_GATE_ANCHOR, EXPORT_GATE_REPLACE,
                      "export_one gate tail")
    e = replace_exact(e, EXPORT_TAIL_ANCHOR, EXPORT_TAIL_REPLACE,
                      "export_one final tail")
    export.write_text(e, encoding="utf-8")

    shutil.copyfile(helper, upstream / "scripts" /
                    "phase3_interaction_reconstruction.py")
    return analyze, export


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--helper-root", required=True)
    args = parser.parse_args()
    print(patch(Path(args.upstream), Path(args.helper_root)))


if __name__ == "__main__":
    main()
