#!/usr/bin/env python3
"""Run the TEST-ONLY question-type fixture PDF through the PDF to site v2 path.

The fixture (tests/fixtures/question-types) is synthetic and must never be
promoted. This script:
  1. extracts the PDF, runs OCR and the visual stage, and builds the site v2
     file with the pinned upstream pipeline (scripts only, AI off);
  2. compares every question with truth.json (type, answer key and the text
     the learner sees) and checks the expected holds;
  3. optionally imports the file into the local import sandbox and grades a
     correct and a wrong response for every question (--sandbox).

Exit code 0 only when every check passes. Never touches production, port
3306 or the 8330 audit worktree (the sandbox gate refuses those itself).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
FIXTURE = SKILL / 'tests' / 'fixtures' / 'question-types'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plain(rich) -> str:
    if rich is None:
        return ''
    if isinstance(rich, str):
        return rich
    if isinstance(rich, dict):
        out = []
        if 'text' in rich and isinstance(rich['text'], str):
            out.append(rich['text'])
        for k in ('content', 'items'):
            if k in rich:
                out.append(plain(rich[k]))
        return ' '.join(x for x in out if x)
    if isinstance(rich, list):
        return ' '.join(x for x in (plain(v) for v in rich) if x)
    return str(rich)


def norm(t: str) -> str:
    return ' '.join((t or '').split()).strip()


def run_pipeline(upstream: Path, pdf: Path, work: Path, exam: str) -> Path:
    if work.exists():
        shutil.rmtree(work)
    out = work / 'out' / exam
    out.mkdir(parents=True)
    env = dict(os.environ)
    env['CERTPASSLY_SKILL_ROOT'] = str(upstream)
    env['CERTPASSLY_AI_VISION_ENABLED'] = 'false'
    env['CERTPASSLY_AI_VISION_PROVIDER'] = 'none'
    env.pop('GROQ_API_KEY', None)
    py = sys.executable
    s = upstream / 'scripts'
    logf = open(work / 'fixture-run.log', 'w', encoding='utf-8')
    for cmd in ([py, str(s / 'extract_owner_pdf.py'), str(pdf), str(out)],
                [py, str(s / 'ocr_extract.py'), str(out), str(pdf)],
                [py, str(s / 'build_technical_export.py'), '--exam', exam, '--out-dir', str(out),
                 '--root', str(work)]):
        r = subprocess.run(cmd, env=env, stdout=logf, stderr=subprocess.STDOUT, cwd=str(work))
        if r.returncode != 0:
            raise SystemExit('fixture pipeline step failed (%s); see %s' % (Path(cmd[1]).name, work / 'fixture-run.log'))
    logf.close()
    return out


SINGLE = {'single_choice', 'true_false', 'inline_dropdown', 'image_based_choice', 'hotspot_single'}
SETS = {'multiple_select', 'hotspot_multi'}
PUBLISHABLE = ['single_choice', 'multiple_select', 'true_false', 'image_based_choice', 'scenario_standalone',
               'yes_no_matrix', 'single_choice_matrix', 'inline_dropdown', 'multi_blank_dropdown', 'ordering',
               'matching', 'categorization', 'drag_drop', 'hotspot_single', 'hotspot_multi', 'case_study_group']
STAGING = ['multi_select_matrix', 'text_cloze', 'short_text', 'numeric']
STAGING_TAG = 'staging_draft_only'


def _first(v):
    if isinstance(v, dict):
        return next(iter(v.values()), None)
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _same(want, got) -> bool:
    return got is not None and got != '' and not isinstance(got, (list, dict)) and str(want) == str(got)


def _keyed(key):
    if isinstance(key, dict):
        return {str(k): v for k, v in key.items()}
    if isinstance(key, list):
        return {str(i): v for i, v in enumerate(key)}
    return {}


def _norm_text(s) -> str:
    return ' '.join(str(s).split()).lower()


def _as_list(v):
    if isinstance(v, list):
        return v
    if v is None:
        return []
    return [v]


def grade(qtype: str, key, response) -> bool:
    """Python mirror of the sandbox SiteFormatGrader (all or nothing)."""
    if qtype in SINGLE:
        got = response.get('value', response) if isinstance(response, dict) else response
        return _same(_first(key), _first(got))
    if qtype in SETS:
        got = response.get('value', response) if isinstance(response, dict) else response
        a = sorted(str(x) for x in (key if isinstance(key, list) else [key]))
        b = sorted(str(x) for x in (got if isinstance(got, list) else [got]) if not isinstance(x, (list, dict)))
        return bool(a) and a == b
    if qtype == 'short_text':
        accepted = (key or {}).get('accepted') if isinstance(key, dict) else key
        got = response.get('value', response) if isinstance(response, dict) else response
        return any(_norm_text(a) == _norm_text(got) and _norm_text(got) != '' for a in (accepted or []))
    if qtype == 'numeric':
        got = response.get('value', response) if isinstance(response, dict) else response
        try:
            got_n = float(str(got).split()[0])
        except (TypeError, ValueError, IndexError):
            return False
        if isinstance(key, dict) and key.get('range'):
            lo, hi = (float(key['range'][0]), float(key['range'][1]))
            return lo <= got_n <= hi
        try:
            want = float((key or {}).get('value') if isinstance(key, dict) else key)
        except (TypeError, ValueError):
            return False
        tol = 0.0
        if isinstance(key, dict) and key.get('tolerance') is not None:
            tol = float(key['tolerance'])
            if (key.get('tolerance_type') or 'absolute') == 'relative':
                tol = abs(want) * tol
        return abs(got_n - want) <= tol
    resp = _keyed(response)
    if qtype == 'ordering':
        parts = [_same(pos + 1, resp.get(str(item))) for pos, item in enumerate(key)]
    elif qtype == 'multi_select_matrix':
        parts = []
        for k, want in _keyed(key).items():
            got = resp.get(k)
            a = sorted(map(str, _as_list(want)))
            b = sorted(map(str, _as_list(got)))
            parts.append(bool(a) and a == b)
    elif qtype == 'text_cloze':
        parts = [_norm_text(want) == _norm_text(resp.get(k, '')) and _norm_text(want) != ''
                 for k, want in _keyed(key).items()]
    else:
        parts = [_same(want, resp.get(k)) for k, want in _keyed(key).items()]
    return bool(parts) and all(parts)


def correct_response(qtype: str, key):
    if qtype in SINGLE:
        return {'value': str(_first(key))}
    if qtype in SETS:
        return [str(x) for x in key]
    if qtype == 'ordering':
        return {str(item): pos + 1 for pos, item in enumerate(key)}
    if qtype == 'short_text':
        acc = (key or {}).get('accepted') if isinstance(key, dict) else key
        return {'value': str((acc or [''])[0])}
    if qtype == 'numeric':
        if isinstance(key, dict) and key.get('value') is not None:
            text = str(key['value'])
            if key.get('unit'):
                text = '%s %s' % (text, key['unit'])
            return {'value': text}
        if isinstance(key, dict) and key.get('range'):
            return {'value': str(key['range'][0])}
        return {'value': str(key)}
    if qtype == 'multi_select_matrix':
        return {str(k): list(v) if isinstance(v, list) else [v] for k, v in dict(key).items()}
    if isinstance(key, list):
        return [str(x) for x in key]
    return dict(key)


def wrong_response(qtype: str, key):
    """The correct response with exactly one part changed."""
    right = correct_response(qtype, key)
    if qtype in SINGLE:
        return {'value': right['value'] + '_wrong'}
    if qtype in SETS:
        return right[1:] if len(right) > 1 else right + ['__other__']
    if qtype == 'ordering':
        ks = list(right)
        w = dict(right)
        w[ks[0]], w[ks[1]] = right[ks[1]], right[ks[0]]
        return w
    if qtype == 'short_text':
        return {'value': str(right.get('value', '')) + '_wrong'}
    if qtype == 'numeric':
        return {'value': '0'}
    if qtype == 'multi_select_matrix':
        w = {k: list(v) for k, v in right.items()}
        first = next(iter(w))
        if len(w[first]) > 1:
            w[first] = w[first][1:]
        else:
            w[first] = w[first] + ['__other__']
        return w
    if isinstance(right, list):
        return ['__wrong__'] + right[1:]
    w = dict(right)
    w[next(iter(w))] = '__wrong__'
    return w


def cloze_view(q: dict) -> dict:
    """A one-blank inline_dropdown is exported in the site's single-select shape
    (sentence in the stem with ____, options as choices, key = option index).
    Rebuild the cloze view so it compares with the truth file."""
    L = q.get('learner') or {}
    if q.get('type') != 'inline_dropdown' or (L.get('interaction') or {}).get('cloze') or not L.get('choices'):
        return q
    stem = L.get('stem') or []
    sentence = plain([stem[-1]]) if stem else ''
    parts = sentence.split('____')
    segs = []
    for i, part in enumerate(parts):
        if part:
            segs.append({'text': part})
        if i < len(parts) - 1:
            segs.append({'blank': 'blank1'})
    opts = [{'id': 'blank1_o%d' % (i + 1), 'text': plain(c)} for i, c in enumerate(L['choices'])]
    key = q['answer']['answer_key']
    idx = int(key[0]) if isinstance(key, list) and key else None
    L2 = dict(L, stem=stem[:-1], interaction=dict(L.get('interaction') or {}, cloze={'segments': segs, 'blanks': [{'id': 'blank1', 'options': opts}]}))
    L2.pop('choices', None)
    ans = dict(q['answer'], answer_key={'blank1': opts[idx]['id']} if idx is not None and idx < len(opts) else key)
    return dict(q, learner=L2, answer=ans)


def compare(truth: dict, site: dict, fidelity: dict) -> list[dict]:
    prefix = str((site.get('exam') or {}).get('exam_code') or truth.get('exam_code') or '') + '-'
    # the site file carries exam-scoped keys (QTYPE-FIXTURE-q001); truth uses the PDF key
    by_key = {(q['question_key'][len(prefix):] if q['question_key'].startswith(prefix) else q['question_key']): q
              for q in site.get('questions') or []}
    fid = {r['question_key']: r for r in fidelity.get('items') or []}
    rows = []
    for t in truth['questions']:
        k = t['question_key']
        q = by_key.get(k)
        if q is not None:
            q = cloze_view(q)
        problems = []
        if t.get('held'):
            if q is not None:
                problems.append('expected a hold but the question was exported')
            reason = (fid.get(k) or {}).get('reason') or ''
            if t.get('hold_reason_contains') and t['hold_reason_contains'] not in reason:
                problems.append('hold reason %r does not contain %r' % (reason[:160], t['hold_reason_contains']))
            rows.append({'question_key': k, 'expected': 'held', 'ok': not problems, 'problems': problems})
            continue
        if q is None:
            problems.append('not exported: %s' % ((fid.get(k) or {}).get('reason') or 'no reason')[:300])
            rows.append({'question_key': k, 'expected': t['type'], 'ok': False, 'problems': problems})
            continue
        if q['type'] != t['type']:
            problems.append('type %s, expected %s' % (q['type'], t['type']))
        key = q['answer']['answer_key']
        if key != t['answer_key']:
            problems.append('answer key %s, expected %s' % (json.dumps(key), json.dumps(t['answer_key'])))
        if t.get('staging_draft_only') and STAGING_TAG not in (q.get('tags') or []):
            problems.append('staging type is missing the %s tag' % STAGING_TAG)
        L = q['learner']
        inter = L.get('interaction') or {}
        if 'choices' in t and [norm(plain(c)) for c in L.get('choices') or []] != t['choices']:
            problems.append('choices differ: %s' % [plain(c) for c in L.get('choices') or []])
        if 'rows' in t:
            got = [norm(plain(r['text'])) for r in (inter.get('matrix') or {}).get('rows') or []]
            if got != t['rows']:
                problems.append('rows differ: %s' % got)
        if 'columns' in t:
            got = [c['text'] for c in (inter.get('matrix') or {}).get('columns') or []]
            if got != t['columns']:
                problems.append('columns differ: %s' % got)
        if 'cloze' in t:
            cz = inter.get('cloze') or {}
            got = norm(' '.join(s.get('text') or '[%s]' % s['blank'] for s in cz.get('segments') or []))
            if got != norm(t['cloze']):
                problems.append('cloze reads %r, expected %r' % (got, t['cloze']))
            opts = {b['id']: [o['text'] for o in b.get('options') or []] for b in cz.get('blanks') or []}
            if opts != t['blank_options']:
                problems.append('drop-down options differ: %s' % opts)
        if 'ordering' in t and inter.get('ordering') != t['ordering']:
            problems.append('ordering items differ: %s' % inter.get('ordering'))
        if 'matching_pairs' in t and inter.get('matching_pairs') != t['matching_pairs']:
            problems.append('matching pairs differ: %s' % inter.get('matching_pairs'))
        if 'items' in t and [norm(plain(c)) for c in L.get('choices') or []] != t['items']:
            problems.append('items differ: %s' % [plain(c) for c in L.get('choices') or []])
        if 'slots' in t and inter.get('drag_slots') != t['slots']:
            problems.append('slots differ: %s' % inter.get('drag_slots'))
        if 'regions' in t:
            got = {r['id']: r['label'] for r in inter.get('hotspot_regions') or []}
            if got != t['regions']:
                problems.append('hotspot regions differ: %s' % got)
        rows.append({'question_key': k, 'expected': t['type'], 'ok': not problems, 'problems': problems})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--upstream', required=True, help='Pinned upstream pipeline checkout (patched).')
    ap.add_argument('--work', default='/tmp/certpassly-qtype-fixture')
    ap.add_argument('--fixture-dir', default=str(FIXTURE))
    ap.add_argument('--sandbox', help='Local import sandbox (optional).')
    ap.add_argument('--php', default='php')
    ap.add_argument('--report', help='Write the JSON report here.')
    args = ap.parse_args(argv)
    fx = Path(args.fixture_dir)
    truth = json.loads((fx / 'truth.json').read_text(encoding='utf-8'))
    if not truth.get('test_only') or not truth.get('never_promote'):
        print('refusing: fixture truth is not marked test_only and never_promote', file=sys.stderr)
        return 2
    work = Path(args.work)
    pdf = fx / 'TEST-FIXTURE-question-types.pdf'
    if not pdf.is_file():
        # PDFs are not committed (public safety): build the synthetic fixture from its script
        gen = Path(tempfile.mkdtemp(prefix='qtype-fixture-'))
        subprocess.run([sys.executable, str(fx / 'make_fixtures.py'), str(gen)], check=True,
                       stdout=subprocess.DEVNULL)
        pdf = gen / 'TEST-FIXTURE-question-types.pdf'
        if json.loads((gen / 'truth.json').read_text(encoding='utf-8')) != truth:
            print('refusing: generated fixture truth differs from truth.json', file=sys.stderr)
            return 2
    out = run_pipeline(Path(args.upstream).resolve(), pdf, work, truth['exam_code'])
    site_path = out / ('%s.site-format.v2.json' % truth['exam_code'])
    site = json.loads(site_path.read_text(encoding='utf-8'))
    fidelity = json.loads((out / 'export' / 'fidelity.json').read_text(encoding='utf-8'))
    rows = compare(truth, site, fidelity)
    report = {
        'fixture_pdf': pdf.name, 'fixture_pdf_sha256': sha256(pdf),
        'site_file': str(site_path), 'site_file_sha256': sha256(site_path),
        'exported': len(site.get('questions') or []), 'held': fidelity.get('held'),
        'checks': rows, 'ok': all(r['ok'] for r in rows),
    }
    if args.sandbox:
        gate_report = work / 'sandbox-import.json'
        cmd = [args.php, str(HERE / 'site_import_gate.php'), '--sandbox=%s' % args.sandbox,
               '--file=%s' % site_path, '--report=%s' % gate_report, '--grade-all']
        r = subprocess.run(cmd, capture_output=True, text=True)
        gate = json.loads(gate_report.read_text(encoding='utf-8')) if gate_report.is_file() else {}
        samples = gate.get('grading_samples') or []
        graded_ok = bool(samples) and all(s.get('correct_response_accepted') and s.get('wrong_response_rejected')
                                          for s in samples)
        report['sandbox'] = {
            'exit_code': r.returncode, 'status': gate.get('status'),
            'created_count': gate.get('created_count'), 'draft_count': gate.get('draft_count'),
            'graded': len(samples), 'all_graded_correctly': graded_ok,
            'semantic_errors': gate.get('semantic_errors') or [],
            'report': str(gate_report),
        }
        report['ok'] = report['ok'] and r.returncode == 0 and graded_ok and not report['sandbox']['semantic_errors']
    text = json.dumps(report, indent=1)
    if args.report:
        Path(args.report).write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
