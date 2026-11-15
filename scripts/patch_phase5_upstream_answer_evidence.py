#!/usr/bin/env python3
"""Fail-closed Phase 5 answer-evidence integration into pinned upstream.

No competing converter: installs the deterministic Phase 5 evidence module
(with its Phase 3/4 structure dependencies) alongside canonical modules and
patches the existing pinned build_technical_export.py and fidelity.py.

build_technical_export.py:
- the fidelity OCR record for an item is rebuilt from its Phase 2 strict
  source regions (two-pass agreed words at the unchanged 90/95 floors);
  question images without strict regions keep their raw record and fail
  the gate exactly as before; answer-role images are excluded from the
  learner OCR gate because they are server-only key evidence governed by
  the Phase 4 key gate
- answer keys verified by Phase 5's two-agreeing-methods evidence
  (status verified_pixel_agreed) are applied when the structure they were
  verified against matches the export structure exactly; candidates and
  blocked items never receive keys
- the applied key source is recorded on the technical report, never on
  the site answer payload

fidelity.py:
- key_certainty accepts a Phase 4 verified key under the same canonical
  rule: two or more agreeing independent mark methods, recorded in the
  evidence, with the exported key required to match it

The Phase 4 evidence report path comes from the CERTPASSLY_PHASE4_EVIDENCE
environment variable. Without it nothing is applied (fail-closed default).
"""
from pathlib import Path
import argparse
import shutil

EXPORT_IMPORT_ANCHOR = "import fidelity\n"
EXPORT_IMPORT_REPLACE = EXPORT_IMPORT_ANCHOR + """import phase5_export_evidence as PHASE5

# Phase 5: verified answer-key evidence from the Phase 4 report. Optional:
# without the environment variable nothing is applied (fail-closed).
PHASE5_EVIDENCE = PHASE5.load_phase4_evidence(
    os.environ.get('CERTPASSLY_PHASE4_EVIDENCE'))
"""

EXPORT_HEAD_ANCHOR = """def export_one(item, visual, ocr_item, exam_code, domain, min_conf, fid_cfg=None, deny=None):
    result = qtypes.classify_detailed(item, visual, ocr=ocr_item, min_confidence=min_conf)"""
EXPORT_HEAD_REPLACE = """def export_one(item, visual, ocr_item, exam_code, domain, min_conf, fid_cfg=None, deny=None):
    # Phase 5: attach the item's verified Phase 4 key evidence and rebuild
    # the OCR record from strict source regions (fail-closed; see helper).
    item['_phase4'] = PHASE5_EVIDENCE.get(item.get('question_key'))
    ocr_item, phase5_meta = PHASE5.verified_ocr_item(item, ocr_item)
    result = qtypes.classify_detailed(item, visual, ocr=ocr_item, min_confidence=min_conf)"""

EXPORT_HOLD_ANCHOR = """        'matched_rules': result.get('matched_rules') or [],
    }
"""
EXPORT_HOLD_REPLACE = """        'matched_rules': result.get('matched_rules') or [],
    }
    hold['phase5'] = {
        'ocr': phase5_meta,
        'phase4_status': (item.get('_phase4') or {}).get('status'),
    }
"""

EXPORT_MATRIX_ANCHOR = """    if typ == 'yes_no_matrix':
        key = dict((visual or {}).get('key') or {})
        rows = [r['id'] for r in (visual or {}).get('rows') or []]
        if not key or set(key) != set(rows):
            return key or {}, False
        return key, True"""
EXPORT_MATRIX_REPLACE = """    if typ == 'yes_no_matrix':
        key = dict((visual or {}).get('key') or {})
        rows = [r['id'] for r in (visual or {}).get('rows') or []]
        # Phase 5: the Phase 4 verified pixel-agreed key applies when its
        # structure corresponds to this export's rows. It completes an
        # incomplete canonical key, and when the complete canonical key
        # equals it exactly the Phase 4 agreement corroborates it (the
        # second independent mark method). A canonical key that DISAGREES
        # with the verified key is never overridden: the item stays held.
        p4 = PHASE5.matrix_key_from_phase4(
            item, visual, (item or {}).get('_phase4'))
        if p4:
            if not key or set(key) != set(rows):
                key = p4['key']
            if set(key) == set(rows) and key == p4['key']:
                item['_phase4_applied'] = {
                    'source': 'phase4_pixel_agreed:'
                              + '+'.join(sorted(p4['methods'])),
                    'key': dict(p4['key'])}
        if not key or set(key) != set(rows):
            return key or {}, False
        return key, True"""

EXPORT_DROPDOWN_ANCHOR = """    if typ in ('inline_dropdown', 'multi_blank_dropdown'):
        selected = learner.get('_dropdown_selected') or {}"""
