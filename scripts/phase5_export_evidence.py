#!/usr/bin/env python3
"""Phase 5: feed repaired extraction and verified answer evidence into the
canonical converter. Fail-closed; nothing is guessed or weakened.

Two integrations, both reading evidence that earlier phases produced:

- ``verified_ocr_item``: the fidelity OCR record for an item is rebuilt from
  its Phase 2 strict source regions (two-pass agreed, every word at or above
  the unchanged 90/95 floors). Question images without strict regions keep
  their raw record and fail the gate exactly as before. Answer-role images
  are excluded from the learner OCR gate because they are server-only key
  evidence governed by the Phase 4 key gate, never learner-visible media.
  Thresholds are untouched: the same 90/95 floors and pass-agreement rule
  now apply to the verified word set instead of raw first-pass noise.

- Phase 4 answer keys: only records with ``verified_pixel_agreed`` status
  (two or more independent mark methods agreeing on the same complete key)
  are applied, and only when the structure the key was verified against is
  rebuilt here and matches the export structure row by row / blank by
  blank. Single-chain candidates and blocked items never receive keys.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase4_answer_key_evidence as P4  # noqa: E402

WORD_RE = re.compile(r'[a-z0-9]+')


def normalize(text):
    return ' '.join(WORD_RE.findall((text or '').lower()))


def load_phase4_evidence(path):
    """Load the Phase 4 evidence report as {question_key: record}."""
    if not path:
        return {}
    doc = json.loads(Path(path).read_text(encoding='utf-8'))
    return {q.get('question_key'): q for q in doc.get('questions') or []}


def verified_ocr_item(item, ocr_item):
    """Rebuild the fidelity OCR record from strict source regions.

    Returns (record, meta). Fail-closed: an image without strict regions
    keeps its raw record, so the unchanged gate still fails it; an item
    whose images are all answer-role keeps its raw record too.
    """
    images = (ocr_item or {}).get('images') or []
    if not images:
        return ocr_item, {'mode': 'no_images'}
    strict_by_file = {}
    for cand in item.get('source_region_candidates') or []:
        if not cand.get('usable_as_verified_source'):
            continue
        if not cand.get('verified_words'):
            continue
        strict_by_file.setdefault(cand.get('source_file'),
                                  []).append(cand)
    meta = {'verified_files': [], 'raw_files': [],
            'excluded_answer_files': []}
    out_images = []
    for im in images:
        fname = im.get('file')
        if (im.get('role') or 'question') == 'answer':
            # Server-only key evidence: gated by the Phase 4 key gate,
            # not by the learner OCR quality gate.
            meta['excluded_answer_files'].append(fname)
            continue
        regions = strict_by_file.get(fname) or []
        if not regions:
            meta['raw_files'].append(fname)
            out_images.append(im)
            continue
        regions = sorted(
            regions,
            key=lambda r: ((r.get('bbox_pixels') or [0, 0, 0, 0])[1],
                           (r.get('bbox_pixels') or [0, 0, 0, 0])[0]))
        words = []
        means, mins = [], []
        passes = {}
        for reg in regions:
            words.extend(dict(w) for w in reg.get('verified_words') or [])
            cand_text = reg.get('ocr_text_candidate') or ''
            for p in reg.get('passes') or []:
                pid = str(p.get('id'))
                passes[pid] = {'text': cand_text}
                if p.get('mean_confidence') is not None:
                    means.append(float(p['mean_confidence']))
                if p.get('min_confidence') is not None:
                    mins.append(float(p['min_confidence']))
        out_images.append({
            'file': fname,
            'role': im.get('role') or 'question',
            'words': words,
            'lines': [],
            'text': ' '.join((w.get('text') or '') for w in words),
            'mean_confidence': min(means) if means else None,
            'min_confidence': min(mins) if mins else None,
            'passes': passes,
            'agree': True,
        })
        meta['verified_files'].append(fname)
    if not out_images:
        # Every image was answer-role: keep the raw record so the gate
        # still sees the item's images (never bypass it).
        return ocr_item, meta
    new_item = dict(ocr_item or {})
    new_item['images'] = out_images
    if meta['raw_files']:
        new_item['agree'] = (ocr_item or {}).get('agree')
        new_item['confidence'] = (ocr_item or {}).get('confidence')
        new_item['min_confidence'] = (ocr_item or {}).get('min_confidence')
    else:
        new_item['agree'] = True
        confs = [im.get('mean_confidence') for im in out_images
                 if im.get('mean_confidence') is not None]
        lows = [im.get('min_confidence') for im in out_images
                if im.get('min_confidence') is not None]
        new_item['confidence'] = min(confs) if confs else None
        new_item['min_confidence'] = min(lows) if lows else None
    return new_item, meta


def _structure_matches_visual(structure, visual):
    """The Phase 4 structure must correspond to the export structure:
    same ids in the same order, and each row/choice text within the same
    correspondence floor (fuzzy tokens, one OCR misread tolerated) the
    Phase 4 verifier itself used for statement correspondence."""
    if not structure:
        return False
    if structure.get('kind') == 'yes_no_matrix':
        vrows = [r for r in (visual or {}).get('rows') or []]
        srows = structure.get('rows') or []
        if len(srows) != len(vrows):
            return False
        for s, v in zip(srows, vrows):
            if s.get('id') != v.get('id'):
                return False
            if P4.match_token_ratio(s.get('text'), v.get('text')) < 0.6:
                return False
        return True
    if structure.get('kind') in ('inline_dropdown', 'multi_blank_dropdown'):
        vblanks = (visual or {}).get('blanks') or []
        sblanks = structure.get('blanks') or []
        if len(sblanks) != len(vblanks):
            return False
        for s, v in zip(sblanks, vblanks):
            if s.get('id') != v.get('id'):
                return False
            s_choices = [normalize(c['text'] if isinstance(c, dict) else c)
                         for c in (s.get('choices') or [])]
            v_choices = [normalize(c['text'] if isinstance(c, dict) else c)
                         for c in (v.get('choices') or [])]
            if s_choices != v_choices:
                return False
        return True
    return False


def _verified_record(item, record):
    if not record or not isinstance(item, dict):
        return None
    if record.get('status') != 'verified_pixel_agreed':
        return None
    methods = record.get('agreeing_methods') or []
    if len(methods) < 2:
        return None
    return methods


def matrix_key_from_phase4(item, visual, record):
    """Apply a Phase 4 verified matrix key onto this export's rows."""
    methods = _verified_record(item, record)
    if methods is None:
        return None
    if record.get('structure_kind') != 'yes_no_matrix':
        return None
    key_rows = ((record.get('answer_key') or {}).get('rows')) or {}
    structure = P4.structure_of(item, visual)
    if not _structure_matches_visual(structure, visual):
        return None
    vrows = (visual or {}).get('rows') or []
    if set(key_rows) != {r['id'] for r in vrows}:
        return None
    return {'key': dict(key_rows), 'methods': list(methods)}


def dropdown_key_from_phase4(item, visual, record):
    """Apply a Phase 4 verified drop-down key onto this export's blanks."""
    methods = _verified_record(item, record)
    if methods is None:
        return None
    if record.get('structure_kind') not in ('inline_dropdown',
                                            'multi_blank_dropdown'):
        return None
    slots = ((record.get('answer_key') or {}).get('slots')) or {}
    structure = P4.structure_of(item, visual)
    if not _structure_matches_visual(structure, visual):
        return None
    vblanks = (visual or {}).get('blanks') or []
    by_id = {}
    for b in vblanks:
        texts = [normalize(c['text'] if isinstance(c, dict) else c)
                 for c in (b.get('choices') or [])]
        by_id[b.get('id')] = texts
    if set(slots) != set(by_id):
        return None
    key = {}
    for bid, text in slots.items():
        norm = normalize(text)
        if norm not in by_id.get(bid) or []:
            return None
        key[bid] = text
    return {'key': key, 'methods': list(methods)}
