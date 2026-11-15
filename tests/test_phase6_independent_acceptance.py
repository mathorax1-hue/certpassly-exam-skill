"""Phase 6 independent acceptance verification: synthetic contract tests."""
import json
import tempfile
import unittest
from pathlib import Path

import scripts.phase6_independent_acceptance as P6
import scripts.phase6_tamper_fail_closed as TAMPER


def rich(text):
    return [{'type': 'paragraph', 'content': [{'text': text}]}]


def synthetic_candidate():
    return {
        'exam_code': 'SYN-1',
        'questions': [
            {
                'question_key': 'q001',
                'version': 1,
                'type': 'single_choice',
                'domain': 'synthetic',
                'learner': {
                    'stem': rich('What tool shows usage?'),
                    'choices': [rich('Portal'), rich('Explorer')],
                },
                'answer': {'answer_key': [1], 'status': 'owner_key',
                           'scoring_excluded': False,
                           'reviewer_needed': False},
            },
            {
                'question_key': 'q002',
                'version': 1,
                'type': 'yes_no_matrix',
                'domain': 'synthetic',
                'learner': {
                    'stem': rich('Select Yes if true. Otherwise select No.'),
                    'media': [{'url': '/storage/SYN-1/media/q-img.png',
                               'alt': 'Statement alpha is true'}],
                    'interaction': {'matrix': {
                        'rows': [{'id': 'r1', 'text': rich(
                            'Statement alpha is true')}],
                        'columns': [{'id': 'yes', 'text': rich('Yes')},
                                    {'id': 'no', 'text': rich('No')}],
                    }},
                },
                'answer': {'answer_key': {'r1': 'yes'},
                           'status': 'owner_key',
                           'scoring_excluded': False,
                           'reviewer_needed': False},
            },
        ],
    }


def synthetic_split():
    return {
        'q001': {
            'question_key': 'q001',
            'stem': 'What tool shows usage?',
            'source_text': 'What tool shows usage?\nA. Portal\nB. Explorer',
            'options': {'a': 'Portal', 'b': 'Explorer'},
            'answer_raw': 'B',
            'question_images': [],
            'answer_images': [],
            'source_region_candidates': [],
        },
        'q002': {
            'question_key': 'q002',
            'stem': 'Select Yes if true. Otherwise select No.',
            'source_text': 'Select Yes if true. Otherwise select No.\nA.\nB.',
            'options': {'a': '', 'b': ''},
            'answer_raw': '',
            'question_images': ['q-img.png'],
            'answer_images': ['a-img.png'],
            'source_region_candidates': [{
                'source_file': 'q-img.png',
                'source_image_sha256': 'x' * 64,
                'usable_as_verified_source': True,
                'two_pass_agreement': True,
                'verified_words': [
                    {'text': 'Statement', 'conf': 96.0},
                    {'text': 'alpha', 'conf': 95.0},
                    {'text': 'is', 'conf': 97.0},
                    {'text': 'true', 'conf': 96.0},
                ],
            }],
        },
    }


def synthetic_visual():
    return {
        'q002': {'kind': 'yes_no', 'rows': [
            {'id': 'r1', 'text': 'Statement alpha is true'}]},
    }


def synthetic_phase4():
    return {
        'status': 'X',
        'questions': [
            {'question_key': 'q002', 'status': 'verified_pixel_agreed',
             'answer_key': {'rows': {'r1': 'yes'}},
             'agreeing_methods': ['marker_box', 'checked_box']},
        ],
    }


class HelperTests(unittest.TestCase):
    def test_flatten_rich_nested(self):
        value = [{'type': 'paragraph',
                  'content': [{'text': 'one '},
                              {'text': 'two'}]}]
        self.assertEqual(P6.flatten_rich(value), 'one  two')

    def test_tokens_and_prefix_strip(self):
        item = {'source_text': 'A. Alpha beta\nB. Gamma\n',
                'options': {}}
        words = P6.source_tokens(item)
        self.assertEqual(words, {'alpha', 'beta', 'gamma'})

    def test_source_tokens_fallback_and_regions(self):
        item = {'stem': 'Stem words',
                'options': {'a': 'Opt one'},
                'source_region_candidates': [
                    {'usable_as_verified_source': True,
                     'verified_words': [{'text': 'Region'}]},
                    {'usable_as_verified_source': False,
                     'verified_words': [{'text': 'Unverified'}]},
                ]}
        self.assertEqual(P6.source_tokens(item),
                         {'stem', 'words', 'opt', 'one', 'region'})


