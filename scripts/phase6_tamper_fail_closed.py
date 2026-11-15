#!/usr/bin/env python3
"""Phase 6: malformed-input fail-closed behavior test for the independent
acceptance verifier and the consolidated release gate.

Runs on real data in a private workflow (temp copies only; nothing is
written back). Each tamper mutates the candidate (or its evidence/proofs),
re-runs the Phase 6 independent acceptance verification and then the
consolidated release gate, and asserts that the pipeline BLOCKS with the
expected issue code. Any tamper that passes is a verification failure.

Every candidate mutation also changes the candidate sha256, so the
acceptance layer (which attests the candidate against the persisted
Phase 5 deliverable sha) blocks on every mutated candidate as well; each
tamper must still produce its specific gate issue code, proving both
layers fail closed independently:

  stem_tamper         -> acceptance: source_not_verified
  key_swap            -> acceptance: answer_mapping_not_verified
  answer_leak         -> gate: answer_leak
  answer_status_break -> gate: unscored_answer_not_excluded
  proof_tamper        -> gate: proof_sha256_mismatch (candidate untouched)
  count_mismatch      -> gate: source_count_mismatch
  schema_break        -> gate: schema_invalid
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase6_independent_acceptance as P6  # noqa: E402
import verify_site_v2_release_gate as GATE  # noqa: E402


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def run_pair(candidate, split, visual, p4_fresh, p4_persisted,
             phase5_exit_record, media_dir, source_pdf, schema, registry,
             work):
    """Run acceptance verification then the release gate in a temp dir."""
    cand_path = work / 'candidate.json'
    if not cand_path.is_file():
        cand_path.write_text(json.dumps(candidate, ensure_ascii=False) + '\n',
                             encoding='utf-8')
    proof_root = work / 'proofs'
    evidence_path = work / 'evidence.json'
    report_path = work / 'acceptance.json'
    acceptance = P6.verify(cand_path, split, visual, p4_fresh, p4_persisted,
                           phase5_exit_record, media_dir, source_pdf,
                           proof_root, evidence_path, report_path)
    gate = GATE.verify(cand_path, schema, registry, evidence_path,
                       source_pdf, proof_root)
    return acceptance, gate, proof_root, evidence_path


def expected_codes(gate):
    return sorted({issue.get('code') for issue in gate.get('issues') or []})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--split', required=True)
    parser.add_argument('--visual-draft', required=True)
    parser.add_argument('--phase4-fresh', required=True)
    parser.add_argument('--phase4-persisted', required=True)
    parser.add_argument('--phase5-exit-record', required=True)
    parser.add_argument('--media-dir', required=True)
    parser.add_argument('--source-pdf', required=True)
    parser.add_argument('--schema', required=True)
    parser.add_argument('--registry', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)

    candidate = load(args.candidate)
    split = Path(args.split)
    visual = Path(args.visual_draft)
    p4_fresh = Path(args.phase4_fresh)
    p4_persisted = Path(args.phase4_persisted)
    phase5_exit_record = Path(args.phase5_exit_record)
    media_dir = args.media_dir
    source_pdf = args.source_pdf
    schema = Path(args.schema)
    registry = Path(args.registry)

    def one_tamper(name, mutate, expect_acceptance_blocked,
                   expect_gate_codes, post=None):
        doc = copy.deepcopy(candidate)
        changed = mutate(doc) is not False
        with tempfile.TemporaryDirectory(prefix='phase6-tamper-') as t:
            work = Path(t)
            if not changed:
                # byte-identical candidate: only the post hook tampers
                # evidence/proofs, so the acceptance layer must pass and
                # the gate alone must catch it
                shutil.copyfile(args.candidate, work / 'candidate.json')
            acceptance, gate, proof_root, evidence_path = run_pair(
                doc, split, visual, p4_fresh, p4_persisted,
                phase5_exit_record, media_dir, source_pdf, schema, registry,
                work)
            if post is not None:
                post(proof_root, evidence_path)
                gate = GATE.verify(work / 'candidate.json', schema, registry,
                                   evidence_path, source_pdf, proof_root)
            acc_blocked = acceptance['status'] == 'PHASE6_ACCEPTANCE_BLOCKED'
            codes = expected_codes(gate)
            gate_blocked = gate.get('status') == 'BLOCKED'
            ok = (gate_blocked
                  and set(expect_gate_codes) <= set(codes)
                  and acc_blocked == expect_acceptance_blocked)
            return {
                'tamper': name,
                'acceptance_blocked': acc_blocked,
                'acceptance_status': acceptance['status'],
                'gate_blocked': gate_blocked,
                'gate_issue_codes': codes,
                'expected_gate_codes': sorted(set(expect_gate_codes)),
                'result': 'BLOCKED_AS_EXPECTED' if ok else 'FAIL_CLOSED_VIOLATION',
            }

    first_matrix = next((q for q in candidate['questions']
                         if q['type'] == 'yes_no_matrix'), None)
    first_choice = next((q for q in candidate['questions']
                         if q['type'] == 'single_choice'), None)
    results = []

    def mutate_stem(doc):
        doc['questions'][0]['learner']['stem'] = [
            {'type': 'paragraph',
             'content': [{'text': 'Totally invented stem words zzqq'}]}]

    results.append(one_tamper(
        'stem_tamper', mutate_stem, True, ['source_not_verified']))

    def mutate_key(doc):
        q = copy.deepcopy(first_matrix)
        row = sorted(q['answer']['answer_key'])[0]
        q['answer']['answer_key'][row] = ('no' if
                                          q['answer']['answer_key'][row]
                                          == 'yes' else 'yes')
        for i, question in enumerate(doc['questions']):
            if question['question_key'] == q['question_key']:
                doc['questions'][i] = q

    results.append(one_tamper(
        'key_swap', mutate_key, True, ['answer_mapping_not_verified']))

    def mutate_leak(doc):
        doc['questions'][0]['learner']['answer_key'] = [0]

    results.append(one_tamper(
        'answer_leak', mutate_leak, True, ['answer_leak']))

    def mutate_status(doc):
        q = copy.deepcopy(first_choice)
        q['answer']['status'] = 'answer_not_found'
        q['answer']['scoring_excluded'] = False
        for i, question in enumerate(doc['questions']):
            if question['question_key'] == q['question_key']:
                doc['questions'][i] = q

    results.append(one_tamper(
        'answer_status_break', mutate_status, True,
        ['unscored_answer_not_excluded', 'answer_not_release_eligible']))

    def post_proof_tamper(proof_root, evidence_path):
        proofs = sorted(Path(proof_root).glob('*.source.json'))
        proof = proofs[0]
        data = json.loads(proof.read_text(encoding='utf-8'))
        data['tampered'] = True
        proof.write_text(json.dumps(data) + '\n', encoding='utf-8')

    def mutate_nothing(doc):
        return False

    results.append(one_tamper(
        'proof_tamper', mutate_nothing, False,
        ['proof_sha256_mismatch'], post=post_proof_tamper))

    def mutate_count(doc):
        doc['questions'] = doc['questions'][:-1]

    results.append(one_tamper(
        'count_mismatch', mutate_count, True, ['source_count_mismatch']))

    def mutate_schema(doc):
        doc['questions'][0]['unexpected_extra_field'] = 'x'

    results.append(one_tamper(
        'schema_break', mutate_schema, True, ['schema_invalid']))

    all_ok = all(r['result'] == 'BLOCKED_AS_EXPECTED' for r in results)
    report = {
        'status': 'PHASE6_TAMPER_%s' % ('ALL_BLOCKED' if all_ok
                                        else 'FAIL_CLOSED_VIOLATION'),
        'tampers': results,
        'limits': [
            'Tamper tests prove fail-closed behavior on this exact '
            'candidate; they are not a proof of general security',
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n',
                   encoding='utf-8')
    print(json.dumps({'status': report['status'],
                      'tampers': [(r['tamper'], r['result'])
                                  for r in results]}))
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
