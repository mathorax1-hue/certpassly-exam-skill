#!/usr/bin/env python3
"""Phase 4: per-question answer-key evidence from owner marks and text keys.

Verification only, never publication. For every question this module
establishes one of:

- ``verified_text``          the source text layer names answer letters that
                             map to real options and the stem's choose-N
- ``verified_pixel_agreed``  two or more independent mark methods agree on
                             the same complete key mapped onto the item's
                             native structure
- ``candidate_single_chain`` exactly one mark method, but with its own
                             multi-threshold, multi-OCR-mode and
                             source-presence agreement intact (an owner-key
                             candidate, not a verified key)
- ``blocked_*``              an exact evidence blocker (contradictory marks,
                             single weak method, no marks, ambiguous or
                             unresolved structure, uncertain text
                             correspondence)

No key is guessed. Thresholds and the two-pass OCR gates of the canonical
converter are never changed; this module only reads evidence. Answer data
stays separate from learner structure (server-only answer records).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WORD_RE = re.compile(r'[a-z0-9]+')
CHOOSE_N_RE = re.compile(
    r'\b(?:choose|select|pick)\s+(?:the\s+)?(two|three|four|five|six|seven'
    r'|eight|nine|ten|\d+)\b|\bwhich\s+(two|three|four|five|six|seven'
    r'|eight|nine|ten)\b', re.I)
CHOOSE_N_WORDS = {'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
                  'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}

# Canonical rule, unchanged: a pixel key needs this many agreeing methods.
MIN_AGREEING_METHODS = 2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase3_interaction_reconstruction as P3  # noqa: E402


def normalize(text):
    return ' '.join(WORD_RE.findall((text or '').lower()))


def tokens(text):
    return set(WORD_RE.findall((text or '').lower()))


def _levenshtein(a, b):
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def token_matches(a, b):
    """Token equality tolerant of one OCR character misread on words of
    four or more characters; shorter words must match exactly."""
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and abs(len(a) - len(b)) <= 1:
        return _levenshtein(a, b) <= 1
    return False


def choose_n_from_text(text):
    m = CHOOSE_N_RE.search(text or '')
    if not m:
        return None
    raw = (m.group(1) or m.group(2) or '').lower()
    if raw.isdigit():
        n = int(raw)
        return n if n >= 1 else None
    return CHOOSE_N_WORDS.get(raw)


# ---------------------------------------------------------------- collectors

class Collectors:
    """Thin wrappers around the pinned upstream's own detectors plus this
    repository's four-edge selection-box recovery. Kept behind one object so
    tests can substitute synthetic readings."""

    def __init__(self, pipeline_scripts=None):
        self._pipeline_scripts = pipeline_scripts
        self._V = None
        self._sel = None

    @property
    def V(self):
        if self._V is None:
            if not self._pipeline_scripts:
                raise RuntimeError('pipeline scripts path required for '
                                   'image collectors')
            sys.path.insert(0, str(self._pipeline_scripts))
            import vision_util
            self._V = vision_util
        return self._V

    @property
    def sel(self):
        if self._sel is None:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import detect_owner_marked_dropdown
            self._sel = detect_owner_marked_dropdown
        return self._sel

    def mark_methods(self, answer_path, cfg=None):
        """The canonical three mark detectors, on one answer image."""
        V = self.V
        cfg = cfg or V.load_ocr_config()
        out = {
            'marker_box': list(V.marker_boxes(answer_path)[0]),
            'checked_box': list(V.checked_boxes(answer_path, cfg)),
            'highlight': list(V.highlight_marks(answer_path, cfg)),
        }
        for marks in out.values():
            for m in marks:
                for k in ('x', 'y', 'w', 'h'):
                    if k in m:
                        m[k] = float(m[k])
        return out

    def ocr_lines(self, image_path):
        return self.V.ocr_lines(image_path)[0]

    def selection_box(self, question_path, answer_path):
        """Four-edge owner selection box with its internal agreement chain."""
        return self.sel.recover(str(question_path), str(answer_path))


# ------------------------------------------------------------- row grouping

def group_lines(lines, gap=0.8):
    """Group OCR lines into visual rows, line-to-line (the canonical
    analyzer's rule, with a slightly wider documented factor for answer-area
    statement grouping where two-line statements sit close)."""
    rows = []
    for line in sorted(lines, key=lambda l: (l.get('y') or 0, l.get('x') or 0)):
        y = float(line.get('y') or 0)
        y1 = float(line.get('y1')) if line.get('y1') is not None else y + 0.03
        lh = max(0.02, y1 - y)
        if rows and y - rows[-1]['last_y1'] < gap * lh:
            rows[-1]['lines'].append(line)
            rows[-1]['y1'] = max(rows[-1]['y1'], y1)
            rows[-1]['last_y1'] = y1
        else:
            rows.append({'y': y, 'y1': y1, 'last_y1': y1,
                         'lines': [line]})
    for row in rows:
        row['text'] = ' '.join((l.get('text') or '').strip()
                               for l in row['lines']).strip()
        row['x0'] = min(float(l.get('x') or 0) for l in row['lines'])
        row['x1'] = max(float(l.get('x1') or (l.get('x') or 0) + 0.1)
                        for l in row['lines'])
    return rows


TEMPLATE_ROW_RE = re.compile(
    r'^(answer area|statements?|statement)$', re.I)
TEMPLATE_TOKENS = {'answer', 'area', 'statements', 'statement', 'yes', 'no'}


def is_template_row(text):
    t = (text or '').strip()
    if TEMPLATE_ROW_RE.match(t):
        return True
    toks = tokens(t)
    return bool(toks) and toks <= TEMPLATE_TOKENS


def structure_rows_of(visual):
    return [r for r in (visual.get('rows') or [])
            if not is_template_row(r.get('text'))]


def structure_blanks_of(visual):
    return visual.get('blanks') or []


def match_token_ratio(a, b):
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    hit = sum(1 for t in ta if any(token_matches(t, u) for u in tb))
    return hit / min(len(ta), len(tb))


def best_text_matches(text, candidates):
    """Rank candidates by (token ratio, absolute matching tokens). A
    longer candidate that matches every token of the text outranks a
    subset that matches only part of it; equal ranks are a tie."""
    scored = []
    for cand in candidates:
        ta, tb = tokens(text), tokens(cand.get('text') or cand)
        if not ta or not tb:
            continue
        hits = sum(1 for t in ta if any(token_matches(t, u) for u in tb))
        ratio = hits / min(len(ta), len(tb))
        scored.append({'text': cand.get('text') or cand,
                       'hits': hits, 'ratio': ratio})
    scored.sort(key=lambda c: (c['ratio'], c['hits']), reverse=True)
    return scored


def unique_text_match(text, candidates):
    """Unique best match by (ratio, matching tokens); None when ambiguous
    or below the correspondence floor."""
    if not normalize(text):
        return None, 0.0
    scored = best_text_matches(text, candidates)
    if not scored or scored[0]['ratio'] < 0.6:
        return None, scored[0]['ratio'] if scored else 0.0
    if len(scored) > 1 and (scored[1]['ratio'], scored[1]['hits']) == \
            (scored[0]['ratio'], scored[0]['hits']):
        return None, scored[0]['ratio']
    return {'text': scored[0]['text']}, scored[0]['ratio']


# ------------------------------------------------------------------ mapping

def statement_lines(lines):
    """OCR lines that carry real statement text: single-glyph misreads of
    marks and checkboxes are not statements."""
    out = []
    for line in lines:
        text = str(line.get('text') or line.get('t') or '').strip()
        if len(WORD_RE.findall(text.lower())) >= 1 \
                and len(text) >= 3:
            out.append(line)
    return out


def segment_into(rows, n):
    """Split vertically ordered rows into n groups by cutting at the n-1
    largest inter-row gaps. The row count comes from the verified
    structure; each group is then validated against its structure row."""
    if n < 1 or len(rows) < n:
        return None
    if n == 1:
        return [rows]
    gaps = []
    for i in range(1, len(rows)):
        gaps.append((rows[i]['y'] - rows[i - 1]['y1'], i))
    cuts = sorted(i for _gap, i in
                  sorted(gaps, key=lambda g: -g[0])[:n - 1])
    groups = []
    start = 0
    for cut in cuts + [len(rows)]:
        groups.append(rows[start:cut])
        start = cut
    return groups


def map_matrix_marks(marks, answer_rows, structure_rows, yes_x, no_x):
    """Map one method's marks onto matrix rows. The answer image's
    statement lines are segmented into exactly as many rows as the
    verified structure has (cutting at the largest gaps); every group's
    text must correspond to its structure row before any mark is
    trusted."""
    lines = [l for r in answer_rows for l in r['lines']]
    st_rows = sorted(
        [dict(text=str(l.get('text') or l.get('t') or ''),
              y=float(l.get('y') or 0),
              y1=float(l.get('y1')) if l.get('y1') is not None
              else float(l.get('y') or 0) + 0.03)
         for l in statement_lines(lines)
         if str(l.get('text') or l.get('t') or '').strip()
         and not is_template_row(l.get('text') or l.get('t') or '')],
        key=lambda r: r['y'])
    groups = segment_into(st_rows, len(structure_rows))
    if groups is None:
        return None, ['answer image does not show %d statement rows'
                      % len(structure_rows)]
    seg_rows = []
    for group in groups:
        seg_rows.append({
            'y': min(r['y'] for r in group),
            'y1': max(r['y1'] for r in group),
            'text': ' '.join(r['text'] for r in group),
        })
    for i, (seg, srow) in enumerate(zip(seg_rows, structure_rows), 1):
        if match_token_ratio(seg['text'], srow.get('text') or '') < 0.6:
            return None, ['answer statement row %d does not correspond to '
                          'structure row %s' % (i, srow.get('id'))]
    reading = {}
    notes = []
    for mark in marks:
        cx = mark['x'] + (mark.get('w') or 0) / 2
        cy = mark['y'] + (mark.get('h') or 0) / 2
        row = None
        for i, seg in enumerate(seg_rows):
            if seg['y'] - 0.02 <= cy <= seg['y1'] + 0.02:
                row = i
                break
        if row is None:
            notes.append('mark at y=%.3f outside statement rows' % cy)
            continue
        srow = structure_rows[row]
        if yes_x is not None and no_x is not None:
            col = 'yes' if abs(cx - yes_x) <= abs(cx - no_x) else 'no'
        elif yes_x is not None:
            col = 'yes' if cx <= yes_x + 0.05 else 'no'
        elif no_x is not None:
            col = 'no' if cx >= no_x - 0.05 else 'yes'
        else:
            notes.append('no Yes/No column headers found')
            continue
        rid = srow['id']
        if rid in reading and reading[rid] != col:
            notes.append('row %s marked both yes and no' % rid)
            return None, notes
        reading[rid] = col
    if reading and set(reading) != {r['id'] for r in structure_rows}:
        notes.append('marks cover %d of %d matrix rows'
                     % (len(reading), len(structure_rows)))
        return None, notes
    return reading or None, notes


def yes_no_columns(lines):
    """Yes/No header x-centres from OCR lines. Accepts answer-image lines
    ({text, x, x1, words}) and visual-draft entries ({t, x, y, c}). A
    header line like "Statements Yes No" still carries word geometry, so
    the columns are read from the words themselves."""
    yes_x = no_x = None
    for line in lines:
        text = line.get('text')
        if text is None:
            text = line.get('t')
        t = str(text or '').strip().lower().rstrip('.,:;')
        x = float(line.get('x') or 0)
        x1 = float(line.get('x1')) if line.get('x1') is not None else x + 0.03
        if t == 'yes' and yes_x is None:
            yes_x = (x + x1) / 2
            continue
        if t == 'no' and no_x is None:
            no_x = (x + (x + 0.02)) / 2
            continue
        words = line.get('words') or []
        if not words or (yes_x is not None and no_x is not None):
            continue
        toks = str(text or '').lower().split()
        if 'yes' in toks and 'no' in toks:
            for w in words:
                wt = str(w.get('t') or '').strip().lower().rstrip('.,:;')
                wx = float(w.get('x') or 0)
                wx1 = wx + float(w.get('w') or 0.03)
                if wt == 'yes' and yes_x is None:
                    yes_x = (wx + wx1) / 2
                elif wt == 'no' and no_x is None:
                    no_x = (wx + (wx + float(w.get('w') or 0.02))) / 2
    return yes_x, no_x


def choice_texts(blank):
    out = []
    for c in (blank.get('choices') or []):
        out.append(c['text'] if isinstance(c, dict) else c)
    return out


def option_rows_of(answer_rows, blanks):
    """Answer-image rows that correspond to structure choices."""
    out = []
    all_choices = [t for b in blanks for t in choice_texts(b)]
    for row in answer_rows:
        if is_template_row(row['text']) or not row['text']:
            continue
        if len(all_choices) and any(
                match_token_ratio(row['text'], t) >= 0.6
                for t in all_choices):
            out.append(row)
    return out


def _blank_of_mark(mark, blanks, answer_rows):
    """Which blank a mark belongs to. Region structures carry each list's
    box; without geometry the answer-image option rows are split into
    vertical runs and matched to blanks in reading order."""
    cy = mark['y'] + (mark.get('h') or 0) / 2
    cx = mark['x'] + (mark.get('w') or 0) / 2
    with_bbox = [b for b in blanks if b.get('bbox')]
    if len(with_bbox) == len(blanks) and blanks:
        hits = []
        for b in blanks:
            x0, y0, x1, y1 = b['bbox']
            if x0 - 0.05 <= cx <= x1 + 0.05 and y0 - 0.05 <= cy <= y1 + 0.05:
                hits.append(b)
        if len(hits) == 1:
            return hits[0], None
        if not hits:
            return None, 'mark at y=%.3f is outside every blank list' % cy
        return None, 'mark at y=%.3f is inside %d blank lists' % (
            cy, len(hits))
    # No per-blank geometry: split option rows into vertical runs.
    rows = sorted(option_rows_of(answer_rows, blanks),
                  key=lambda r: r['y'])
    if not rows:
        return None, 'no option rows found on the answer image'
    runs = [[rows[0]]]
    for row in rows[1:]:
        prev = runs[-1][-1]
        gap = row['y'] - prev['y1']
        if gap > 0.08:
            runs.append([row])
        else:
            runs[-1].append(row)
    if len(runs) != len(blanks):
        return None, ('answer image shows %d option lists for %d blanks'
                      % (len(runs), len(blanks)))
    for blank, run in zip(blanks, runs):
        if any(r['y'] - 0.03 <= cy <= r['y1'] + 0.03 for r in run):
            return blank, None
    return None, 'mark at y=%.3f outside option rows' % cy


def map_dropdown_marks(marks, answer_rows, blanks):
    """Map one method's marks onto dropdown options.

    A mark first belongs to exactly one blank list (geometry when the
    region structure carries it, otherwise vertical runs of option rows),
    then to the unique option row inside that list whose y-band contains
    it. A mark that spans several option rows is whole-list widget
    geometry, never a selection."""
    reading = {}
    notes = []
    for mark in marks:
        cy = mark['y'] + (mark.get('h') or 0) / 2
        blank, note = _blank_of_mark(mark, blanks, answer_rows)
        if blank is None:
            notes.append(note)
            continue
        blank_rows = [r for r in option_rows_of(answer_rows, blanks)
                      if _row_matches_choices(r, blank)]
        if blank.get('bbox'):
            x0, y0, x1, y1 = blank['bbox']
            blank_rows = [r for r in blank_rows
                          if y0 - 0.05 <= (r['y'] + r['y1']) / 2 <= y1 + 0.05]
        hits = [r for r in blank_rows if r['y'] - 0.03 <= cy <= r['y1'] + 0.03]
        if not hits:
            notes.append('mark at y=%.3f outside the option rows of %s'
                         % (cy, blank['id']))
            continue
        mark_h = float(mark.get('h') or 0)
        row_h = max((r['y1'] - r['y']) for r in blank_rows) if blank_rows \
            else 0.05
        if len(hits) > 1 or mark_h > 1.5 * max(row_h, 0.02):
            notes.append('mark at y=%.3f is whole-list widget geometry, '
                         'not a selection' % cy)
            continue
        row = hits[0]
        scored = best_text_matches(row['text'],
                                   [{'text': t}
                                    for t in choice_texts(blank)])
        if not scored or scored[0]['ratio'] < 0.6 or (
                len(scored) > 1 and
                (scored[1]['ratio'], scored[1]['hits']) ==
                (scored[0]['ratio'], scored[0]['hits'])):
            notes.append('option row text does not map to exactly one '
                         'choice of %s: %s' % (blank['id'], row['text'][:40]))
            continue
        choice = scored[0]['text']
        if blank['id'] in reading and reading[blank['id']] != choice:
            notes.append('blank %s marked with two different options'
                         % blank['id'])
            return None, notes
        reading[blank['id']] = choice
    if reading and len(reading) != len(blanks):
        notes.append('marks cover %d of %d blanks' % (len(reading),
                                                      len(blanks)))
        return None, notes
    return reading or None, notes


def _row_matches_choices(row, blank):
    scored = best_text_matches(row['text'],
                               [{'text': t}
                                for t in choice_texts(blank)])
    return bool(scored) and scored[0]['ratio'] >= 0.6


# ------------------------------------------------------------- verification

def verify_text_key(item, visual):
    """Canonical text-key rule: letters map to real options, choose-N fits."""
    raw = (item.get('answer_raw') or '').strip()
    letters = re.findall(r'[A-H]', raw.upper())
    options = item.get('options') or {}
    keys = sorted(options.keys())
    if not letters or not options:
        return {'status': 'blocked_no_text_key',
                'blocker': 'no answer letters in the source text layer'}
    mapped = []
    for letter in letters:
        i = ord(letter) - ord('A')
        if 0 <= i < len(keys) and keys[i] not in mapped:
            mapped.append(keys[i])
    if not mapped:
        return {'status': 'blocked_text_unmapped',
                'blocker': 'answer letters do not map to existing options',
                'answer_raw': raw}
    n = choose_n_from_text(item.get('stem') or '')
    multi = len(mapped) > 1
    if multi and n is not None and len(mapped) != n:
        return {'status': 'blocked_text_choose_n',
                'blocker': 'stem asks to choose %d but the key names %d '
                           'options' % (n, len(mapped)),
                'answer_raw': raw, 'mapped': mapped}
    if not multi and n is not None and n > 1:
        return {'status': 'blocked_text_choose_n',
                'blocker': 'stem asks to choose %d but the key names one '
                           'option' % n,
                'answer_raw': raw, 'mapped': mapped}
    return {
        'status': 'verified_text',
        'answer_raw': raw,
        'answer_key': {'correct_option_ids': mapped},
        'scoring': {
            'type': 'multiple_select' if multi else 'single_choice',
            'choose_n': len(mapped) if multi else 1,
        },
    }


def region_structure_of(item, visual=None):
    """Native structure rebuilt from the Phase 2 strict source regions
    (Phase 3 reconstruction): the structure with verified source
    provenance. The kind comes from the same effective-kind evidence the
    Phase 3 fill used; only the matching structure is rebuilt. Returns
    None when the region evidence is not usable."""
    if not item.get('question_images'):
        return None
    kind, _evidence = P3._effective_kind(item, visual or {})
    if kind == 'yes_no':
        rows, uncertain = P3.reconstruct_matrix_rows(item)
        if rows and not uncertain:
            return {'kind': 'yes_no_matrix', 'rows': rows,
                    'source': 'phase3_strict_source_regions'}
        return None
    if kind == 'dropdown':
        blanks, _text, unreadable = P3.reconstruct_dropdown(item)
        if blanks and not unreadable and all(len(b['choices']) >= 2
                                             for b in blanks):
            return {'kind': ('multi_blank_dropdown' if len(blanks) >= 2
                             else 'inline_dropdown'),
                    'blanks': [{'id': b['id'],
                                'bbox': b.get('norm_bbox'),
                                'choices': [
                                    {'text': c['text'], 'strict': c['strict']}
                                    for c in b['choices']]} for b in blanks],
                    'source': 'phase3_strict_source_regions'}
    return None


def canonical_structure_of(visual):
    rows = structure_rows_of(visual)
    blanks = structure_blanks_of(visual)
    if rows:
        return {'kind': 'yes_no_matrix', 'rows': rows,
                'source': 'canonical_marker_box_flow'}
    if blanks:
        return {'kind': ('multi_blank_dropdown' if len(blanks) >= 2
                         else 'inline_dropdown'),
                'blanks': [{'id': b.get('id'), 'choices': [
                    {'text': c['text'] if isinstance(c, dict) else c,
                     'strict': c.get('strict') if isinstance(c, dict)
                     else None}
                    for c in (b.get('choices') or [])]}
                    for b in blanks],
                'source': 'canonical_marker_box_flow'}
    return None


def structure_deviations(chosen, canonical):
    """Findings for Phase 5: where the canonical converter structure
    differs from the region-verified structure the keys map onto."""
    if not chosen or not canonical or chosen is canonical:
        return []
    out = []
    if chosen['kind'] != canonical['kind']:
        out.append('canonical kind %s differs from region-verified kind %s'
                   % (canonical['kind'], chosen['kind']))
        return out
    if chosen['kind'] == 'yes_no_matrix':
        c_texts = [normalize(r.get('text')) for r in canonical['rows']]
        r_texts = [normalize(r.get('text')) for r in chosen['rows']]
        if len(c_texts) != len(r_texts):
            out.append('canonical flow read %d matrix rows, region evidence '
                       'groups %d' % (len(c_texts), len(r_texts)))
        else:
            for i, (c, r) in enumerate(zip(c_texts, r_texts), 1):
                if c != r and match_token_ratio(c, r) < 0.99:
                    out.append('matrix row r%d differs between canonical '
                               'and region structures' % i)
    else:
        c_shape = [(b['id'], len(b['choices'])) for b in canonical['blanks']]
        r_shape = [(b['id'], len(b['choices'])) for b in chosen['blanks']]
        if c_shape != r_shape:
            out.append('canonical blank shape %s differs from region '
                       'evidence %s' % (c_shape, r_shape))
    return out


def structure_of(item, visual):
    """Region-verified structure first (verified source provenance);
    canonical converter structure as fallback. Keys always map onto the
    best-evidence structure and any deviation is recorded for Phase 5."""
    region = region_structure_of(item, visual)
    canonical = canonical_structure_of(visual)
    if region is not None:
        region['deviations_from_canonical'] = structure_deviations(
            region, canonical)
        return region
    return canonical


def verify_visual_item(item, visual, media_dir, collectors, cfg):
    """Collect every mark method on the answer image, map each onto the
    item's structure, then apply the canonical agreement rule."""
    structure = structure_of(item, visual)
    if structure is None:
        return {'status': 'blocked_no_structure',
                'blocker': 'no native interaction structure for this item '
                           '(see Phase 3 blockers)'}
    answer_images = item.get('answer_images') or []
    question_images = item.get('question_images') or []
    if not answer_images:
        return {'status': 'blocked_no_answer_image',
                'blocker': 'the item has no answer-area image'}
    if len(answer_images) > 1:
        return {'status': 'blocked_multiple_answer_images',
                'blocker': '%d answer images; mark positions cannot be '
                           'combined' % len(answer_images)}
    answer_path = Path(media_dir) / answer_images[0]
    if not answer_path.is_file():
        return {'status': 'blocked_answer_image_missing',
                'blocker': 'answer image %s not found' % answer_images[0]}

    methods = collectors.mark_methods(str(answer_path), cfg)
    answer_lines = collectors.ocr_lines(str(answer_path))
    answer_rows = [r for r in group_lines(answer_lines)
                   if r['text'] and not is_template_row(r['text'])]

    readings = {}
    method_notes = {}
    for name, marks in methods.items():
        if not marks:
            continue
        if structure['kind'] == 'yes_no_matrix':
            yes_x, no_x = yes_no_columns(answer_lines)
            if yes_x is None and no_x is None:
                yes_x, no_x = yes_no_columns(visual.get('ocr') or [])
            reading, notes = map_matrix_marks(
                marks, answer_rows, structure['rows'], yes_x, no_x)
        else:
            reading, notes = map_dropdown_marks(
                marks, answer_rows, structure['blanks'])
        method_notes[name] = notes
        if reading is not None:
            readings[name] = reading

    # Four-edge owner selection box (its own threshold/OCR agreement chain).
    selection = None
    if question_images and structure['kind'] != 'yes_no_matrix':
        question_path = Path(media_dir) / question_images[-1]
        if question_path.is_file():
            try:
                selection = collectors.selection_box(
                    str(question_path), str(answer_path))
            except Exception as exc:  # evidence tool failure is a blocker
                selection = {'status': 'SELECTION_BOX_ERROR', 'error': str(exc)}

    record = {
        'structure_kind': structure['kind'],
        'structure_source': structure.get('source'),
        'method_readings': readings,
        'method_notes': method_notes,
        'marks_found': {name: len(m) for name, m in methods.items()
                        if m},
    }
    if structure.get('deviations_from_canonical'):
        record['canonical_structure_deviations'] = \
            structure['deviations_from_canonical']

    # Canonical agreement rule: MIN_AGREEING_METHODS identical readings.
    groups = {}
    for name, reading in readings.items():
        sig = json.dumps(reading, sort_keys=True, ensure_ascii=False)
        groups.setdefault(sig, []).append(name)
    for sig, names in groups.items():
        if len(names) >= MIN_AGREEING_METHODS:
            record['status'] = 'verified_pixel_agreed'
            record['agreeing_methods'] = names
            key = json.loads(sig)
            if structure['kind'] == 'yes_no_matrix':
                record['answer_key'] = {'rows': key}
                record['scoring'] = {'type': 'yes_no_matrix',
                                     'rows_scored': len(key)}
            else:
                record['answer_key'] = {'slots': key}
                record['scoring'] = {
                    'type': structure['kind'],
                    'blanks_scored': len(key)}
            return record

    if selection and selection.get('status') == 'OWNER_MARK_CANDIDATE_VERIFIED':
        label = normalize(selection.get('selected_label'))
        matched, ratio = unique_text_match(
            selection.get('selected_label') or '',
            [{'text': t} for b in structure['blanks']
             for t in choice_texts(b)])
        if matched is not None:
            # one rigorous chain, but only one independent method
            record['status'] = 'candidate_single_chain'
            record['selection_box'] = {
                'selected_label': selection.get('selected_label'),
                'bbox': selection.get('bbox'),
                'evidence': selection.get('evidence'),
                'maps_to_choice_text': matched['text'],
            }
            record['blocker'] = ('owner selection box verified by its own '
                                 'threshold and OCR chain, but no second '
                                 'independent mark method agrees; needs '
                                 'reviewer or owner confirmation')
            return record
        record['selection_box'] = {
            'selected_label': selection.get('selected_label'),
            'note': 'label does not uniquely match a structure choice',
        }

    if readings:
        record['status'] = 'blocked_contradictory_marks'
        record['blocker'] = ('mark methods disagree or only one method '
                             'produced a reading: %s'
                             % ', '.join(sorted(readings)))
        return record
    if any(methods.values()):
        record['status'] = 'blocked_marks_not_mappable'
        record['blocker'] = ('marks were detected but none maps onto the '
                             'native structure (%s)'
                             % ', '.join(sorted(
                                 k for k, v in methods.items() if v)))
        return record
    record['status'] = 'blocked_no_marks'
    record['blocker'] = 'no owner marks detected on the answer image'
    return record


