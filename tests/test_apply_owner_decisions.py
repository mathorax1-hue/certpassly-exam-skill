#!/usr/bin/env python3
"""Contract tests for apply_owner_decisions.py (synthetic only).

Covers: file-level validation (version, exam, identity, date); row/blank/
option id validation against the real structures; complete-key rule;
partial decisions rejected and never becoming confirmations; override of
a machine-verified key rejected outside editorial_conflicts; editorial
retain/override/retire semantics incl. required evidence and both values
preserved; provenance + decision-file SHA256; exit codes. All fixtures
are synthetic: no images, no private content.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'scripts'))

import apply_owner_decisions as AOD  # noqa: E402

PY = sys.executable
SCRIPT = str(HERE.parent / 'scripts' / 'apply_owner_decisions.py')


def matrix_hold():
    return {
        'question_key': 'qM1',
        'native_structure': {
            'type': 'yes_no_matrix',
            'interaction': {'matrix': {'rows': [
                {'id': 'r1', 'text': []},
                {'id': 'r2', 'text': []},
                {'id': 'r3', 'text': []}]}},
        },
    }


def dropdown_hold():
    return {
        'question_key': 'qD1',
        'native_structure': {
            'type': 'inline_dropdown',
            'interaction': {'cloze': {
                'segments': [{'text': 'seg '}],
                'blanks': [{'id': 'blank1', 'options': [
                    {'id': 'blank1_o1', 'text': 'Alpha.'},
                    {'id': 'blank1_o2', 'text': 'Beta.'}]}]}},
        },
    }


def phase4_evidence():
    return {'questions': [
        {'question_key': 'qM1', 'status': 'blocked_marks_not_mappable',
         'answer_key': None},
        {'question_key': 'qD1', 'status': 'candidate_single_chain',
         'answer_key': None},
        {'question_key': 'qE1', 'status': 'verified_text',
         'answer_key': {'correct_option_ids': ['a']}},
    ]}


def candidate():
    return {'questions': [{
        'question_key': 'qE1', 'type': 'single_choice',
        'learner': {'stem': [], 'choices': [
            [{'type': 'paragraph',
              'content': [{'text': 'opt A'}]}],
            [{'type': 'paragraph',
              'content': [{'text': 'opt B'}]}]]},
        'answer': {'answer_key': [0]},
    }]}


def conflicts_file():
    return {'items': [{
        'question_key': 'qE1',
        'owner_source_selection': 'A - opt A',
        'concern': 'synthetic concern',
        'official_url': 'https://example.com/doc',
        'status': 'blocked', 'human_approved': False,
    }]}


def decisions(doc):
    d = {'decision_version': 1, 'exam': 'AB-900',
         'decided_by': 'Test Owner', 'decided_date': '2026-11-16',
         'source': 'test', 'engineering_decisions': {},
         'editorial_conflicts': {}, 'questions': {}}
    d.update(doc)
    return d


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_apply(self, dec, *, p4=None, held=None, cand=None,
                  conflicts=None, exam='AB-900'):
        dp = self.dir / 'dec.json'
        dp.write_text(json.dumps(dec))
        p4p = self.dir / 'p4.json'
        p4p.write_text(json.dumps(p4 or phase4_evidence()))
        args = [PY, SCRIPT, '--decisions', str(dp), '--phase4',
                str(p4p), '--exam', exam,
                '--output', str(self.dir / 'out.json')]
        if held is not None:
            hp = self.dir / 'held.json'
            hp.write_text(json.dumps(held))
            args += ['--held', str(hp)]
        if cand is not None:
            cp = self.dir / 'cand.json'
            cp.write_text(json.dumps(cand))
            args += ['--candidate', str(cp)]
        if conflicts is not None:
            cf = self.dir / 'conf.json'
            cf.write_text(json.dumps(conflicts))
            args += ['--conflicts', str(cf)]
        proc = subprocess.run(args, capture_output=True, text=True)
        out = None
        op = self.dir / 'out.json'
        if op.exists():
            out = json.loads(op.read_text())
        return proc.returncode, out, proc.stdout

    def test_valid_matrix_confirmation(self):
        dec = decisions({'questions': {'qM1': {
            'decision': 'confirm_key',
            'key': {'r1': 'yes', 'r2': 'no', 'r3': 'yes'},
            'text': {'r1': 's1', 'r2': 's2', 'r3': 's3'}}}})
        rc, out, _ = self.run_apply(
            dec, held=[matrix_hold(), dropdown_hold()])
        self.assertEqual(rc, 0)
        self.assertEqual(out['counts']['owner_confirmed'], 1)
        q = out['questions']['qM1']
        self.assertEqual(q['status'], 'owner_confirmed')
        self.assertFalse(q['stays_held'])
        self.assertEqual(q['answer_key']['rows']['r2'], 'no')
        self.assertTrue(q['text_complete'])
        self.assertEqual(out['provenance']['decided_by'], 'Test Owner')

    def test_valid_dropdown_confirmation(self):
        dec = decisions({'questions': {'qD1': {
            'decision': 'confirm_key', 'key': {'blank1': 'blank1_o2'},
            'text': {'blank1_options': 'Alpha.\nBeta.'}}}})
        rc, out, _ = self.run_apply(
            dec, held=[matrix_hold(), dropdown_hold()])
        self.assertEqual(rc, 0)
        q = out['questions']['qD1']
        self.assertEqual(q['status'], 'owner_confirmed')
        self.assertEqual(q['answer_key']['blanks']['blank1'],
                         'blank1_o2')
        self.assertTrue(q['text_complete'])

    def test_file_level_rejections(self):
        for bad in [
            {'decision_version': 2},
            {'exam': 'XX-1'},
            {'decided_by': ''},
            {'decided_date': '16/11/2026'},
        ]:
            dec = decisions({})
            dec.update(bad)
            rc, out, _ = self.run_apply(
                dec, held=[matrix_hold(), dropdown_hold()])
            self.assertEqual(rc, 1, bad)
            self.assertIsNone(out, bad)

    def test_unknown_question_and_bad_ids(self):
        dec = decisions({'questions': {
            'qZZ': {'decision': 'confirm_key', 'key': {}},
            'qM1': {'decision': 'confirm_key',
                    'key': {'r1': 'yes', 'rx': 'no', 'r3': 'yes'}},
            'qD1': {'decision': 'confirm_key',
                    'key': {'blank1': 'blank1_oX'}},
        }})
        rc, out, _ = self.run_apply(
            dec, held=[matrix_hold(), dropdown_hold()])
        self.assertEqual(rc, 1)
        self.assertEqual(len(out['rejections']), 3)
        self.assertEqual(out['questions'].get('qZZ'),
                         out['questions'].get('qZZ'))  # absent
        self.assertNotIn('qZZ', out['questions'])
        self.assertNotIn('qM1', out['questions'])
        self.assertNotIn('qD1', out['questions'])
        self.assertEqual(out['status'],
                         'PHASE4_OWNER_DECIDED_WITH_REJECTIONS')

    def test_partial_key_never_confirms(self):
        dec = decisions({'questions': {'qM1': {
            'decision': 'partial_key',
            'key': {'r1': 'yes'}}}})
        rc, out, _ = self.run_apply(
            dec, held=[matrix_hold(), dropdown_hold()])
        self.assertEqual(rc, 1)
        self.assertEqual(out['counts']['owner_confirmed'], 0)
        self.assertIn('partial', json.dumps(out['rejections']))

    def test_verified_key_override_rejected_outside_editorial(self):
        dec = decisions({'questions': {'qE1': {
            'decision': 'confirm_key',
            'key': {'correct_option_ids': ['b']}}}})
        rc, out, _ = self.run_apply(
            dec, held=[matrix_hold(), dropdown_hold()],
            cand=candidate())
        self.assertEqual(rc, 1)
        self.assertIn('editorial_conflicts',
                      json.dumps(out['rejections']))

    def test_editorial_override_requires_evidence(self):
        dec = decisions({'editorial_conflicts': {'qE1': {
            'decision': 'override', 'override_to': [1], 'note': ''}}})
        rc, out, _ = self.run_apply(
            dec, held=[], cand=candidate(), conflicts=conflicts_file())
        self.assertEqual(rc, 1)
        self.assertIn('explicit evidence',
                      json.dumps(out['rejections']))
        self.assertEqual(out['editorial_conflicts']['qE1']['status'],
                         'no_decision')

    def test_editorial_override_preserves_both_values(self):
        dec = decisions({'editorial_conflicts': {'qE1': {
            'decision': 'override', 'override_to': [1],
            'note': 'current doc says opt B'}}})
        rc, out, _ = self.run_apply(
            dec, held=[], cand=candidate(), conflicts=conflicts_file())
        self.assertEqual(rc, 0)
        ec = out['editorial_conflicts']['qE1']
        self.assertEqual(ec['status'], 'owner_overridden')
        self.assertEqual(ec['previous_key'], {'correct_option_ids':
                                              ['a']})
        self.assertEqual(ec['override_to'], [1])
        self.assertEqual(ec['evidence'], 'current doc says opt B')
        self.assertEqual(ec['owner_source_selection'], 'A - opt A')

    def test_editorial_override_invalid_option(self):
        dec = decisions({'editorial_conflicts': {'qE1': {
            'decision': 'override', 'override_to': [7],
            'note': 'x'}}})
        rc, out, _ = self.run_apply(
            dec, held=[], cand=candidate(), conflicts=conflicts_file())
        self.assertEqual(rc, 1)
        self.assertIn('structure/options',
                      json.dumps(out['rejections']))

    def test_editorial_retain_and_retire(self):
        dec = decisions({'editorial_conflicts': {
            'qE1': {'decision': 'retain', 'override_to': None,
                    'note': None}}})
        rc, out, _ = self.run_apply(
            dec, held=[], cand=candidate(), conflicts=conflicts_file())
        self.assertEqual(rc, 0)
        self.assertEqual(out['editorial_conflicts']['qE1']['status'],
                         'owner_retained')
        dec2 = decisions({'editorial_conflicts': {
            'qE1': {'decision': 'retire'}}})
        rc2, out2, _ = self.run_apply(
            dec2, held=[], cand=candidate(), conflicts=conflicts_file())
        self.assertEqual(rc2, 0)
        self.assertEqual(
            out2['editorial_conflicts']['qE1']['status'],
            'owner_retired')

    def test_editorial_unknown_key_rejected(self):
        dec = decisions({'editorial_conflicts': {'qZZ': {
            'decision': 'retain'}}})
        rc, out, _ = self.run_apply(
            dec, held=[], cand=candidate(), conflicts=conflicts_file())
        self.assertEqual(rc, 1)
        self.assertIn('not in the conflicts review file',
                      json.dumps(out['rejections']))

    def test_text_only_complete_and_incomplete(self):
        dec = decisions({'questions': {'qM1': {
            'decision': 'text_only',
            'text': {'r1': 's1', 'r2': 's2'}}}})
        rc, out, _ = self.run_apply(
            dec, held=[matrix_hold(), dropdown_hold()])
        self.assertEqual(rc, 1)
        self.assertEqual(out['counts']['owner_text_confirmed'], 0)
        dec2 = decisions({'questions': {'qM1': {
            'decision': 'text_only',
            'text': {'r1': 's1', 'r2': 's2', 'r3': 's3'}}}})
        rc2, out2, _ = self.run_apply(
            dec2, held=[matrix_hold(), dropdown_hold()])
        self.assertEqual(rc2, 0)
        self.assertEqual(out2['counts']['owner_text_confirmed'], 1)
        self.assertFalse(
            out2['questions']['qM1']['stays_held'])

    def test_structure_provided(self):
        dec = decisions({'questions': {'qS1': {
            'decision': 'structure_provided',
            'structure': json.dumps({
                'type': 'yes_no_matrix',
                'rows': ['a', 'b'],
                'key': {'a': 'yes', 'b': 'no'}})}}})
        p4 = {'questions': [{'question_key': 'qS1',
                             'status': 'blocked_no_structure',
                             'answer_key': None}]}
        rc, out, _ = self.run_apply(dec, held=[], p4=p4)
        self.assertEqual(rc, 0)
        self.assertEqual(out['questions']['qS1']['status'],
                         'owner_structure_provided')
        dec2 = decisions({'questions': {'qS1': {
            'decision': 'structure_provided',
            'structure': 'not json'}}})
        rc2, out2, _ = self.run_apply(dec2, held=[], p4=p4)
        self.assertEqual(rc2, 1)
        self.assertIn('type+key', json.dumps(out2['rejections']))

    def test_provenance_sha256(self):
        dec = decisions({})
        rc, out, _ = self.run_apply(
            dec, held=[matrix_hold(), dropdown_hold()])
        self.assertEqual(rc, 0)
        sha = out['provenance']['decision_file_sha256']
        self.assertEqual(len(sha), 64)
        self.assertIn('standalone_note', out)
        self.assertIn('NOT', out['standalone_note'])

    def test_untouched_all_no_decision(self):
        dec = decisions({'questions': {'qM1': {
            'decision': 'no_decision'}}})
        rc, out, _ = self.run_apply(
            dec, held=[matrix_hold(), dropdown_hold()])
        self.assertEqual(rc, 0)
        self.assertEqual(out['counts']['owner_confirmed'], 0)
        self.assertEqual(out['questions']['qM1']['status'],
                         'no_decision')
        self.assertTrue(out['questions']['qM1']['stays_held'])


if __name__ == '__main__':
    unittest.main()
