#!/usr/bin/env python3
"""Phase 6: independent per-question acceptance verification of a site V2
candidate against freshly extracted source evidence. Fail-closed.

Independence: this tool never imports or calls the converter. It
re-implements tokenization, rich-text flattening, option-prefix stripping,
letter-to-index answer mapping and structure comparison against the
extract's raw evidence (PDF text layer, strict two-pass region words,
phase 3 structures, re-derived phase 4 keys) and re-hashes the actual
media files. Every question must pass ALL of source, interaction,
answer-mapping and visual verification; any failure records the exact
diff and keeps the question out of the release gate evidence.

No thresholds are configurable: source coverage is 100 percent in both
directions (no missing, no extra tokens), answer keys must match the
re-derived evidence exactly, and every learner media reference must be
a question-role image that exists on disk.

Writes:
  --proof-root/<key>.source.json ... .visual.json  per-question proofs
  --evidence-out  gate-shape evidence (exactly the fields the release
                  gate accepts: source_sha256, source_question_count,
                  questions)
  --report-out    rich per-question acceptance result for review
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

WORD = re.compile(r'[a-z0-9]+')
LETTER = re.compile(r'[A-H]')
OPTION_PREFIX = re.compile(r'^[A-H][\.\):]\s*', re.I)
CHOICE_TYPES = ('single_choice', 'multiple_select', 'true_false',
                'image_based_choice')


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tokens(text):
    return set(WORD.findall((text or '').lower()))


def token_seq(text):
    return WORD.findall((text or '').lower())


def flatten_rich(value):
    """Flatten the site V2 rich-text arrays to plain text, preserving
    document order."""
    out = []

    def walk(node):
        if isinstance(node, dict):
            text = node.get('text')
            if isinstance(text, str):
                out.append(text)
            elif text is not None:
                walk(text)
            for field in ('content', 'blocks', 'rows', 'cells', 'columns'):
                child = node.get(field)
                if child is not None:
                    walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            out.append(node)

    walk(value)
    return ' '.join(out)


def learner_text(question):
    learner = question.get('learner') or {}
    parts = [flatten_rich(learner.get('stem'))]
    for choice in learner.get('choices') or []:
        parts.append(flatten_rich(choice))
    for block in learner.get('content_blocks') or []:
        if isinstance(block, dict):
            parts.append(flatten_rich(block))
    for media in learner.get('media') or []:
        if isinstance(media, dict):
            parts.append(media.get('alt') or '')
    interaction = learner.get('interaction') or {}
    matrix = interaction.get('matrix') or {}
    for row in matrix.get('rows') or []:
        parts.append(flatten_rich(row.get('text') if isinstance(row, dict)
                                  else row))
    for col in matrix.get('columns') or []:
        parts.append(flatten_rich(col.get('text') if isinstance(col, dict)
                                  else col))
    cloze = interaction.get('cloze') or {}
    for seg in cloze.get('segments') or []:
        parts.append(flatten_rich(seg.get('text') if isinstance(seg, dict)
                                  else seg))
    for blank in cloze.get('blanks') or []:
        if isinstance(blank, dict):
            for choice in blank.get('choices') or []:
                parts.append(flatten_rich(
                    choice.get('text') if isinstance(choice, dict) else choice))
    return ' '.join(p for p in parts if p)


def source_tokens(item):
    """Source basis: PDF text layer span (option prefixes stripped) or the
    stem+options fallback, plus the strict two-pass region words."""
    words = set()
    block = item.get('source_text')
    if block:
        lines = []
        for raw in str(block).replace('\r\n', '\n').replace('\r', '\n').split('\n'):
            line = OPTION_PREFIX.sub('', raw.strip()).strip()
            if line:
                lines.append(line)
        text = ' '.join(lines)
    else:
        parts = [item.get('stem') or '']
        opts = item.get('options') or {}
        for key in sorted(opts, key=lambda k: str(k).lower()):
            parts.append(opts[key] or '')
        text = ' '.join(p for p in parts if p)
    words |= tokens(text)
    for cand in item.get('source_region_candidates') or []:
        if not cand.get('usable_as_verified_source'):
            continue
        for word in cand.get('verified_words') or []:
            words |= tokens(word.get('text'))
    return words


def option_values(item):
    opts = item.get('options') or {}
    return [opts[k] or '' for k in sorted(opts, key=lambda k: str(k).lower())]


def letter_indexes(answer_raw, n_options):
    out = []
    for letter in LETTER.findall((answer_raw or '').upper()):
        idx = ord(letter) - ord('A')
        if idx >= n_options:
            return None
        out.append(idx)
    return sorted(set(out)) if out else None


def check_source(question, item, proof):
    src = source_tokens(item)
    exp = tokens(learner_text(question))
    missing = sorted(src - exp)
    extra = sorted(exp - src)
    ok = not missing and not extra
    proof.update({'source_token_count': len(src),
                  'learner_token_count': len(exp),
                  'missing_tokens': missing,
                  'extra_tokens': extra})
    return ok


def check_interaction(question, item, visual, proof):
    typ = question.get('type')
    learner = question.get('learner') or {}
    if typ in CHOICE_TYPES:
        expected = [token_seq(v) for v in option_values(item)]
        got = [token_seq(flatten_rich(c)) for c in learner.get('choices') or []]
        ok = expected == got and bool(expected)
        proof.update({'kind': 'choice_options',
                      'expected_option_count': len(expected),
                      'exported_choice_count': len(got),
                      'options_match': ok})
        if not ok:
            proof['expected_options'] = [' '.join(e) for e in expected]
            proof['exported_choices'] = [' '.join(g) for g in got]
        return ok
    if typ == 'yes_no_matrix':
        matrix = (learner.get('interaction') or {}).get('matrix') or {}
        rows = matrix.get('rows') or []
        cols = matrix.get('columns') or []
        vrows = (visual or {}).get('rows') or []
        expected = [(r.get('id'), token_seq(r.get('text') or ''))
                    for r in vrows]
        got = [(r.get('id'), token_seq(flatten_rich(r.get('text'))))
               for r in rows]
        cols = ((learner.get('interaction') or {}).get('matrix') or {}).get('columns') or []
        cols_ok = [c.get('id') for c in cols] == ['yes', 'no'] and \
            [flatten_rich(c.get('text')).strip().lower() for c in cols] == ['yes', 'no']
        ok = expected == got and cols_ok and bool(expected)
        proof.update({'kind': 'yes_no_matrix',
                      'expected_rows': [(i, ' '.join(t)) for i, t in expected],
                      'exported_rows': [(i, ' '.join(t)) for i, t in got],
                      'rows_match': expected == got,
                      'columns_yes_no': cols_ok})
        return ok
    if typ in ('inline_dropdown', 'multi_blank_dropdown'):
        blanks = (((learner.get('interaction') or {}).get('cloze') or {})
                  .get('blanks') or [])
        vblanks = (visual or {}).get('blanks') or []
        expected = [(b.get('id'), [token_seq(c['text'] if isinstance(c, dict)
                                             else c)
                                   for c in (b.get('choices') or [])])
                    for b in vblanks]
        got = [(b.get('id'), [token_seq(flatten_rich(c))
                              for c in (b.get('choices') or [])])
               for b in blanks]
        ok = expected == got and bool(expected)
        proof.update({'kind': 'dropdown_blanks',
                      'expected_blanks': len(expected),
                      'exported_blanks': len(got),
                      'blanks_match': ok})
        return ok
    proof.update({'kind': 'unsupported_for_independent_check', 'type': typ})
    return False


def check_answer_mapping(question, item, p4_fresh, p4_persisted, proof):
    typ = question.get('type')
    answer = question.get('answer') or {}
    status = answer.get('status')
    key = answer.get('answer_key')
    status_ok = (status == 'owner_key'
                 and answer.get('scoring_excluded') is not True
                 and answer.get('reviewer_needed') is not True)
    proof['answer_status_ok'] = status_ok
    if typ in CHOICE_TYPES:
        expected = letter_indexes(item.get('answer_raw'),
                                  len(option_values(item)))
        got = key if isinstance(key, list) else None
        ok = status_ok and expected is not None and got == expected
        proof.update({'kind': 'text_letters',
                      'source_answer_raw': item.get('answer_raw'),
                      'recomputed_indexes': expected,
                      'exported_answer_key': got,
                      'mapping_match': expected == got})
        return ok
    if typ == 'yes_no_matrix':
        fresh = p4_fresh.get(question.get('question_key')) or {}
        persisted = p4_persisted.get(question.get('question_key')) or {}
        fresh_key = ((fresh.get('answer_key') or {}).get('rows'))
        persisted_key = ((persisted.get('answer_key') or {}).get('rows'))
        got = key if isinstance(key, dict) else None
        fresh_ok = (fresh.get('status') == 'verified_pixel_agreed'
                    and fresh_key is not None and got == fresh_key)
        persisted_ok = (persisted.get('status') == 'verified_pixel_agreed'
                        and persisted_key is not None and got == persisted_key)
        proof.update({'kind': 'pixel_verified_matrix',
                      'fresh_phase4_status': fresh.get('status'),
                      'fresh_phase4_key': fresh_key,
                      'persisted_phase4_status': persisted.get('status'),
                      'persisted_phase4_key': persisted_key,
                      'exported_answer_key': got,
                      'fresh_evidence_match': fresh_ok,
                      'persisted_evidence_match': persisted_ok})
        return status_ok and fresh_ok and persisted_ok
    if typ in ('inline_dropdown', 'multi_blank_dropdown'):
        blanks = (((question.get('learner') or {}).get('interaction') or {})
                  .get('cloze') or {}).get('blanks') or []
        by_id = {}
        for b in blanks:
            texts = [flatten_rich(c).strip().lower()
                     for c in (b.get('choices') or [])]
            by_id[b.get('id')] = texts
        fresh = p4_fresh.get(question.get('question_key')) or {}
        slots = ((fresh.get('answer_key') or {}).get('rows') or
                 (fresh.get('answer_key') or {}).get('slots')) or {}
        got = key if isinstance(key, dict) else None
        ok = True
        detail = {}
        if not slots or got is None or set(slots) != set(got or {}):
            ok = False
        else:
            for bid, text in slots.items():
                norm = (text or '').strip().lower()
                if norm not in by_id.get(bid, []):
                    ok = False
                detail[bid] = {'evidence_choice': norm,
                               'exported': got.get(bid)}
        proof.update({'kind': 'dropdown_slots',
                      'evidence_slots': slots,
                      'exported_key': got,
                      'slot_detail': detail,
                      'mapping_match': ok,
                      'fresh_phase4_status': fresh.get('status')})
        return status_ok and ok and \
            fresh.get('status') == 'verified_pixel_agreed'
    proof.update({'kind': 'unsupported_for_independent_check', 'type': typ})
    return False


def check_visual(question, item, media_dir, proof):
    learner = question.get('learner') or {}
    media = learner.get('media') or []
    q_images = item.get('question_images') or []
    a_images = set(item.get('answer_images') or [])
    refs = []
    ok = len(media) == len(q_images)
    proof['media_count_matches_question_images'] = ok
    for entry in media:
        url = entry.get('url') or ''
        name = url.rsplit('/', 1)[-1]
        rec = {'url': url, 'file': name,
               'is_answer_image': name in a_images}
        if rec['is_answer_image']:
            ok = False
        path = Path(media_dir) / name
        if not path.is_file():
            rec['exists'] = False
            ok = False
        else:
            rec['exists'] = True
            rec['sha256'] = sha256_file(path)
        refs.append(rec)
    proof['media'] = refs
    # anchor region evidence to the actual image bytes on disk
    region_hashes = {}
    for cand in item.get('source_region_candidates') or []:
        name = cand.get('source_file')
        if name and name not in region_hashes:
            path = Path(media_dir) / name
            region_hashes[name] = (sha256_file(path)
                                   if path.is_file() else None)
    hash_ok = True
    for cand in item.get('source_region_candidates') or []:
        name = cand.get('source_file')
        claimed = cand.get('source_image_sha256')
        actual = region_hashes.get(name)
        if actual != claimed:
            hash_ok = False
    proof['region_source_image_hashes_match'] = hash_ok
    proof['region_files'] = {k: v for k, v in region_hashes.items()}
    return ok and hash_ok


def verify(candidate_path, split_path, visual_path, p4_fresh_path,
           p4_persisted_path, phase5_exit_record_path, media_dir, source_pdf,
           proof_root, evidence_out, report_out):
    candidate = json.loads(Path(candidate_path).read_text(encoding='utf-8'))
    phase5 = json.loads(Path(phase5_exit_record_path).read_text(
        encoding='utf-8'))
    summary = phase5.get('export_summary') or {}
    expected_keys = sorted(set(
        list(summary.get('verified_text_keys') or [])
        + list(summary.get('phase4_pixel_corroborated') or [])
        + list(phase5.get('exported_keys') or [])))
    expected_sha = phase5.get('candidate_v2_sha256')
    split = json.loads(Path(split_path).read_text(encoding='utf-8'))
    visual = json.loads(Path(visual_path).read_text(encoding='utf-8'))
    p4_fresh = {q.get('question_key'): q for q in (
        json.loads(Path(p4_fresh_path).read_text(encoding='utf-8'))
        .get('questions') or [])}
    p4_persisted = {q.get('question_key'): q for q in (
        json.loads(Path(p4_persisted_path).read_text(encoding='utf-8'))
        .get('questions') or [])}
    questions = candidate.get('questions') or []
    proof_root = Path(proof_root)
    proof_root.mkdir(parents=True, exist_ok=True)

    per_question = {}
    gate_questions = {}
    for question in questions:
        key = question.get('question_key')
        item = split.get(key)
        vis = visual.get(key) or {}
        record = {'question_key': key}
        if not isinstance(item, dict):
            record.update({'source_verified': False,
                           'interaction_verified': False,
                           'answer_mapping_verified': False,
                           'visual_verified': False,
                           'blocker': 'missing split item for question'})
            per_question[key] = record
            gate_questions[key] = dict(record, held=False, proof={})
            continue
        proofs = {}
        checks = {}
        for kind, fn in (
                ('source', lambda p: check_source(question, item, p)),
                ('interaction', lambda p: check_interaction(
                    question, item, vis, p)),
                ('answer_mapping', lambda p: check_answer_mapping(
                    question, item, p4_fresh, p4_persisted, p)),
                ('visual', lambda p: check_visual(
                    question, item, media_dir, p)),
        ):
            proof = {'question_key': key, 'kind': kind}
            ok = fn(proof)
            path = proof_root / ('%s.%s.json' % (key, kind.replace('_', '-')))
            path.write_text(json.dumps(proof, indent=2, sort_keys=True,
                                       ensure_ascii=False) + '\n',
                            encoding='utf-8')
            proofs[kind] = {'path': path.name, 'sha256': sha256_file(path)}
            checks[kind] = ok
        record.update({
            'source_verified': checks['source'],
            'interaction_verified': checks['interaction'],
            'answer_mapping_verified': checks['answer_mapping'],
            'visual_verified': checks['visual'],
        })
        record['blockers'] = [k for k, v in checks.items() if not v]
        per_question[key] = record
        gate_questions[key] = {
            'source_verified': checks['source'],
            'interaction_verified': checks['interaction'],
            'answer_mapping_verified': checks['answer_mapping'],
            'visual_verified': checks['visual'],
            'held': False,
            'proof': proofs,
        }

    candidate_keys = [q.get('question_key') for q in questions]
    key_set_match = (len(candidate_keys) == len(set(candidate_keys))
                     and set(candidate_keys) == set(expected_keys)
                     and len(expected_keys) == len(set(expected_keys)))
    evidence = {
        'source_sha256': sha256_file(source_pdf),
        'source_question_count': len(expected_keys),
        'questions': gate_questions,
    }
    Path(evidence_out).write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8')
    passed = sum(1 for r in per_question.values()
                 if not r.get('blockers'))
    candidate_sha = sha256_file(candidate_path)
    sha_match = (expected_sha is None or candidate_sha == expected_sha)
    report = {
        'status': 'PHASE6_ACCEPTANCE_%s' % (
            'PASS' if (passed == len(questions) and questions
                       and key_set_match and sha_match) else 'BLOCKED'),
        'questions_total': len(questions),
        'questions_all_checks_pass': passed,
        'candidate_key_set_matches_phase5': key_set_match,
        'expected_key_count': len(expected_keys),
        'candidate_sha256': candidate_sha,
        'phase5_candidate_sha256': expected_sha,
        'candidate_sha256_matches_phase5': sha_match,
        'per_question': per_question,
        'limits': [
            'Independent structural and source-token verification of the '
            'exported candidate; not a semantic review of question quality',
            'Answer verification recomputes text-letter mappings and '
            'cross-checks re-derived and persisted Phase 4 pixel evidence; '
            'it does not re-run OCR from scratch',
            'A pass is a precondition for the consolidated release gate, '
            'never publication readiness by itself',
        ],
    }
    Path(report_out).write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--split', required=True)
    parser.add_argument('--visual-draft', required=True)
    parser.add_argument('--phase4-fresh', required=True)
    parser.add_argument('--phase4-persisted', required=True)
    parser.add_argument('--phase5-exit-record', required=True,
                        help='Persisted Phase 5 exit record: the expected '
                             'exported key set and candidate sha256 the '
                             'verification attests against')
    parser.add_argument('--media-dir', required=True)
    parser.add_argument('--source-pdf', required=True)
    parser.add_argument('--proof-root', required=True)
    parser.add_argument('--evidence-out', required=True)
    parser.add_argument('--report-out', required=True)
    args = parser.parse_args(argv)
    report = verify(args.candidate, args.split, args.visual_draft,
                    args.phase4_fresh, args.phase4_persisted,
                    args.phase5_exit_record, args.media_dir,
                    args.source_pdf, args.proof_root, args.evidence_out,
                    args.report_out)
    print(json.dumps({'status': report['status'],
                      'questions_total': report['questions_total'],
                      'questions_all_checks_pass':
                          report['questions_all_checks_pass']}))
    return 0 if report['status'] == 'PHASE6_ACCEPTANCE_PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