def verify_question(item, visual, media_dir, collectors, cfg,
                    structure_blockers=None):
    key = item.get('question_key')
    if structure_blockers and key in structure_blockers:
        return {'question_key': key,
                'status': 'blocked_structure_under_review',
                'blocker': structure_blockers[key]}
    if item.get('options'):
        rec = verify_text_key(item, visual)
    else:
        rec = verify_visual_item(item, visual, media_dir, collectors, cfg)
    rec['question_key'] = key
    rec.setdefault('answer_key', None)
    rec['release_approved'] = False
    return rec


def build_evidence(split, visual_draft, media_dir, collectors=None,
                   cfg=None, structure_blockers=None):
    collectors = collectors or Collectors()
    questions = []
    for key in sorted(split,
                      key=lambda k: (split[k].get('source_number') or 0, k)):
        item = split[key]
        visual = (visual_draft or {}).get(key) or {}
        questions.append(verify_question(
            item, visual, media_dir, collectors, cfg,
            structure_blockers=structure_blockers))
    from collections import Counter
    counts = Counter(q['status'] for q in questions)
    verified = [q for q in questions if q['status'].startswith('verified')]
    return {
        'status': 'PHASE4_ANSWER_KEY_EVIDENCE_NOT_RELEASE',
        'keys_verified_only': True,
        'no_key_guessed': True,
        'release_approved': False,
        'summary': {
            'questions': len(questions),
            'verified': len(verified),
            'verified_text': counts.get('verified_text', 0),
            'verified_pixel_agreed': counts.get('verified_pixel_agreed', 0),
            'candidate_single_chain': counts.get('candidate_single_chain', 0),
            'blocked': sum(v for k, v in counts.items()
                           if k.startswith('blocked')),
            'by_status': dict(counts),
        },
        'questions': questions,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    verify = sub.add_parser(
        'verify', help='Verify per-question answer-key evidence.')
    verify.add_argument('--split', required=True)
    verify.add_argument('--visual-draft', required=True)
    verify.add_argument('--media-dir', required=True)
    verify.add_argument('--pipeline-scripts', required=True,
                        help='Pinned upstream scripts dir (vision_util).')
    verify.add_argument('--structure-blockers',
                        help='JSON file: question_key -> blocker reason '
                             'for structures under review.')
    verify.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    if args.cmd != 'verify':
        parser.error('unknown command')

    split = json.loads(Path(args.split).read_text(encoding='utf-8'))
    visual = json.loads(
        Path(args.visual_draft).read_text(encoding='utf-8'))
    blockers = None
    if args.structure_blockers:
        blockers = json.loads(
            Path(args.structure_blockers).read_text(encoding='utf-8'))
    collectors = Collectors(Path(args.pipeline_scripts))
    cfg = collectors.V.load_ocr_config()
    doc = build_evidence(split, visual, args.media_dir,
                         collectors=collectors, cfg=cfg,
                         structure_blockers=blockers)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + '\n',
                   encoding='utf-8')
    print('phase4 key evidence: %d questions, %d verified, %d candidates, '
          '%d blocked (%s)' % (
              doc['summary']['questions'], doc['summary']['verified'],
              doc['summary']['candidate_single_chain'],
              doc['summary']['blocked'], out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