class CheckTests(unittest.TestCase):
    def question(self, **over):
        doc = synthetic_candidate()
        question = doc['questions'][0]
        question.update(over)
        return question

    def test_source_check_pass_and_fail(self):
        item = synthetic_split()['q001']
        proof = {}
        self.assertTrue(P6.check_source(
            self.question(), item, proof))
        tampered = self.question()
        tampered['learner']['stem'] = rich('What tool shows usage invented')
        proof = {}
        self.assertFalse(P6.check_source(tampered, item, proof))
        self.assertEqual(proof['extra_tokens'], ['invented'])

    def test_interaction_choice_mismatch(self):
        item = synthetic_split()['q001']
        question = self.question()
        question['learner']['choices'] = [rich('Portal'),
                                          rich('Different')]
        proof = {}
        self.assertFalse(P6.check_interaction(question, item, {}, proof))
        self.assertEqual(proof['exported_choice_count'], 2)

    def test_interaction_unsupported_type_fails_closed(self):
        proof = {}
        self.assertFalse(P6.check_interaction(
            {'type': 'future_type', 'learner': {}}, {}, {}, proof))

    def test_answer_mapping_letters(self):
        item = synthetic_split()['q001']
        proof = {}
        self.assertTrue(P6.check_answer_mapping(
            self.question(), item, {}, {}, proof))
        self.assertEqual(proof['recomputed_indexes'], [1])
        bad = self.question()
        bad['answer']['answer_key'] = [0]
        proof = {}
        self.assertFalse(P6.check_answer_mapping(bad, item, {}, {}, proof))

    def test_answer_mapping_matrix_needs_both_evidence_sets(self):
        doc = synthetic_candidate()
        question = doc['questions'][1]
        p4 = {q['question_key']: q
              for q in synthetic_phase4()['questions']}
        proof = {}
        self.assertTrue(P6.check_answer_mapping(
            question, synthetic_split()['q002'], p4, p4, proof))
        persisted_bad = {'q002': {'status': 'candidate_single_chain',
                                  'answer_key': None}}
        proof = {}
        self.assertFalse(P6.check_answer_mapping(
            question, synthetic_split()['q002'], p4, persisted_bad, proof))

    def test_answer_status_must_be_owner_key(self):
        item = synthetic_split()['q001']
        question = self.question()
        question['answer']['status'] = 'answer_not_found'
        proof = {}
        self.assertFalse(P6.check_answer_mapping(
            question, item, {}, {}, proof))

    def test_visual_rejects_answer_image_and_missing_file(self):
        doc = synthetic_candidate()
        question = doc['questions'][1]
        item = synthetic_split()['q002']
        with tempfile.TemporaryDirectory() as t:
            media = Path(t)
            (media / 'q-img.png').write_bytes(b'question image bytes')
            proof = {}
            self.assertFalse(P6.check_visual(question, item, media, proof))
            self.assertEqual(proof['media'][0]['exists'], True)
            # the region's claimed source image hash must match the file
            self.assertFalse(proof['region_source_image_hashes_match'])
            good = json.loads(json.dumps(item))
            import hashlib
            good['source_region_candidates'][0]['source_image_sha256'] = \
                hashlib.sha256(b'question image bytes').hexdigest()
            proof = {}
            self.assertTrue(P6.check_visual(question, good, media, proof))
            leaking = json.loads(json.dumps(question))
            leaking['learner']['media'][0]['url'] = \
                '/storage/SYN-1/media/a-img.png'
            (media / 'a-img.png').write_bytes(b'answer image bytes')
            proof = {}
            self.assertFalse(P6.check_visual(leaking, item, media, proof))
            self.assertTrue(proof['media'][0]['is_answer_image'])


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)

    def fixture(self, mutate_candidate=None):
        candidate = synthetic_candidate()
        if mutate_candidate:
            mutate_candidate(candidate)
        media = self.root / 'media'
        media.mkdir(exist_ok=True)
        (media / 'q-img.png').write_bytes(b'question image bytes')
        import hashlib
        split = synthetic_split()
        split['q002']['source_region_candidates'][0][
            'source_image_sha256'] = hashlib.sha256(
                b'question image bytes').hexdigest()
        (self.root / 'split.json').write_text(json.dumps(split))
        (self.root / 'visual.json').write_text(json.dumps(synthetic_visual()))
        (self.root / 'p4.json').write_text(json.dumps(synthetic_phase4()))
        cand_path = self.root / 'candidate.json'
        cand_path.write_text(json.dumps(candidate, indent=2) + '\n')
        exit_record = {
            'export_summary': {
                'verified_text_keys': ['q001'],
                'phase4_pixel_corroborated': ['q002'],
            },
            'candidate_v2_sha256': P6.sha256_file(cand_path),
        }
        (self.root / 'phase5.json').write_text(json.dumps(exit_record))
        (self.root / 'source.pdf').write_bytes(b'synthetic immutable pdf')
        return cand_path

    def run_verify(self, cand_path):
        return P6.verify(
            cand_path, self.root / 'split.json', self.root / 'visual.json',
            self.root / 'p4.json', self.root / 'p4.json',
            self.root / 'phase5.json', self.root / 'media',
            self.root / 'source.pdf', self.root / 'proofs',
            self.root / 'evidence.json', self.root / 'report.json')

    def test_clean_candidate_passes_and_writes_proofs(self):
        report = self.run_verify(self.fixture())
        self.assertEqual(report['status'], 'PHASE6_ACCEPTANCE_PASS')
        self.assertEqual(report['questions_all_checks_pass'], 2)
        evidence = json.loads(
            (self.root / 'evidence.json').read_text())
        self.assertEqual(sorted(evidence), ['questions',
                                            'source_question_count',
                                            'source_sha256'])
        self.assertEqual(evidence['source_question_count'], 2)
        proofs = sorted(p.name for p in (self.root / 'proofs').iterdir())
        self.assertEqual(len(proofs), 8)
        self.assertTrue(all(P6.sha256_file(self.root / 'proofs' / p)
                            for p in proofs))

    def test_missing_split_item_blocks(self):
        def drop_question(candidate):
            candidate['questions'] = [
                q for q in candidate['questions']
                if q['question_key'] != 'q001']
        report = self.run_verify(self.fixture(drop_question))
        self.assertEqual(report['status'], 'PHASE6_ACCEPTANCE_BLOCKED')

    def test_stem_tamper_blocks_with_exact_diff(self):
        def tamper(candidate):
            candidate['questions'][0]['learner']['stem'] = rich(
                'What tool shows usage invented')
        report = self.run_verify(self.fixture(tamper))
        self.assertEqual(report['status'], 'PHASE6_ACCEPTANCE_BLOCKED')
        record = report['per_question']['q001']
        self.assertFalse(record['source_verified'])
        self.assertEqual(record['blockers'], ['source'])


class TamperHarnessTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)

    def test_harness_blocks_all_tampers_on_synthetic_data(self):
        candidate = synthetic_candidate()
        media = self.root / 'media'
        media.mkdir()
        (media / 'q-img.png').write_bytes(b'question image bytes')
        import hashlib
        split = synthetic_split()
        split['q002']['source_region_candidates'][0][
            'source_image_sha256'] = hashlib.sha256(
                b'question image bytes').hexdigest()
        (self.root / 'split.json').write_text(json.dumps(split))
        (self.root / 'visual.json').write_text(json.dumps(synthetic_visual()))
        (self.root / 'p4.json').write_text(json.dumps(synthetic_phase4()))
        cand_path = self.root / 'candidate.json'
        cand_path.write_text(json.dumps(candidate, indent=2) + '\n')
        (self.root / 'phase5.json').write_text(json.dumps({
            'export_summary': {'verified_text_keys': ['q001'],
                               'phase4_pixel_corroborated': ['q002']},
            'candidate_v2_sha256': P6.sha256_file(cand_path),
        }))
        (self.root / 'source.pdf').write_bytes(b'synthetic immutable pdf')
        schema = {
            '$schema': 'https://json-schema.org/draft/2020-12/schema',
            'type': 'object',
            'required': ['question_key', 'type', 'learner', 'answer'],
            'additionalProperties': False,
            'properties': {
                'question_key': {'type': 'string'},
                'version': {'type': 'integer'},
                'type': {'type': 'string'},
                'domain': {'type': 'string'},
                'learner': {'type': 'object'},
                'answer': {'type': 'object'},
            },
        }
        (self.root / 'schema.json').write_text(json.dumps(schema))
        registry = {'types': {'single_choice': {'publishable': True},
                              'yes_no_matrix': {'publishable': True},
                              'multiple_select': {'publishable': True}}}
        (self.root / 'registry.json').write_text(json.dumps(registry))
        out = self.root / 'tamper.json'
        rc = TAMPER.main([
            '--candidate', str(cand_path),
            '--split', str(self.root / 'split.json'),
            '--visual-draft', str(self.root / 'visual.json'),
            '--phase4-fresh', str(self.root / 'p4.json'),
            '--phase4-persisted', str(self.root / 'p4.json'),
            '--phase5-exit-record', str(self.root / 'phase5.json'),
            '--media-dir', str(media),
            '--source-pdf', str(self.root / 'source.pdf'),
            '--schema', str(self.root / 'schema.json'),
            '--registry', str(self.root / 'registry.json'),
            '--out', str(out),
        ])
        self.assertEqual(rc, 0)
        report = json.loads(out.read_text())
        self.assertEqual(report['status'], 'PHASE6_TAMPER_ALL_BLOCKED')
        self.assertEqual(len(report['tampers']), 7)
        for tamper in report['tampers']:
            self.assertEqual(tamper['result'], 'BLOCKED_AS_EXPECTED',
                             tamper['tamper'])


if __name__ == '__main__':
    unittest.main()
