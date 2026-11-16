#!/usr/bin/env python3
"""Apply an owner decision file to extended phase 4 evidence.

STANDALONE TOOL - NOT WIRED INTO ANY GATE OR WORKFLOW.

This composes `AB900-PHASE4-OWNER-DECIDED.json` style evidence from:
  --decisions  the owner decision file exported by the owner review
               tool (schema v1, decision_version=1)
  --phase4     the extended phase 4 answer-key evidence (statuses and
               machine-verified keys; used for override detection)
  --held       the phase 5 hold records (cannot-convert.json) carrying
               the native structures of held questions
  --candidate  the site-format candidate (structures of exported
               questions; required only when editorial_conflicts
               override exported keys)
  --conflicts  the official-answer-conflicts review file (required only
               when the decision file carries editorial_conflicts)

Fail-closed rules (every violation is RECORDED and fails the run):
  - decision_version must be 1; exam must match --exam
  - decided_by non-empty; decided_date YYYY-MM-DD
  - unknown question keys, row ids, blank ids or option ids rejected
  - a confirmed key must be COMPLETE (every row/blank) and map onto the
    real structure; partial decisions are recorded as rejected_partial
    and the question stays held - they never become confirmations
  - a key that contradicts a machine-verified key is rejected here;
    overriding a verified key must go through editorial_conflicts with
    explicit evidence (non-empty note); both the previous value and the
    override are preserved
  - no thresholds, floors or gate rules are read or changed here

Exit code: 0 when there are zero rejections, 1 otherwise (the output
file is still written, recording every rejection and its reason).
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

DECISION_ENUM = {'no_decision', 'confirm_full', 'confirm_key',
                 'partial_key', 'text_only', 'structure_provided'}
EC_ENUM = {'no_decision', 'retain', 'override', 'retire'}
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
VERIFIED_STATUSES = ('verified_text', 'verified_pixel_agreed')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def structure_of(key, held, candidate):
    """Return (rows, blanks) ids for a question key, or (None, None)."""
    h = held.get(key)
    if h:
        inter = (h.get('native_structure') or {}).get('interaction') or {}
        rows = [r['id'] for r in
                (inter.get('matrix') or {}).get('rows') or []]
        blanks = {(b.get('id') or ''): [o.get('id') for o in
                                        b.get('options') or []]
                  for b in (inter.get('cloze') or {}).get('blanks') or []}
        return rows, blanks
    q = (candidate or {}).get(key)
    if q:
        inter = ((q.get('learner') or {}).get('interaction')) or {}
        rows = [r['id'] for r in
                (inter.get('matrix') or {}).get('rows') or []]
        blanks = {(b.get('id') or ''): [o.get('id') for o in
                                        b.get('options') or []]
                  for b in (inter.get('cloze') or {}).get('blanks') or []}
        return rows, blanks
    return None, None


def norm_option_text(t):
    return ' '.join(re.findall(r'[A-Za-z0-9]+', (t or '').lower()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--decisions', required=True)
    ap.add_argument('--phase4', required=True)
    ap.add_argument('--held')
    ap.add_argument('--candidate')
    ap.add_argument('--conflicts')
    ap.add_argument('--exam', default='AB-900')
    ap.add_argument('--output', required=True)
    args = ap.parse_args(argv)

    dec_path = Path(args.decisions)
    dec = load(dec_path)
    dec_sha = hashlib.sha256(dec_path.read_bytes()).hexdigest()
    p4 = {q['question_key']: q for q in
          load(args.phase4).get('questions', [])}
    held = {}
    if args.held:
        held = {h['question_key']: h for h in load(args.held)}
    candidate = {}
    if args.candidate:
        candidate = {q['question_key']: q
                     for q in load(args.candidate).get('questions', [])}
    conflicts = {}
    if args.conflicts:
        conflicts = {it['question_key']: it for it in
                     load(args.conflicts).get('items', [])}

    rejections = []

    def reject(key, reason):
        rejections.append({'question_key': key, 'reason': reason})

    # ---- file-level validation
    if dec.get('decision_version') != 1:
        print('REJECT: decision_version must be 1, got %r'
              % dec.get('decision_version'))
        return 1
    if dec.get('exam') != args.exam:
        print('REJECT: exam %r does not match --exam %s'
              % (dec.get('exam'), args.exam))
        return 1
    if not (dec.get('decided_by') or '').strip():
        print('REJECT: decided_by is empty')
        return 1
    if not DATE_RE.match(dec.get('decided_date') or ''):
        print('REJECT: decided_date must be YYYY-MM-DD, got %r'
              % dec.get('decided_date'))
        return 1

    questions_out = {}
    for key, entry in (dec.get('questions') or {}).items():
        if key not in p4:
            reject(key, 'unknown question key (not in phase 4 evidence)')
            continue
        decision = entry.get('decision')
        if decision not in DECISION_ENUM:
            reject(key, 'invalid decision %r' % decision)
            continue
        rows, blanks = structure_of(key, held, candidate)
        rec = {'status': 'no_decision', 'stays_held': True,
               'provenance': 'owner_review_tool'}
        key_map = entry.get('key') or {}
        text_map = entry.get('text') or {}
        p4rec = p4.get(key) or {}
        prev_verified = (p4rec.get('answer_key')
                         if p4rec.get('status') in VERIFIED_STATUSES
                         else None)

        if decision == 'partial_key':
            reject(key, 'incomplete key decision (partial_key): the '
                    'question stays held and nothing is confirmed')
            continue
        if key_map and prev_verified is not None:
            reject(key, 'key contradicts a machine-verified key; '
                    'overrides must go through editorial_conflicts '
                    'with explicit evidence')
            continue
        if key_map and rows:                       # matrix decision
            bad = [r for r in key_map if r not in rows]
            bad += [r for r in rows if r not in key_map]
            vals_bad = [r for r, v in key_map.items()
                        if v not in ('yes', 'no')]
            if bad:
                reject(key, 'row ids do not match the structure '
                        '(missing %r / unknown %r)'
                        % ([r for r in rows if r not in key_map],
                           [r for r in key_map if r not in rows]))
                continue
            if vals_bad:
                reject(key, 'matrix values must be yes/no, got %r'
                        % {r: key_map[r] for r in vals_bad})
                continue
            rec.update({'status': 'owner_confirmed',
                        'answer_key': {'rows': key_map},
                        'key_complete': True, 'stays_held': False})
        elif key_map and blanks:                   # dropdown decision
            bad = [b for b in key_map if b not in blanks]
            bad += [b for b in blanks if b not in key_map]
            opt_bad = [b for b, o in key_map.items()
                       if b in blanks and o not in blanks[b]]
            if bad:
                reject(key, 'blank ids do not match the structure '
                        '(missing %r / unknown %r)'
                        % ([b for b in blanks if b not in key_map],
                           [b for b in key_map if b not in blanks]))
                continue
            if opt_bad:
                reject(key, 'option ids do not exist: %r' % opt_bad)
                continue
            rec.update({'status': 'owner_confirmed',
                        'answer_key': {'blanks': key_map},
                        'key_complete': True, 'stays_held': False})
        elif key_map:
            reject(key, 'key given but no structure rows/blanks found '
                    'for this question')
            continue

        if text_map:
            need = rows or sorted(blanks) or []
            covered = [r for r in need if r in text_map]
            if rows:
                text_ok = len(covered) == len(rows)
            else:
                text_ok = all(('%s_options' % b) in text_map
                              for b in blanks)
            rec['owner_confirmed_text'] = text_map
            rec['text_complete'] = bool(text_ok)
            if rec['status'] == 'no_decision':
                rec['status'] = ('owner_text_confirmed' if text_ok
                                 else 'rejected_partial_text')
                if not text_ok:
                    reject(key, 'text confirmation does not cover every '
                            'row/blank-options block')
                    rec['stays_held'] = True
                else:
                    rec['stays_held'] = False
        if decision == 'structure_provided':
            raw = entry.get('structure')
            try:
                s = json.loads(raw) if isinstance(raw, str) else raw
                assert s.get('type') and s.get('key')
            except Exception:
                reject(key, 'structure_provided but structure is not '
                        'valid JSON with type+key')
                continue
            rec.update({'status': 'owner_structure_provided',
                        'structure': s, 'stays_held': False})
        questions_out[key] = rec

    # ---- editorial conflicts
    ec_out = {}
    for key, entry in (dec.get('editorial_conflicts') or {}).items():
        if key not in conflicts:
            reject(key, 'editorial conflict decision for a question '
                    'not in the conflicts review file')
            continue
        decision = entry.get('decision')
        if decision not in EC_ENUM:
            reject(key, 'invalid editorial decision %r' % decision)
            continue
        p4rec = p4.get(key) or {}
        previous = (p4rec.get('answer_key')
                    if p4rec.get('status') in VERIFIED_STATUSES else None)
        rec = {'status': 'no_decision', 'previous_key': previous,
               'owner_source_selection':
                   conflicts[key].get('owner_source_selection'),
               'editorial_concern': conflicts[key].get('concern'),
               'official_url': conflicts[key].get('official_url')}
        if decision == 'retain':
            rec.update({'status': 'owner_retained'})
        elif decision == 'retire':
            rec.update({'status': 'owner_retired',
                        'retired': True})
        elif decision == 'override':
            note = (entry.get('note') or '').strip()
            if not note:
                reject(key, 'override of a machine-verified key requires '
                        'explicit evidence (non-empty note)')
                ec_out[key] = rec
                continue
            override_to = entry.get('override_to')
            rows, blanks = structure_of(key, held, candidate)
            valid = True
            if rows:
                if not isinstance(override_to, dict):
                    valid = False
                else:
                    for r in rows:
                        if override_to.get(r) not in ('yes', 'no'):
                            valid = False
                    if set(override_to) != set(rows):
                        valid = False
            elif blanks:
                if not isinstance(override_to, dict):
                    valid = False
                else:
                    cand_q = candidate.get(key) or {}
                    cloze = ((cand_q.get('learner') or {})
                             .get('interaction') or {}).get('cloze') or {}
                    real = {b.get('id'): [o.get('text') for o in
                                          b.get('options') or []]
                            for b in cloze.get('blanks') or []}
                    if set(override_to) != set(blanks):
                        valid = False
                    else:
                        for b, v in override_to.items():
                            if v not in real.get(b, []):
                                valid = False
            else:  # single/multiple choice: option index list
                cand_q = candidate.get(key) or {}
                n_opts = len((cand_q.get('learner') or {})
                             .get('choices') or [])
                if not isinstance(override_to, list) or not override_to:
                    valid = False
                else:
                    for i in override_to:
                        if not isinstance(i, int) or not (
                                0 <= i < n_opts):
                            valid = False
            if not valid:
                reject(key, 'override_to does not map onto the question '
                        'structure/options')
                ec_out[key] = rec
                continue
            rec.update({'status': 'owner_overridden',
                        'override_to': override_to, 'evidence': note})
        ec_out[key] = rec

    n_conf = sum(1 for r in questions_out.values()
                 if r['status'] == 'owner_confirmed')
    n_text = sum(1 for r in questions_out.values()
                 if r['status'] == 'owner_text_confirmed')
    n_struct = sum(1 for r in questions_out.values()
                   if r['status'] == 'owner_structure_provided')
    n_ec = sum(1 for r in ec_out.values()
               if r['status'] != 'no_decision')
    counts = {'questions_decided': len(questions_out),
              'owner_confirmed': n_conf,
              'owner_text_confirmed': n_text,
              'owner_structure_provided': n_struct,
              'editorial_conflicts_decided': n_ec,
              'rejections': len(rejections)}
    assert counts['owner_confirmed'] + counts[
        'owner_text_confirmed'] + counts['owner_structure_provided'] \
        <= len(questions_out)

    out = {
        'status': ('PHASE4_OWNER_DECIDED' if not rejections
                   else 'PHASE4_OWNER_DECIDED_WITH_REJECTIONS'),
        'standalone_note': ('composed by apply_owner_decisions.py; NOT '
                            'consumed by any phase 4/5 gate yet - '
                            'activating it requires owner approval of '
                            'the gate rule change'),
        'provenance': {
            'decided_by': dec.get('decided_by'),
            'decided_date': dec.get('decided_date'),
            'decision_file': str(dec_path),
            'decision_file_sha256': dec_sha,
            'tool_source': dec.get('source'),
        },
        'counts': counts,
        'rejections': rejections,
        'questions': questions_out,
        'editorial_conflicts': ec_out,
    }
    Path(args.output).write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8')
    print('wrote %s (%d confirmed, %d text-confirmed, %d structure, '
          '%d editorial decisions, %d rejections)'
          % (args.output, n_conf, n_text, n_struct, n_ec,
             len(rejections)))
    for r in rejections:
        print('REJECTED %s: %s' % (r['question_key'], r['reason']))
    return 1 if rejections else 0


if __name__ == '__main__':
    sys.exit(main())
