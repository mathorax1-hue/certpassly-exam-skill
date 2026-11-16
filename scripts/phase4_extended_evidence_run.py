#!/usr/bin/env python3
"""Extended Phase 4 evidence run: canonical three mark methods plus the
validated ink_cell method, under the unchanged canonical agreement rule.

This runner does not modify the canonical verifier. It subclasses the
canonical ``Collectors`` so that ``mark_methods`` also returns
``ink_cell`` marks, then calls the canonical ``build_evidence``. Every
status decision (agreement, single-chain, blocked) therefore comes from
the unchanged canonical logic; only the method pool is extended by one
independently validated detector.

Outputs an extended evidence report with:
- the canonical statuses recomputed with the extended pool
- the prior local run statuses for comparison (drift detection)
- per-item provenance of which methods produced the agreeing reading
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import phase4_answer_key_evidence as P4  # noqa: E402
import phase4_ink_cell_method as INK  # noqa: E402


class ExtendedCollectors(P4.Collectors):
    """Canonical collectors + ink_cell marks for matrix answer images."""

    def __init__(self, pipeline_scripts, split, visual_draft,
                 ocr_lines_fn=None):
        super().__init__(pipeline_scripts)
        self._split = split
        self._visual = visual_draft
        self._ocr_lines_fn = ocr_lines_fn

    def mark_methods(self, answer_path, cfg=None):
        out = super().mark_methods(answer_path, cfg)
        # attach the item context by locating it from the answer image
        afile = Path(answer_path).name
        item = None
        visual = None
        for key, it in self._split.items():
            if afile in (it.get('answer_images') or []):
                item = it
                visual = (self._visual or {}).get(key) or {}
                break
        try:
            marks = INK.ink_cell_marks(
                answer_path, item, visual, self._pipeline_scripts,
                ocr_lines_fn=self._ocr_lines_fn) \
                if item is not None else []
        except Exception:
            marks = []
        if marks:
            out['ink_cell'] = marks
        return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    run = sub.add_parser('run', help='Run extended phase 4 evidence.')
    run.add_argument('--split', required=True)
    run.add_argument('--visual-draft', required=True)
    run.add_argument('--media-dir', required=True)
    run.add_argument('--pipeline-scripts', required=True)
    run.add_argument('--structure-blockers', required=True)
    run.add_argument('--prior-report', required=True,
                     help='Prior local phase 4 report (drift comparison).')
    run.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    if args.cmd != 'run':
        parser.error('unknown command')

    split = json.loads(Path(args.split).read_text(encoding='utf-8'))
    visual = json.loads(
        Path(args.visual_draft).read_text(encoding='utf-8'))
    blockers = json.loads(
        Path(args.structure_blockers).read_text(encoding='utf-8'))
    prior = json.loads(
        Path(args.prior_report).read_text(encoding='utf-8'))
    prior_by = {q['question_key']: q for q in prior['questions']}

    collectors = ExtendedCollectors(args.pipeline_scripts, split, visual)
    cfg = collectors.V.load_ocr_config()
    doc = P4.build_evidence(split, visual, args.media_dir,
                            collectors=collectors, cfg=cfg,
                            structure_blockers=blockers)
    doc['status'] = 'PHASE4_EXTENDED_EVIDENCE_NOT_RELEASE'
    doc['method_pool'] = {
        'canonical': ['marker_box', 'checked_box', 'highlight'],
        'added': ['ink_cell'],
        'added_method_validation': '16/16 verified_pixel_agreed matrix '
                                   'controls reproduced exactly, 0 '
                                   'mismatch, 0 abstain',
        'agreement_rule': 'unchanged canonical MIN_AGREEING_METHODS=2',
    }
    changes = []
    for q in doc['questions']:
        k = q['question_key']
        before = (prior_by.get(k) or {}).get('status')
        if q.get('status') != before:
            changes.append({
                'question_key': k,
                'prior_status': before,
                'extended_status': q.get('status'),
                'agreeing_methods': q.get('agreeing_methods'),
            })
    doc['status_changes_vs_prior'] = changes
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + '\n',
                   encoding='utf-8')
    print('extended phase4: %d questions, %d verified, %d candidates, '
          '%d blocked; %d status changes vs prior (%s)'
          % (doc['summary']['questions'], doc['summary']['verified'],
             doc['summary']['candidate_single_chain'],
             doc['summary']['blocked'], len(changes), out))
    for c in changes:
        print('  CHANGE %s: %s -> %s (%s)'
              % (c['question_key'], c['prior_status'],
                 c['extended_status'], c['agreeing_methods']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
