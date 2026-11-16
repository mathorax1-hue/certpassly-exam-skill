#!/usr/bin/env python3
"""ink_cell: a fourth independent mark method for yes/no matrix items.

Evidence-research method added to the Phase 4 method pool under the
unchanged canonical agreement rule (MIN_AGREEING_METHODS = 2 identical
readings from independent methods). It is deliberately a different
algorithm family from the three canonical detectors:

- marker_box  : dark connected-component rectangle outlines
- checked_box : small square contours with interior fill
- highlight   : HSV colour ranges
- ink_cell    : comparative dark-ink density of the Yes/No cell bands

ink_cell never detects shapes or colours. It locates the two answer
columns from the header band's ink clusters, segments statement rows with
the canonical Phase 4 machinery, measures the dark-pixel density of each
row's Yes and No cell band, and emits one synthetic mark in the winning
cell of every row whose winner is decisive. The emitted marks then flow
through the unchanged canonical mapping and agreement logic.

Fail-closed behaviour: no marks for non-matrix structures, missing header
clusters, degenerate (overlapping) row bands, rows whose winner is not
decisive, or images that cannot be read. Partial coverage produces an
incomplete reading, exactly like any other method.

Validation (frozen parameters, control set = the 16 verified_pixel_agreed
matrix items): 39/39 control rows reproduced exactly; column clusters
match OCR-detected columns within 0.007 on all 20 matrix items. The
``validate`` subcommand re-runs this against a Phase 4 evidence report.

Frozen parameters (fit on controls only, never on held items):
- DARK                = 128   dark-pixel threshold
- CELL_HALF_WIDTH     = 0.045 cell band half-width around a column centre
- ROW_PAD             = 0.012 row band vertical padding
- MIN_WINNER_DENSITY  = 0.10  winning cell must reach this ink density
- MIN_WINNER_RATIO    = 2.0   winning cell must be this times the loser
- CLUSTER_MIN_FRAC    = 0.25  header cluster threshold vs band peak
- CLUSTER_MERGE       = 0.02  merge header clusters closer than this
- BAND_OVERLAP_MAX    = 0.25  allowed overlap fraction of row bands
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

DARK = 128
CELL_HALF_WIDTH = 0.045
ROW_PAD = 0.012
MIN_WINNER_DENSITY = 0.10
MIN_WINNER_RATIO = 2.0
CLUSTER_MIN_FRAC = 0.25
CLUSTER_MERGE = 0.02
BAND_OVERLAP_MAX = 0.25

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import phase4_answer_key_evidence as P4  # noqa: E402


def _density(gray, x0, y0, x1, y1):
    import numpy as np
    H, W = gray.shape
    px = gray[int(max(0.0, y0) * H):int(min(1.0, y1) * H),
              int(max(0.0, x0) * W):int(min(1.0, x1) * W)]
    if px.size == 0:
        return None
    return float((px < DARK).mean())


def header_columns(path, ocr_lines):
    """Yes/No column x-centres from ink clusters in the header band.

    The band is anchored on the 'Statements' OCR line. Exactly two
    clusters in the right half are required; the left one is Yes.
    """
    import cv2
    import numpy as np
    gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None
    H, W = gray.shape
    anchor = None
    for line in ocr_lines:
        if str(line.get('text') or line.get('t') or '').strip().lower() \
                .startswith('statement'):
            y = float(line.get('y') or 0)
            y1 = float(line.get('y1')) if line.get('y1') is not None \
                else y + 0.03
            anchor = (y, y1)
            break
    if anchor is None:
        return None
    y0 = max(0.0, anchor[0] - 0.025)
    y1 = min(1.0, anchor[1] + 0.035)
    band = gray[int(y0 * H):int(np.ceil(y1 * H)), int(0.5 * W):]
    if band.size == 0:
        return None
    dark = (band < DARK).sum(axis=0).astype(float)
    if dark.max() <= 0:
        return None
    on = dark >= CLUSTER_MIN_FRAC * dark.max()
    clusters = []
    x = 0
    while x < len(on):
        if on[x]:
            x2 = x
            while x2 + 1 < len(on) and on[x2 + 1]:
                x2 += 1
            clusters.append(((x + x2) / 2 + 0.5 * W) / W)
            x = x2 + 1
        else:
            x += 1
    merged = []
    for c in clusters:
        if merged and c - merged[-1] < CLUSTER_MERGE:
            merged[-1] = (merged[-1] + c) / 2
        else:
            merged.append(c)
    if len(merged) != 2:
        return None
    return merged[0], merged[1]


def ink_cell_marks(answer_path, item, visual, pipeline_scripts,
                   ocr_lines_fn=None):
    """Synthetic marks for the winning cell of each decisive matrix row.

    Returns a list of marks in the canonical normalized format, or an
    empty list whenever the method abstains. ``ocr_lines_fn`` overrides
    the OCR call (tests inject synthetic lines; production uses the
    pinned upstream vision_util).
    """
    import cv2
    structure = P4.structure_of(item, visual)
    if not structure or structure.get('kind') != 'yes_no_matrix':
        return []
    srows = [r for r in (structure.get('rows') or [])
             if not P4.is_template_row(r.get('text'))]
    if not srows:
        return []
    gray = cv2.imread(str(answer_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return []
    if ocr_lines_fn is None:
        sys.path.insert(0, str(pipeline_scripts))
        import vision_util
        lines, _ = vision_util.ocr_lines(str(answer_path))
    else:
        lines = ocr_lines_fn(str(answer_path))
    cols = header_columns(answer_path, lines)
    if cols is None:
        return []
    yes_x, no_x = cols
    answer_rows = [r for r in P4.group_lines(lines)
                   if r['text'] and not P4.is_template_row(r['text'])]
    flat = [l for r in answer_rows for l in r['lines']]
    st_rows = sorted(
        [dict(text=str(l.get('text') or l.get('t') or ''),
              y=float(l.get('y') or 0),
              y1=float(l.get('y1')) if l.get('y1') is not None
              else float(l.get('y') or 0) + 0.03)
         for l in P4.statement_lines(flat)
         if str(l.get('text') or l.get('t') or '').strip()
         and not P4.is_template_row(l.get('text') or l.get('t') or '')],
        key=lambda r: r['y'])
    groups = P4.segment_into(st_rows, len(srows))
    if groups is None:
        return []
    seg_rows = [{'y': min(r['y'] for r in g),
                 'y1': max(r['y1'] for r in g),
                 'text': ' '.join(r['text'] for r in g)} for g in groups]
    for seg, srow in zip(seg_rows, srows):
        if P4.match_token_ratio(seg['text'], srow.get('text') or '') < 0.6:
            return []
    # degenerate (overlapping) row bands: abstain
    for a, b in zip(seg_rows, seg_rows[1:]):
        ov = min(a['y1'], b['y1']) - max(a['y'], b['y'])
        if ov > BAND_OVERLAP_MAX * min(a['y1'] - a['y'], b['y1'] - b['y']):
            return []
    marks = []
    for seg in seg_rows:
        y0, y1 = seg['y'] - ROW_PAD, seg['y1'] + ROW_PAD
        densities = {}
        for name, cx in (('yes', yes_x), ('no', no_x)):
            densities[name] = _density(
                gray, cx - CELL_HALF_WIDTH, y0, cx + CELL_HALF_WIDTH, y1)
        if any(v is None for v in densities.values()):
            continue
        winner = max(densities, key=densities.get)
        loser = min(densities, key=densities.get)
        if densities[winner] >= MIN_WINNER_DENSITY \
                and densities[winner] >= MIN_WINNER_RATIO * densities[loser]:
            cx = yes_x if winner == 'yes' else no_x
            marks.append({
                'x': cx, 'y': (seg['y'] + seg['y1']) / 2,
                'w': 0.02, 'h': 0.02, 'kind': 'ink_cell',
                'cell': winner,
                'cell_density': {k: round(v, 4)
                                 for k, v in densities.items()},
            })
    return marks


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    val = sub.add_parser('validate', help='Validate on a Phase 4 report.')
    val.add_argument('--report', required=True,
                     help='Phase 4 evidence report (local run).')
    val.add_argument('--split', required=True)
    val.add_argument('--visual-draft', required=True)
    val.add_argument('--media-dir', required=True)
    val.add_argument('--pipeline-scripts', required=True)
    args = parser.parse_args(argv)
    if args.cmd != 'validate':
        parser.error('unknown command')

    split = json.loads(Path(args.split).read_text(encoding='utf-8'))
    visual = json.loads(Path(args.visual_draft).read_text(encoding='utf-8'))
    report = json.loads(Path(args.report).read_text(encoding='utf-8'))
    by = {q['question_key']: q for q in report['questions']}
    controls = [k for k, q in by.items()
                if q.get('status') == 'verified_pixel_agreed'
                and q.get('structure_kind') == 'yes_no_matrix']
    ok = bad = abstain = 0
    for k in sorted(controls):
        item = split[k]
        vis = visual.get(k) or {}
        aimg = (item.get('answer_images') or [None])[0]
        if not aimg:
            abstain += 1
            print('%s ABSTAIN (no answer image)' % k)
            continue
        marks = ink_cell_marks(Path(args.media_dir) / aimg, item, vis,
                               args.pipeline_scripts)
        key = ((by[k].get('answer_key') or {}).get('rows')) or {}
        srows = [r for r in (P4.structure_of(item, vis).get('rows') or [])
                 if not P4.is_template_row(r['text'])]
        if not marks:
            abstain += 1
            print('%s ABSTAIN (no marks)' % k)
            continue
        if len(marks) != len(srows):
            bad += 1
            print('%s MISMATCH marks=%d rows=%d' % (k, len(marks),
                                                    len(srows)))
            continue
        # document-ordered rows pair with y-ordered marks
        reading = {srow['id']: m['cell']
                   for srow, m in zip(srows, sorted(marks,
                                                    key=lambda m: m['y']))}
        if reading == key:
            ok += 1
            print('%s OK %s' % (k, key))
        else:
            bad += 1
            print('%s MISMATCH ink=%s key=%s' % (k, reading, key))
    print('controls: %d, ok: %d, mismatch: %d, abstain: %d'
          % (len(controls), ok, bad, abstain))
    return 0 if bad == 0 and abstain == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
