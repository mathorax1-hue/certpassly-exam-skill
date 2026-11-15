"""Phase 7 importer acceptance gate: synthetic contract tests."""
import json
import tempfile
import unittest
from pathlib import Path

import scripts.phase7_importer_acceptance as P7


def rich(text):
    return [{'type': 'paragraph', 'content': [{'text': text}]}]


def synthetic_package():
    return {
        'exam': {'vendor': 'Synthetic', 'exam_code': 'SYN-7',
                 'name': 'Synthetic 7', 'question_count': 2},
        'questions': [
            {'question_key': 'q001', 'version': 1, 'type': 'single_choice',
             'domain': 'd1',
             'learner': {'stem': rich('Pick one.'),
                         'choices': [rich('A'), rich('B')]},
             'answer': {'answer_key': [0], 'status': 'owner_key',
                        'scoring_excluded': False,
                        'reviewer_needed': False}},
            {'question_key': 'q002', 'version': 1, 'type': 'yes_no_matrix',
             'domain': 'd1',
             'learner': {'stem': rich('Yes or no.'),
                         'media': [{'url': '/storage/SYN-7/media/i.png',
                                    'alt': 'Alpha statement'}],
                         'interaction': {'matrix': {
                             'rows': [{'id': 'r1', 'text': rich(
                                 'Alpha statement')}],
                             'columns': [{'id': 'yes', 'text': rich('Yes')},
                                         {'id': 'no', 'text': rich('No')}]}}},
             'answer': {'answer_key': {'r1': 'yes'}, 'status': 'owner_key',
                        'scoring_excluded': False,
                        'reviewer_needed': False}},
        ],
    }


def synthetic_receipt(package_sha, schema_sha):
    return {
        'importer': {
            'identity': 'certpassly-web-importer 1.4.2',
            'source': 'https://github.com/certpassly/website (inspected)',
            'inspected': True,
            'import_format_version': '2',
            'content_schema_sha256': schema_sha,
            'staging_environment': 'https://staging.certpassly.com',
        },
        'run': {
            'mode': 'staging_dry_run',
            'site_url': 'https://staging.certpassly.com/admin/import',
            'release_id': 'rel-syn-7-001',
        },
        'package': {
            'sha256': package_sha,
            'question_count': 2,
            'type_counts': {'single_choice': 1, 'yes_no_matrix': 1},
            'media_count': 1,
            'answer_count': 2,
        },
        'questions': {
            'q001': {
                'rendered_type': 'single_choice',
                'relations_ok': True,
                'media_loaded': True,
                'answer_hidden_before_submission': True,
                'answer_exposure_probes': ['frontend_payload',
                                           'api_response'],
                'scored_correct_key_matches': True,
                'functional_modes': {m: True for m in
                                     ('study', 'timed', 'resume', 'retry',
                                      'review')},
                'accessibility': {c: True for c in
                                  ('keyboard', 'screen_reader', 'mobile',
                                   'wcag_2_2_aa')},
            },
            'q002': {
                'rendered_type': 'yes_no_matrix',
                'relations_ok': True,
                'media_loaded': True,
                'answer_hidden_before_submission': True,
                'answer_exposure_probes': ['frontend_payload',
                                           'api_response'],
                'scored_correct_key_matches': True,
                'functional_modes': {m: True for m in
                                     ('study', 'timed', 'resume', 'retry',
                                      'review')},
                'accessibility': {c: True for c in
                                  ('keyboard', 'screen_reader', 'mobile',
                                   'wcag_2_2_aa')},
            },
        },
        'functional': {c: True for c in (
            'timer', 'navigator', 'review', 'practice_feedback',
            'exam_feedback', 'timeout', 'partial_credit', 'trial_limits',
            'access_policy', 'encrypted_answer_isolation')},
        'publish': {
            'atomic_publish_rollback': True,
            'content_version': 'syn-7/v1',
            'reviewer_identity': 'Jane Reviewer',
            'reviewer_decision': 'approved_staging',
            'package_sha256': package_sha,
        },
        'content_audit': {c: True for c in (
            'no_owner_pdf_exposed', 'no_raw_extracts_exposed',
            'no_secrets_exposed', 'only_authorized_content')},
        'evidence_files': [
            {'path': 'import-log.txt', 'sha256': None},
            {'path': 'screenshots/q001.png', 'sha256': None},
        ],
    }


class ImporterAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.pkg_path = self.root / 'package.json'
        self.pkg_path.write_text(json.dumps(synthetic_package(), indent=2)
                                 + '\n', encoding='utf-8')
        self.schema_path = self.root / 'schema.json'
        self.schema_path.write_text('{"type": "object"}\n',
                                    encoding='utf-8')
        self.evidence = self.root / 'evidence'
        (self.evidence / 'screenshots').mkdir(parents=True)
        (self.evidence / 'import-log.txt').write_text('import log\n',
                                                      encoding='utf-8')
        (self.evidence / 'screenshots' / 'q001.png').write_bytes(
            b'png bytes')
        import hashlib
        self.hashes = {
            'import-log.txt': hashlib.sha256(b'import log\n').hexdigest(),
            'screenshots/q001.png': hashlib.sha256(b'png bytes').hexdigest(),
        }

    def receipt_path(self, mutate=None, fill_evidence=True):
        import hashlib
        receipt = synthetic_receipt(
            P7.sha256_file(self.pkg_path),
            P7.sha256_file(self.schema_path))
        if fill_evidence:
            for entry in receipt['evidence_files']:
                entry['sha256'] = self.hashes[entry['path']]
        if mutate:
            mutate(receipt)
        path = self.root / 'receipt.json'
        path.write_text(json.dumps(receipt, indent=2) + '\n',
                        encoding='utf-8')
        return path

    def run_verify(self, receipt_path):
        report = P7.verify(self.pkg_path, self.schema_path, receipt_path,
                           self.evidence, self.root / 'report.json')
        return report

    def test_missing_receipt_blocks(self):
        report = self.run_verify(None)
        self.assertEqual(report['status'],
                         'PHASE7_IMPORTER_ACCEPTANCE_BLOCKED')
        codes = {i['code'] for i in report['issues']}
        self.assertIn('missing_import_receipt', codes)
        self.assertFalse(report['receipt_present'])

    def test_complete_receipt_passes(self):
        report = self.run_verify(self.receipt_path())
        self.assertEqual(report['status'], 'PHASE7_IMPORTER_ACCEPTANCE_PASS',
                         report['issues'])
        self.assertEqual(report['package_facts']['question_count'], 2)
        self.assertEqual(report['package_facts']['media_count'], 1)

    def test_fabricated_package_sha_blocks(self):
        def mutate(receipt):
            receipt['package']['sha256'] = 'f' * 64
        report = self.run_verify(self.receipt_path(mutate))
        codes = {i['code'] for i in report['issues']}
        self.assertIn('package_sha_mismatch', codes)

    def test_count_lie_blocks(self):
        def mutate(receipt):
            receipt['package']['question_count'] = 3
        report = self.run_verify(self.receipt_path(mutate))
        codes = {i['code'] for i in report['issues']}
        self.assertIn('question_count_mismatch', codes)

    def test_production_publish_claim_blocks(self):
        def mutate(receipt):
            receipt['run']['mode'] = 'production_publish'
        report = self.run_verify(self.receipt_path(mutate))
        codes = {i['code'] for i in report['issues']}
        self.assertIn('run_mode_not_staging_dry_run', codes)

    def test_answer_exposure_blocks(self):
        def mutate(receipt):
            receipt['questions']['q001'][
                'answer_hidden_before_submission'] = False
        report = self.run_verify(self.receipt_path(mutate))
        codes = {i['code'] for i in report['issues']}
        self.assertIn('question_flag_failed', codes)

    def test_missing_api_probe_blocks(self):
        def mutate(receipt):
            receipt['questions']['q002']['answer_exposure_probes'] = \
                ['frontend_payload']
        report = self.run_verify(self.receipt_path(mutate))
        codes = {i['code'] for i in report['issues']}
        self.assertIn('answer_exposure_probes_missing', codes)

    def test_accessibility_gap_blocks(self):
        def mutate(receipt):
            del receipt['questions']['q001']['accessibility']['wcag_2_2_aa']
        report = self.run_verify(self.receipt_path(mutate))
        codes = {i['code'] for i in report['issues']}
        self.assertIn('accessibility_check_failed', codes)

    def test_automated_reviewer_blocks(self):
        def mutate(receipt):
            receipt['publish']['reviewer_identity'] = 'AI Reviewer Bot'
        report = self.run_verify(self.receipt_path(mutate))
        codes = {i['code'] for i in report['issues']}
        self.assertIn('reviewer_not_human', codes)

    def test_uninspected_importer_blocks(self):
        def mutate(receipt):
            receipt['importer']['inspected'] = False
        report = self.run_verify(self.receipt_path(mutate))
        codes = {i['code'] for i in report['issues']}
        self.assertIn('importer_not_inspected', codes)

    def test_schema_mismatch_blocks(self):
        def mutate(receipt):
            receipt['importer']['content_schema_sha256'] = 'a' * 64
        report = self.run_verify(self.receipt_path(mutate))
        codes = {i['code'] for i in report['issues']}
        self.assertIn('schema_sha_mismatch', codes)

    def test_tampered_evidence_blocks(self):
        def mutate(receipt):
            receipt['evidence_files'][0]['sha256'] = '0' * 64
        report = self.run_verify(self.receipt_path(mutate))
        codes = {i['code'] for i in report['issues']}
        self.assertIn('evidence_sha_mismatch', codes)

    def test_missing_evidence_file_blocks(self):
        def mutate(receipt):
            receipt['evidence_files'].append(
                {'path': 'screenshots/q999.png', 'sha256': 'b' * 64})
        report = self.run_verify(self.receipt_path(mutate))
        codes = {i['code'] for i in report['issues']}
        self.assertIn('evidence_file_missing', codes)

    def test_unknown_section_blocks(self):
        def mutate(receipt):
            receipt['extra_section'] = {}
        report = self.run_verify(self.receipt_path(mutate))
        codes = {i['code'] for i in report['issues']}
        self.assertIn('receipt_unknown_sections', codes)

    def test_functional_gap_blocks(self):
        def mutate(receipt):
            receipt['functional']['timeout'] = False
        report = self.run_verify(self.receipt_path(mutate))
        codes = {i['code'] for i in report['issues']}
        self.assertIn('functional_check_failed', codes)


if __name__ == '__main__':
    unittest.main()
