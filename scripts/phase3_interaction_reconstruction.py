#!/usr/bin/env python3
"""Phase 3: reconstruct native interaction structure from source evidence.

Structure only, never answers. When the canonical marker-box flow in the
pinned upstream cannot read an answer-area layout (no marker box aligned
with the drop-down text, or Yes/No headers not found by OCR), the Phase 2
strict source regions already carry the layout: matrix statement bands,
enclosed UI controls with their option bands, and unboxed option stacks.

This module turns that region evidence into the exact visual-draft fields
the canonical converter already consumes (rows for matrices; blanks with
choices plus text_lines for drop-downs). It never fills answer keys or
selected options (Phase 4), never invents text, and never changes the
90/95 word/overall confidence floors or two-pass agreement rules.

Every reconstructed element records the region it came from. Elements
whose region did not pass the unchanged gates are kept only when the
layout needs them and are reported as evidenced deficiencies so Phase 6
verification can hold them. Items whose structure cannot be established
from the regions stay held with an exact blocker.

Text handling is limited to two documented normalizations: template
scaffolding labels (Answer Area, Statements, ...) named by the canonical
converter's own SKIP_OCR_LINES list are excluded, and a single leading
UI-chrome glyph (radio circle, checkbox, border) is stripped from row and
option text. Both the raw and normalized text are recorded.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Kept in sync with the canonical converter's SKIP_OCR_LINES so template
# scaffolding never becomes learner-facing interaction content.
TEMPLATE_LABEL_RE = re.compile(
    r'^(answer area|statements?|statement|correct answer:?|section:.*'
    r'|explanation.*|hotspot|drag drop)$',
    re.I,
)
YES_NO_INSTRUCTION_RE = re.compile(
    r'select yes if the statement is true|select yes if true', re.I)
DROPDOWN_INSTRUCTION_RE = re.compile(
    r'completes the sentence|drop-?down|answer area', re.I)

# A single leading glyph from UI chrome (radio circle OCR'd as O/0,
# checkbox, list border, disclosure marker) is not statement or option
# content.
UI_CHROME_PREFIX_RE = re.compile(r'^(?:[O0][\s\)\]]+|[\W_]{1,3}\s+)')
UI_CHROME_SUFFIX_RE = re.compile(r'\s+[\W_]{1,3}$')

CONTROL_KINDS = {'enclosed_text_control', 'light_ui_text_control'}

# Vertical-gap thresholds as a fraction of the row height.
STACK_GAP_FACTOR = 1.2      # options in one expanded list sit close
STATEMENT_GAP_FACTOR = 0.25  # lines of one statement nearly touch
AMBIGUOUS_GAP_FACTOR = 0.5   # below this a statement boundary is uncertain


def _text(candidate):
    return str(candidate.get('ocr_text_candidate') or '').strip()


def _strict(candidate):
    return bool(candidate.get('usable_as_verified_source'))


def _bbox(candidate):
    box = candidate.get('bbox_pixels') or [0, 0, 0, 0]
    return [float(v) for v in box]


def _dims(candidate):
    dims = candidate.get('source_dimensions') or [1, 1]
    return [float(dims[0]) or 1.0, float(dims[1]) or 1.0]


def _norm_bbox(candidate):
    x0, y0, x1, y1 = _bbox(candidate)
    w, h = _dims(candidate)
    return [x0 / w, y0 / h, x1 / w, y1 / h]


def _is_template_label(text):
    t = (text or '').strip()
    if TEMPLATE_LABEL_RE.match(t):
        return True
    # Column headers like "Statements" or "Statements Yes No" are matrix
    # scaffolding; a real statement that begins with the word "Statement"
    # is not ("Statements are reviewed yearly" stays content).
    return bool(re.match(r'^statements?(\s+(yes|no))*$', t, re.I))


def _strip_chrome(text):
    t = (text or '').strip()
    t = UI_CHROME_PREFIX_RE.sub('', t, count=1)
    t = UI_CHROME_SUFFIX_RE.sub('', t, count=1)
    return t.strip()


def _band_kind(kind):
    return 'text_band' in str(kind or '')


def _is_control(kind):
    return str(kind or '') in CONTROL_KINDS


def _is_matrix_band(kind):
    return 'matrix_statement_column' in str(kind or '') and _band_kind(kind)


def _is_control_band(kind):
    k = str(kind or '')
    return ('enclosed_text_control' in k or 'light_ui_text_control' in k) \
        and _band_kind(k)


def _is_unboxed_band(kind):
    return 'unboxed_source_text' in str(kind or '') and _band_kind(kind)


def _min_conf(candidate):
    values = []
    for p in candidate.get('passes') or []:
        v = p.get('min_confidence')
        if v is not None:
            values.append(float(v))
    return round(min(values)) if values else 0


def _vertical_overlap(a, b):
    return max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _vertical_gap(a, b):
    return max(0.0, max(a[1], b[1]) - min(a[3], b[3]))


def _horizontal_overlap(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0]))


def _same_row(a, b):
    shorter = min(a[3] - a[1], b[3] - b[1]) or 1.0
    return _vertical_overlap(a, b) > 0.5 * shorter \
        and _horizontal_overlap(a, b) > 0


def _row_key(candidate):
    """Reading order: top-to-bottom, left-to-right."""
    box = _bbox(candidate)
    return (box[1], box[0])


def _rank(candidate):
    """Deterministic reading preference: gate-certified first, then
    agreeing passes, then the longer reading (a trailing period is real
    source content that a tight crop can lose)."""
    return (
        1 if _strict(candidate) else 0,
        1 if candidate.get('two_pass_agreement') else 0,
        len(_text(candidate)),
    )


def _merge_rows(candidates):
    """Collapse band and localized crops of the same visual row into one
    record: the best reading as text, the tight (localized) box as
    geometry, and the strongest gate result as strictness."""
    groups = []
    for cand in sorted(candidates, key=_row_key):
        for group in groups:
            if _same_row(_bbox(cand), _bbox(group['geometry'])):
                group['members'].append(cand)
                break
        else:
            groups.append({'geometry': cand, 'members': [cand]})
    merged = []
    for group in groups:
        best = max(group['members'], key=_rank)
        localized = [c for c in group['members']
                     if str(c.get('kind') or '').endswith('_localized')]
        geometry = localized[0] if localized else group['geometry']
        merged.append({
            'text': _text(best),
            'raw_text': _text(best),
            'bbox': _bbox(geometry),
            'norm_bbox': _norm_bbox(geometry),
            'dims': _dims(geometry),
            'strict': _strict(best),
            'agreed': bool(best.get('two_pass_agreement')),
            'minconf': _min_conf(best),
            'evidence': _evidence(best),
        })
    return merged


def _evidence(cand):
    return {
        'kind': cand.get('kind'),
        'bbox_pixels': cand.get('bbox_pixels'),
        'source_file': cand.get('source_file'),
        'crop_sha256': cand.get('crop_sha256'),
        'two_pass_agreement': bool(cand.get('two_pass_agreement')),
        'usable_as_verified_source': _strict(cand),
    }


def question_regions(item):
    """The item's question-image region candidates (learner-facing source;
    answer-image regions are Phase 4 key evidence, never structure)."""
    return list(item.get('source_region_candidates') or [])


def _group_statements(rows):
    """Merge vertically-overlapping or nearly-touching rows into one
    statement; a clear gap starts a new statement. Returns statements and
    whether any boundary was too tight to be certain."""
    if not rows:
        return [], False
    heights = sorted(r['bbox'][3] - r['bbox'][1] for r in rows)
    median_h = heights[len(heights) // 2] or 1.0
    statements = []
    uncertain = False
    for row in rows:
        if statements:
            prev = statements[-1]
            gap = _vertical_gap(prev['bbox'], row['bbox'])
            overlap = _vertical_overlap(prev['bbox'], row['bbox'])
            if overlap > 0 or gap <= STATEMENT_GAP_FACTOR * median_h:
                # same statement, next line
                prev['text'] = (prev['text'] + ' ' + _strip_chrome(
                    row['text'])).strip()
                prev['raw_lines'].append(row['text'])
                prev['strict'] = prev['strict'] and row['strict']
                prev['bbox'] = [
                    min(prev['bbox'][0], row['bbox'][0]),
                    min(prev['bbox'][1], row['bbox'][1]),
                    max(prev['bbox'][2], row['bbox'][2]),
                    max(prev['bbox'][3], row['bbox'][3]),
                ]
                if gap > 0 and gap < AMBIGUOUS_GAP_FACTOR * median_h:
                    uncertain = True
                continue
            if gap < AMBIGUOUS_GAP_FACTOR * median_h:
                uncertain = True
        statements.append({
            'text': _strip_chrome(row['text']),
            'raw_lines': [row['text']],
            'bbox': list(row['bbox']),
            'strict': row['strict'],
            'minconf': row['minconf'],
            'evidence': row['evidence'],
        })
    for i, statement in enumerate(statements, 1):
        statement['id'] = 'r%d' % i
    return statements, uncertain


def reconstruct_matrix_rows(item):
    """Matrix rows from matrix statement bands; when the source has no
    detected matrix panel, unboxed statement bands are used with explicit
    line-grouping. Template labels are scaffolding, not statements."""
    regions = question_regions(item)
    matrix_bands = [c for c in regions
                    if _is_matrix_band(c) and _text(c)
                    and not _is_template_label(_text(c))]
    structure = 'matrix_bands'
    rows = _merge_rows(matrix_bands)
    if not rows:
        structure = 'unboxed_statement_bands'
        unboxed = [c for c in regions
                   if _is_unboxed_band(c) and _text(c)
                   and not _is_template_label(_text(c))]
        rows = _merge_rows(unboxed)
    rows = [r for r in rows if _strip_chrome(r['text'])]
    statements, uncertain = _group_statements(rows)
    for statement in statements:
        statement['structure'] = structure
    return statements, uncertain


def _center(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _inside(candidate_box, control_box):
    cx, cy = _center(candidate_box)
    return control_box[0] <= cx <= control_box[2] \
        and control_box[1] <= cy <= control_box[3]


def _column_aligned(a, b):
    """Left edges close relative to the source image width (options of one
    list align) and the boxes overlap horizontally."""
    w = max(a['dims'][0], b['dims'][0]) or 1000.0
    dx = abs(a['bbox'][0] - b['bbox'][0])
    return dx <= max(20.0, 0.04 * w) and _horizontal_overlap(a['bbox'],
                                                             b['bbox']) > 0


def _stack_runs(merged_rows, gap_factor=STACK_GAP_FACTOR):
    """Group merged rows into vertical runs: aligned left edges, adjacent
    rows. Each run of two or more rows is one expanded option list."""
    runs = []
    for row in merged_rows:
        placed = False
        for run in runs:
            for other in run:
                height = min(row['bbox'][3] - row['bbox'][1],
                             other['bbox'][3] - other['bbox'][1]) or 1.0
                gap = _vertical_gap(row['bbox'], other['bbox'])
                if gap <= gap_factor * height and _column_aligned(row, other):
                    run.append(row)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            runs.append([row])
    return [run for run in runs if len(run) >= 2]


def _blank_from_choices(rows, blank_index, structure):
    choices = []
    for row in rows:
        choices.append({
            'text': _strip_chrome(row['text']),
            'raw_text': row['raw_text'],
            'strict': row['strict'],
            'evidence': row['evidence'],
        })
    return {
        'id': 'blank%d' % blank_index,
        'structure': structure,
        'choices': choices,
        'minconf': min([r['minconf'] for r in rows] or [0]),
        'bbox_pixels': [
            min(r['bbox'][0] for r in rows),
            min(r['bbox'][1] for r in rows),
            max(r['bbox'][2] for r in rows),
            max(r['bbox'][3] for r in rows),
        ],
        'norm_bbox': [
            min(r['norm_bbox'][0] for r in rows),
            min(r['norm_bbox'][1] for r in rows),
            max(r['norm_bbox'][2] for r in rows),
            max(r['norm_bbox'][3] for r in rows),
        ],
    }


def reconstruct_dropdown(item, ocr_lines=None):
    """Blanks and sentence text from enclosed controls with option bands,
    stacked control rows, or unboxed option stacks. One blank per detected
    drop-down list; the sentence keeps every other line."""
    regions = question_regions(item)
    controls = _merge_rows([c for c in regions if _is_control(c.get('kind'))])
    control_bands = _merge_rows(
        [c for c in regions if _is_control_band(c.get('kind'))])
    unboxed = [c for c in regions if _is_unboxed_band(c.get('kind'))
               and _text(c) and not _is_template_label(_text(c))]

    blanks = []
    used_rows = []
    unreadable_controls = []

    # Case A: an enclosed control whose option bands sit inside its box.
    blank_control_rows = []
    for control in controls:
        inside_all = [b for b in control_bands
                      if _inside(b['bbox'], control['bbox'])]
        inside = [b for b in inside_all if b['text']]
        if len(inside_all) >= 2 and len(inside) < len(inside_all):
            unreadable_controls.append(control)
        if len(inside) >= 2:
            blank_control_rows.append(control)
            used_rows.extend(inside)
    for control in blank_control_rows:
        inside = [b for b in control_bands
                  if _inside(b['bbox'], control['bbox']) and b['text']]
        blanks.append(_blank_from_choices(inside, len(blanks) + 1, 'control'))

    # Case B: stacked control rows with no separate option bands are the
    # option list themselves (each control row is one expanded option).
    leftover_controls = [c for c in controls
                         if all(not _same_row(c['bbox'], u['bbox'])
                                for u in blank_control_rows)]
    for run in _stack_runs(leftover_controls):
        blanks.append(_blank_from_choices(
            run, len(blanks) + 1, 'stacked_controls'))
        used_rows.extend(run)

    # Case C: unboxed option stacks (no control chrome at all).
    free = [b for b in _merge_rows(unboxed)
            if all(not _same_row(b['bbox'], u['bbox']) for u in used_rows)]
    for run in _stack_runs(free):
        blanks.append(_blank_from_choices(
            run, len(blanks) + 1, 'option_stack'))
        used_rows.extend(run)

    blanks.sort(key=lambda b: (b['bbox_pixels'][1], b['bbox_pixels'][0]))
    for i, blank in enumerate(blanks, 1):
        blank['id'] = 'blank%d' % i

    # Sentence text: OCR lines outside every blank box, minus scaffolding.
    text_lines = []
    for line in (ocr_lines or []):
        text = str(line.get('text') or line.get('t') or '').strip()
        if not text or _is_template_label(text):
            continue
        x = line.get('x')
        y = line.get('y')
        in_blank = False
        if x is not None and y is not None:
            for blank in blanks:
                bx = blank['norm_bbox']
                if bx[0] - 0.02 <= float(x) <= bx[2] + 0.02 \
                        and bx[1] - 0.02 <= float(y) <= bx[3] + 0.02:
                    in_blank = True
                    break
        else:
            in_blank = any(_text_in_blank(text, blank) for blank in blanks)
        if not in_blank:
            text_lines.append({'t': text,
                               'x': round(float(x or 0), 3),
                               'y': round(float(y or 0), 3)})
    return blanks, text_lines, unreadable_controls


def _text_in_blank(text, blank):
    return any(ch['text'].strip().lower() == text.strip().lower()
               for ch in blank['choices'])


def kind_from_stem(stem, ocr_lines=None):
    """Mirror of the patched canonical classifier's kind rules; the kind
    decision stays with the converter, this is only the fallback order."""
    s = (stem or '').lower()
    source = ' '.join(str((l or {}).get('text') or (l or {}).get('t') or '')
                      .strip().lower() for l in (ocr_lines or []))
    if YES_NO_INSTRUCTION_RE.search(s) or YES_NO_INSTRUCTION_RE.search(source):
        return 'yes_no'
    if DROPDOWN_INSTRUCTION_RE.search(s) or DROPDOWN_INSTRUCTION_RE.search(source):
        return 'dropdown'
    return 'unknown'


def _effective_kind(item, visual_rec):
    """Kind for reconstruction: the canonical classifier's decision when it
    committed to one, otherwise the layout evidence itself. The strict
    classifier (stems alone never prove a drop-down) stays untouched; an
    'unknown' kind is only overridden by actual UI structure in the source
    regions, which is exactly what Phase 3 reconstructs from."""
    kind = visual_rec.get('kind')
    if kind in ('yes_no', 'dropdown'):
        return kind, None
    stem = item.get('stem') or ''
    regions = question_regions(item)
    if regions and YES_NO_INSTRUCTION_RE.search(stem) and any(
            _is_matrix_band(c.get('kind')) for c in regions):
        return 'yes_no', 'phase3_region_structure'
    if regions:
        blanks, _, _ = reconstruct_dropdown(item)
        if blanks:
            return 'dropdown', 'phase3_region_structure'
    return 'unknown', None


def reconstruct_item(item, visual_rec=None):
    """Full Phase 3 reconstruction record for one item."""
    visual_rec = visual_rec or {}
    key = item.get('question_key')
    ocr_lines = visual_rec.get('ocr') or []
    kind, kind_evidence = _effective_kind(item, visual_rec)
    rec = {
        'question_key': key,
        'kind': kind,
        'suggested_type': None,
        'structure_source': 'phase3_strict_source_regions',
        'filled': False,
        'blockers': [],
    }
    if kind_evidence:
        rec['kind_evidence'] = kind_evidence
        rec['classifier_kind'] = visual_rec.get('kind')
    if kind == 'yes_no':
        rows, uncertain = reconstruct_matrix_rows(item)
        rec['rows'] = rows
        if not rows:
            rec['blockers'].append(
                'yes/no matrix: no matrix statement or unboxed statement '
                'source region was read for this item, so the native rows '
                'cannot be reconstructed without guessing')
        else:
            rec['suggested_type'] = 'yes_no_matrix'
            rec['filled'] = True
            if uncertain:
                rec['grouping_uncertain'] = True
                rec['blockers'].append(
                    'yes/no matrix: at least one statement boundary gap is '
                    'below half the row height, so line-to-statement '
                    'grouping needs reviewer confirmation')
                rec['filled'] = False
            deficient = [r for r in rows if not r['strict']]
            if deficient:
                rec['evidenced_deficiencies'] = [
                    {'row': r['id'], 'text': r['text'],
                     'reason': 'row text not from a strict two-pass region '
                               '(Phase 2 coverage records any line-crop '
                               'verification)'}
                    for r in deficient]
    elif kind == 'dropdown':
        blanks, text_lines, unreadable = reconstruct_dropdown(item, ocr_lines)
        rec['blanks'] = blanks
        rec['text_lines'] = text_lines
        if unreadable:
            rec['blockers'].append(
                'drop-down: %d answer-area control(s) contain option bands '
                'that no OCR pass could read, so the complete option list '
                'cannot be reconstructed without guessing'
                % len(unreadable))
        if not blanks:
            rec['blockers'].append(
                'drop-down: no enclosed control with option bands, stacked '
                'control run, or aligned option stack was read from the '
                'question source regions, so the native blank structure '
                'cannot be reconstructed without guessing')
        else:
            rec['suggested_type'] = ('multi_blank_dropdown'
                                     if len(blanks) >= 2 else 'inline_dropdown')
            rec['filled'] = True
            deficiencies = []
            for blank in blanks:
                if len(blank['choices']) < 2:
                    rec['blockers'].append(
                        'drop-down %s: fewer than two options were read '
                        'from the source regions' % blank['id'])
                    rec['filled'] = False
                for ch in blank['choices']:
                    if not ch['strict']:
                        deficiencies.append(
                            {'blank': blank['id'], 'choice': ch['text'],
                             'reason': 'choice text not from a strict '
                                       'two-pass region (Phase 2 coverage '
                                       'records any line-crop verification)'})
            if deficiencies:
                rec['evidenced_deficiencies'] = deficiencies
        if rec['blockers']:
            rec['filled'] = False
    else:
        rec['blockers'].append(
            'interaction kind is not evidenced by the stem instruction or '
            'source OCR text; the layout cannot be mapped to a native type '
            'without guessing')
    return rec


def fill_item_structure(d, item, ocr_lines=None):
    """Patch target inside the canonical analyzer: fill only what the
    canonical marker-box flow left empty. Never touches keys/selected."""
    if item.get('options') or not item.get('question_images'):
        return d
    kind, kind_evidence = _effective_kind(item, d)
    if kind not in ('yes_no', 'dropdown'):
        return d
    rec = reconstruct_item(item, d)
    rec_kind = rec.get('kind')
    d['phase3_reconstruction'] = {
        'question_key': rec['question_key'],
        'structure_source': rec['structure_source'],
        'suggested_type': rec['suggested_type'],
        'filled': rec['filled'],
        'blockers': rec['blockers'],
    }
    if rec.get('evidenced_deficiencies'):
        d['phase3_reconstruction']['evidenced_deficiencies'] = \
            rec['evidenced_deficiencies']
    if rec.get('grouping_uncertain'):
        d['phase3_reconstruction']['grouping_uncertain'] = True
    if kind_evidence:
        d['phase3_reconstruction']['kind_evidence'] = kind_evidence
        d['phase3_reconstruction']['classifier_kind'] = d.get('kind')
        d['notes'].append(
            'phase3: kind %s established from source-region layout '
            'evidence (classifier said unknown)' % rec_kind)
    if rec_kind == 'yes_no' and not (d.get('rows') or []):
        rows = [r for r in (rec.get('rows') or []) if r.get('text')]
        if rows and not rec.get('grouping_uncertain'):
            d['rows'] = [{'id': r['id'], 'text': r['text'],
                          'minconf': r['minconf']} for r in rows]
            d['notes'].append(
                'phase3: rows reconstructed from strict source regions; '
                'answer key not set (Phase 4)')
            d['phase3_reconstruction']['filled_structure'] = True
    if rec_kind == 'dropdown' and not (d.get('blanks') or []):
        blanks = rec.get('blanks') or []
        if blanks and all(len(b['choices']) >= 2 for b in blanks) \
                and rec['filled']:
            d['blanks'] = [{'id': b['id'],
                            'choices': [ch['text'] for ch in b['choices']],
                            'selected': None,
                            'minconf': b.get('minconf', 0)}
                           for b in blanks]
            d['text_lines'] = rec.get('text_lines') or []
            d.pop('key', None)
            d['notes'].append(
                'phase3: blanks reconstructed from strict source regions; '
                'selected options and key not set (Phase 4)')
            d['phase3_reconstruction']['filled_structure'] = True
    if (d.get('rows') or []) or (d.get('blanks') or []):
        if not d['phase3_reconstruction'].get('filled_structure'):
            d['phase3_reconstruction']['corroborated_canonical'] = True
    return d


def build_report(split, visual_draft, coverage=None):
    """Phase 3 evidence report across all items. Coverage is optional; when
    a Phase 2 source-coverage record is given, per-question token
    verification is attached without changing any verdict.

    An item counts as structured when the canonical marker-box flow already
    read its layout, or when this reconstruction could rebuild it from the
    strict source regions. Region evidence is attached as corroboration for
    canonically structured items, with explicit discrepancies; it never
    overrides the canonical structure."""
    coverage = coverage or {}
    per_question = {}
    for q in coverage.get('questions') or []:
        per_question[q.get('question_key')] = q
    items = []
    for key in sorted(split,
                      key=lambda k: (split[k].get('source_number') or 0, k)):
        item = split[key]
        visual = (visual_draft or {}).get(key) or {}
        if item.get('options'):
            rec = {
                'question_key': key,
                'kind': 'selection',
                'structure_source': 'text_layer_options',
                'suggested_type': None,
                'filled': True,
                'blockers': [],
            }
        elif (visual.get('phase3_reconstruction') or {}).get(
                'filled_structure'):
            marker = visual['phase3_reconstruction']
            rec = {
                'question_key': key,
                'kind': visual.get('kind'),
                'structure_source': 'phase3_strict_source_regions',
                'suggested_type': marker.get('suggested_type'),
                'filled': bool(marker.get('filled')),
                'blockers': marker.get('blockers') or [],
                'rows': [{'text': r.get('text'), 'strict': None}
                         for r in (visual.get('rows') or [])],
                'blanks': [{'id': b.get('id'),
                            'choices': [c if isinstance(c, str)
                                        else c.get('text')
                                        for c in (b.get('choices') or [])]}
                           for b in (visual.get('blanks') or [])],
            }
            if marker.get('kind_evidence'):
                rec['kind_evidence'] = marker['kind_evidence']
                rec['classifier_kind'] = visual.get('kind')
            if marker.get('evidenced_deficiencies'):
                rec['evidenced_deficiencies'] = \
                    marker['evidenced_deficiencies']
            if marker.get('grouping_uncertain'):
                rec['grouping_uncertain'] = True
        elif (visual.get('rows') or []) or (visual.get('blanks') or []):
            canonical_rows = visual.get('rows') or []
            canonical_blanks = visual.get('blanks') or []
            rec = {
                'question_key': key,
                'kind': visual.get('kind'),
                'structure_source': 'canonical_marker_box_flow',
                'suggested_type': ('yes_no_matrix' if canonical_rows
                                   else ('multi_blank_dropdown'
                                         if len(canonical_blanks) >= 2
                                         else 'inline_dropdown')),
                'filled': True,
                'blockers': [],
                'canonical_rows': len(canonical_rows),
                'canonical_blanks': [
                    {'id': b.get('id'),
                     'choices': len(b.get('choices') or []),
                     'selected': b.get('selected')}
                    for b in canonical_blanks],
            }
            region_rec = reconstruct_item(item, visual)
            if region_rec.get('rows') is not None:
                rec['region_corroboration'] = {
                    'rows': [{'text': r['text'], 'strict': r['strict']}
                             for r in region_rec['rows']],
                    'grouping_uncertain': region_rec.get(
                        'grouping_uncertain', False),
                }
                if len(region_rec['rows']) != len(canonical_rows):
                    rec['discrepancies'] = [
                        'canonical flow read %d matrix rows, region evidence '
                        'groups %d' % (len(canonical_rows),
                                       len(region_rec['rows']))]
            if region_rec.get('blanks') is not None:
                region_blanks = [
                    {'id': b['id'], 'choices': len(b['choices'])}
                    for b in region_rec['blanks']]
                rec['region_corroboration'] = {
                    'blanks': region_blanks,
                }
                canonical_shape = [
                    (b.get('id'), len(b.get('choices') or []))
                    for b in canonical_blanks]
                if [(b['id'], b['choices']) for b in region_blanks] \
                        != canonical_shape:
                    rec['discrepancies'] = [
                        'canonical flow read %s, region evidence reads %s'
                        % (canonical_shape,
                           [(b['id'], b['choices'])
                            for b in region_blanks])]
        else:
            rec = reconstruct_item(item, visual)
        cov = per_question.get(key)
        if cov:
            rec['source_coverage'] = {
                'reference_tokens': cov.get('reference_content_token_count'),
                'verified_tokens': cov.get('verified_token_count'),
                'evidenced_deficient_tokens': cov.get('uncovered_token_count'),
            }
        items.append(rec)
    return {
        'status': 'PHASE3_INTERACTION_STRUCTURE_EVIDENCE_NOT_RELEASE',
        'structure_only': True,
        'answer_keys_extracted': False,
        'fidelity_certified': False,
        'release_approved': False,
        'summary': {
            'questions': len(items),
            'structure_reconstructed': sum(1 for r in items if r['filled']
                                           and not r['blockers']),
            'held_with_blockers': sum(1 for r in items if r['blockers']),
            'with_evidenced_deficiencies': sum(
                1 for r in items if r.get('evidenced_deficiencies')),
            'with_region_discrepancies': sum(
                1 for r in items if r.get('discrepancies')),
        },
        'questions': items,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    report = sub.add_parser(
        'report', help='Build the Phase 3 reconstruction evidence report.')
    report.add_argument('--split', required=True)
    report.add_argument('--visual-draft', required=True)
    report.add_argument('--coverage', help='Phase 2 source coverage JSON.')
    report.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    if args.cmd != 'report':
        parser.error('unknown command')
    split = json.loads(Path(args.split).read_text(encoding='utf-8'))
    visual = json.loads(Path(args.visual_draft).read_text(encoding='utf-8'))
    coverage = None
    if args.coverage:
        coverage = json.loads(Path(args.coverage).read_text(encoding='utf-8'))
    doc = build_report(split, visual, coverage)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + '\n',
                   encoding='utf-8')
    print('phase3 report: %d questions, %d reconstructed, %d held (%s)' % (
        len(doc['questions']),
        doc['summary']['structure_reconstructed'],
        doc['summary']['held_with_blockers'],
        out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