EXPORT_DROPDOWN_REPLACE = """    if typ in ('inline_dropdown', 'multi_blank_dropdown'):
        selected = dict(learner.get('_dropdown_selected') or {})
        # Phase 5: verified Phase 4 slots fill blanks the canonical flow
        # could not read; canonical reads are never overridden.
        p4 = PHASE5.dropdown_key_from_phase4(
            item, visual, (item or {}).get('_phase4'))
        if p4:
            for bid, text in (p4['key'] or {}).items():
                if not (str(selected.get(bid) or '')).strip():
                    selected[bid] = text
            item['_phase4_applied'] = {
                'source': 'phase4_pixel_agreed:'
                          + '+'.join(sorted(p4['methods'])),
                'key': dict(p4['key'])}"""

EXPORT_RECORD_ANCHOR = """        rec['answer_key_status'] = answer.get('status')
"""
EXPORT_RECORD_REPLACE = """        rec['answer_key_status'] = answer.get('status')
        if (item or {}).get('_phase4_applied'):
            rec['answer_key_source'] = item['_phase4_applied']['source']
"""

FIDELITY_ANCHOR = """        return {
            'ok': False,
            'source': 'pixel_mismatch',
            'reason': 'two pixel methods agreed but the exported key does not match them',
        }
    if raw and typ in ('single_choice', 'true_false', 'image_based_choice', 'multiple_select'):
        return {'ok': False, 'source': 'text_unmapped', 'reason': 'answer letters do not map to existing choice ids'}"""
FIDELITY_REPLACE = """        return {
            'ok': False,
            'source': 'pixel_mismatch',
            'reason': 'two pixel methods agreed but the exported key does not match them',
        }
    p4 = item.get('_phase4_applied') if isinstance(item, dict) else None
    if p4 and p4.get('source', '').startswith('phase4_pixel_agreed'):
        # Same canonical rule, satisfied by the two or more agreeing
        # independent mark methods recorded in the Phase 4 evidence for
        # this item's verified structure; the exported key must match.
        if _keys_equivalent(key, p4.get('key'), typ):
            return {'ok': True, 'source': p4['source'], 'reason': None}
        return {
            'ok': False,
            'source': 'phase4_mismatch',
            'reason': 'the Phase 4 verified key does not match the exported key',
        }
    if raw and typ in ('single_choice', 'true_false', 'image_based_choice', 'multiple_select'):
        return {'ok': False, 'source': 'text_unmapped', 'reason': 'answer letters do not map to existing choice ids'}"""


def replace_exact(s, old, new, name):
    if new in s:
        return s
    if s.count(old) != 1:
        raise ValueError("Pinned canonical upstream mismatch: " + name)
    return s.replace(old, new, 1)


def patch(upstream: Path, helper_root: Path):
    export = upstream / "scripts" / "build_technical_export.py"
    fidelity = upstream / "scripts" / "fidelity.py"
    helpers = [helper_root / name for name in (
        "phase5_export_evidence.py",
        "phase4_answer_key_evidence.py",
        "phase3_interaction_reconstruction.py",
    )]
    for p in (export, fidelity) + tuple(helpers):
        if not p.is_file():
            raise FileNotFoundError(p)

    e = export.read_text(encoding="utf-8")
    e = replace_exact(e, EXPORT_IMPORT_ANCHOR, EXPORT_IMPORT_REPLACE,
                      "export import")
    e = replace_exact(e, EXPORT_HEAD_ANCHOR, EXPORT_HEAD_REPLACE,
                      "export_one head")
    e = replace_exact(e, EXPORT_HOLD_ANCHOR, EXPORT_HOLD_REPLACE,
                      "export hold record")
    e = replace_exact(e, EXPORT_MATRIX_ANCHOR, EXPORT_MATRIX_REPLACE,
                      "matrix answer key")
    e = replace_exact(e, EXPORT_DROPDOWN_ANCHOR, EXPORT_DROPDOWN_REPLACE,
                      "dropdown answer key")
    e = replace_exact(e, EXPORT_RECORD_ANCHOR, EXPORT_RECORD_REPLACE,
                      "technical record source")
    export.write_text(e, encoding="utf-8")

    f = fidelity.read_text(encoding="utf-8")
    f = replace_exact(f, FIDELITY_ANCHOR, FIDELITY_REPLACE,
                      "key_certainty phase4 branch")
    fidelity.write_text(f, encoding="utf-8")

    for helper in helpers:
        shutil.copyfile(helper, upstream / "scripts" / helper.name)
    return export, fidelity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--helper-root", required=True)
    args = parser.parse_args()
    print(patch(Path(args.upstream), Path(args.helper_root)))


if __name__ == "__main__":
    main()
