"""Phase 5 answer-evidence integration: fail-closed synthetic contract tests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.phase5_export_evidence import (
    load_phase4_evidence, verified_ocr_item,
    matrix_key_from_phase4, dropdown_key_from_phase4,
)
from scripts.patch_phase5_upstream_answer_evidence import (
    EXPORT_IMPORT_ANCHOR, EXPORT_HEAD_ANCHOR, EXPORT_HOLD_ANCHOR,
    EXPORT_MATRIX_ANCHOR, EXPORT_DROPDOWN_ANCHOR, EXPORT_RECORD_ANCHOR,
    FIDELITY_ANCHOR, patch as patch_upstream,
)


def region(fname, text, words, strict=True, bbox=(0, 0, 100, 30)):
    return {
        'source_file': fname, 'kind': 'matrix_statement_column_text_band',
        'bbox_pixels': list(bbox), 'source_dimensions': [1000, 300],
        'ocr_text_candidate': text, 'verified_words': words if strict else [],
        'two_pass_agreement': strict, 'confidence_pass': strict,
        'usable_as_verified_source': strict,
        'passes': [
            {'id': 'psm3', 'min_confidence': 91.0, 'mean_confidence': 96.0,
             'word_count': len(words)},
            {'id': 'psm6', 'min_confidence': 92.0, 'mean_confidence': 97.0,
             'word_count': len(words)},
        ],
    }


def raw_image(fname, role='question', minc=44.8):
    return {'file': fname, 'role': role, 'words': [
        {'text': 'clean', 'conf': 97.0}, {'text': 'noise', 'conf': minc}],
        'lines': [], 'mean_confidence': 80.0, 'min_confidence': minc,
        'passes': {'psm3': {'text': 'clean noise'}, 'psm6': {'text': 'other'}},
        'agree': False}


class VerifiedOcrItemTests(unittest.TestCase):
    def test_no_images_unchanged(self):
        item = {'source_region_candidates': []}
        ocr = {'images': [], 'agree': True, 'confidence': 99.0}
        out, meta = verified_ocr_item(item, ocr)
        self.assertIs(out, ocr)
        self.assertEqual(meta, {'mode': 'no_images'})

    def test_strict_question_image_becomes_verified_record(self):
        item = {'source_region_candidates': [
            region('q.png', 'Verified source words',
                   [{'text': 'Verified', 'conf': 96.0},
                    {'text': 'source', 'conf': 95.0},
                    {'text': 'words', 'conf': 94.0}])]}
        ocr = {'images': [raw_image('q.png')], 'agree': False,
               'confidence': 93.6, 'min_confidence': 44.8}
        out, meta = verified_ocr_item(item, ocr)
        self.assertEqual(meta['verified_files'], ['q.png'])
        im = out['images'][0]
        self.assertEqual([w['text'] for w in im['words']],
                         ['Verified', 'source', 'words'])
        self.assertTrue(im['agree'])
        # both passes carry the agreed region text: the unchanged
        # pass-agreement rule now sees agreeing evidence
        self.assertEqual(im['passes']['psm3']['text'],
                         im['passes']['psm6']['text'])
        self.assertEqual(im['min_confidence'], 91.0)
        self.assertTrue(out['agree'])
        self.assertEqual(out['min_confidence'], 91.0)

    def test_question_image_without_strict_regions_keeps_raw_record(self):
        item = {'source_region_candidates': [
            region('q.png', 'not strict', [], strict=False)]}
        ocr = {'images': [raw_image('q.png')], 'agree': False,
               'confidence': 93.6}
        out, meta = verified_ocr_item(item, ocr)
        self.assertEqual(meta['raw_files'], ['q.png'])
        self.assertEqual(meta['verified_files'], [])
        self.assertIs(out['images'][0], ocr['images'][0])
        self.assertFalse(out['agree'])

    def test_answer_role_images_are_excluded_from_learner_gate(self):
        item = {'source_region_candidates': [
            region('q.png', 'Verified words', [{'text': 'Verified', 'conf': 96.0}])]}
        ocr = {'images': [raw_image('q.png'), raw_image('a.png', role='answer')],
               'agree': False, 'confidence': 93.6}
        out, meta = verified_ocr_item(item, ocr)
        self.assertEqual(meta['excluded_answer_files'], ['a.png'])
        self.assertEqual([im['file'] for im in out['images']], ['q.png'])

    def test_all_answer_images_never_bypass_the_gate(self):
        item = {'source_region_candidates': []}
        ocr = {'images': [raw_image('a.png', role='answer')],
               'agree': False, 'confidence': 50.0}
        out, meta = verified_ocr_item(item, ocr)
        self.assertIs(out, ocr)
        self.assertEqual(meta['excluded_answer_files'], ['a.png'])

    def test_mixed_verified_and_raw_keeps_raw_item_flags(self):
        item = {'source_region_candidates': [
            region('q1.png', 'Verified', [{'text': 'Verified', 'conf': 96.0}])]}
        ocr = {'images': [raw_image('q1.png'), raw_image('q2.png', minc=40.0)],
               'agree': False, 'confidence': 93.6}
        out, meta = verified_ocr_item(item, ocr)
        self.assertEqual(meta['verified_files'], ['q1.png'])
        self.assertEqual(meta['raw_files'], ['q2.png'])
        self.assertFalse(out['agree'])
        self.assertEqual(out['confidence'], 93.6)


def matrix_visual(rows):
    return {'kind': 'yes_no', 'rows': [
        {'id': 'r%d' % (i + 1), 'text': t} for i, t in enumerate(rows)]}


def verified_matrix_record(rows_key, methods=('marker_box', 'checked_box')):
    return {
        'status': 'verified_pixel_agreed',
        'structure_kind': 'yes_no_matrix',
        'answer_key': {'rows': rows_key},
        'agreeing_methods': list(methods),
    }


class MatrixKeyTests(unittest.TestCase):
    def item(self, visual):
        return {'question_key': 'qX', 'question_images': ['q.png'],
                'answer_images': ['a.png'], 'source_region_candidates': [],
                'options': {}}

    def test_verified_key_applies_when_structure_matches(self):
        visual = matrix_visual(['Statement one', 'Statement two'])
        item = self.item(visual)
        record = verified_matrix_record({'r1': 'yes', 'r2': 'no'})
        out = matrix_key_from_phase4(item, visual, record)
        self.assertEqual(out['key'], {'r1': 'yes', 'r2': 'no'})
        self.assertEqual(sorted(out['methods']),
                         ['checked_box', 'marker_box'])

    def test_structure_mismatch_never_applies(self):
        visual = matrix_visual(['Alpha beta gamma', 'Statement two'])
        item = self.item(visual)
        record = verified_matrix_record({'r1': 'yes', 'r2': 'no'})
        with patch('scripts.phase5_export_evidence.P4.structure_of',
                   return_value={'kind': 'yes_no_matrix', 'rows': [
                       {'id': 'r1', 'text': 'Delta epsilon zeta'},
                       {'id': 'r2', 'text': 'Statement two'}]}):
            self.assertIsNone(
                matrix_key_from_phase4(item, visual, record))

    def test_ocr_variant_text_still_corresponds(self):
        """One OCR misread (Purvie vs Purview) must not block the key:
        the Phase 4 verifier used the same fuzzy correspondence."""
        visual = matrix_visual(['Copilot honors Microsoft Purvie'])
        item = self.item(visual)
        record = verified_matrix_record({'r1': 'yes'})
        with patch('scripts.phase5_export_evidence.P4.structure_of',
                   return_value={'kind': 'yes_no_matrix', 'rows': [
                       {'id': 'r1',
                        'text': 'Copilot honors Microsoft Purview'}]}):
            out = matrix_key_from_phase4(item, visual, record)
            self.assertEqual(out['key'], {'r1': 'yes'})

    def test_incomplete_key_coverage_never_applies(self):
        visual = matrix_visual(['Statement one', 'Statement two'])
        record = verified_matrix_record({'r1': 'yes'})
        self.assertIsNone(
            matrix_key_from_phase4(self.item(visual), visual, record))

    def test_candidate_single_chain_never_applies(self):
        visual = matrix_visual(['Statement one'])
        record = {'status': 'candidate_single_chain',
                  'structure_kind': 'yes_no_matrix',
                  'answer_key': None, 'agreeing_methods': []}
        self.assertIsNone(
            matrix_key_from_phase4(self.item(visual), visual, record))

    def test_blocked_record_never_applies(self):
        visual = matrix_visual(['Statement one'])
        record = {'status': 'blocked_contradictory_marks',
                  'structure_kind': 'yes_no_matrix'}
        self.assertIsNone(
            matrix_key_from_phase4(self.item(visual), visual, record))

    def test_single_method_never_applies(self):
        visual = matrix_visual(['Statement one'])
        record = verified_matrix_record(
            {'r1': 'yes'}, methods=('marker_box',))
        self.assertIsNone(
            matrix_key_from_phase4(self.item(visual), visual, record))


class DropdownKeyTests(unittest.TestCase):
    def visual(self):
        return {'kind': 'dropdown', 'blanks': [
            {'id': 'blank1', 'choices': [
                {'text': 'First option', 'strict': True},
                {'text': 'Second option', 'strict': True}]}]}

    def item(self):
        return {'question_key': 'qY', 'question_images': ['q.png'],
                'answer_images': ['a.png'], 'source_region_candidates': [],
                'options': {}}

    def record(self, slots):
        return {'status': 'verified_pixel_agreed',
                'structure_kind': 'inline_dropdown',
                'answer_key': {'slots': slots},
                'agreeing_methods': ['marker_box', 'checked_box']}

    def test_verified_slots_apply(self):
        out = dropdown_key_from_phase4(
            self.item(), self.visual(), self.record({'blank1': 'Second option'}))
        self.assertEqual(out['key'], {'blank1': 'Second option'})

    def test_slot_text_outside_choices_never_applies(self):
        self.assertIsNone(dropdown_key_from_phase4(
            self.item(), self.visual(), self.record({'blank1': 'Third option'})))

    def test_wrong_structure_kind_never_applies(self):
        record = self.record({'blank1': 'Second option'})
        record['structure_kind'] = 'yes_no_matrix'
        self.assertIsNone(dropdown_key_from_phase4(
            self.item(), self.visual(), record))


class LoadEvidenceTests(unittest.TestCase):
    def test_load_keyed_by_question(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'evidence.json'
            p.write_text(json.dumps({'status': 'X', 'questions': [
                {'question_key': 'q001', 'status': 'verified_text'},
                {'question_key': 'q002',
                 'status': 'verified_pixel_agreed'}]}))
            records = load_phase4_evidence(str(p))
            self.assertEqual(sorted(records), ['q001', 'q002'])
        self.assertEqual(load_phase4_evidence(None), {})
        self.assertEqual(load_phase4_evidence(''), {})


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        root = Path(self.t.name)
        (root / 'pipeline/scripts').mkdir(parents=True)
        (root / 'skill').mkdir()
        self.root = root

    def mini_upstream(self):
        export = self.root / 'pipeline/scripts/build_technical_export.py'
        export.write_text('\n'.join([
            EXPORT_IMPORT_ANCHOR,
            "def export_one(item, visual, ocr_item, exam_code, domain, min_conf, fid_cfg=None, deny=None):",
            EXPORT_HEAD_ANCHOR.split('\n', 1)[1],
            "    hold = {",
            "        'question_key': item.get('question_key'),",
            "        'reason': result['reason'],",
            "        'ocr_confidence': (ocr_item or {}).get('confidence'),",
            "        'ocr_min_confidence': (ocr_item or {}).get('min_confidence'),",
            "        'rule_id': result.get('rule_id'),",
            "        'markers': result.get('markers') or [],",
            "        'suggested_type': result.get('type'),",
            "        'matched_rules': result.get('matched_rules') or [],",
            "    }",
            EXPORT_MATRIX_ANCHOR,
            EXPORT_DROPDOWN_ANCHOR,
            "        rec['answer_key_status'] = answer.get('status')",
            "",
        ]))
        fidelity = self.root / 'pipeline/scripts/fidelity.py'
        fidelity.write_text(FIDELITY_ANCHOR)
        for name in ('phase5_export_evidence.py',
                     'phase4_answer_key_evidence.py',
                     'phase3_interaction_reconstruction.py'):
            (self.root / 'skill' / name).write_text('# synthetic helper\n')

    def test_patcher_idempotent_and_helpers_installed(self):
        self.mini_upstream()
        patch_upstream(self.root / 'pipeline', self.root / 'skill')
        e = (self.root / 'pipeline/scripts/build_technical_export.py').read_text()
        self.assertIn("PHASE5_EVIDENCE = PHASE5.load_phase4_evidence(", e)
        self.assertIn("item['_phase4'] = PHASE5_EVIDENCE.get(", e)
        self.assertIn("hold['phase5'] = {", e)
        self.assertIn("PHASE5.matrix_key_from_phase4(", e)
        self.assertIn("PHASE5.dropdown_key_from_phase4(", e)
        self.assertIn("rec['answer_key_source'] = ", e)
        f = (self.root / 'pipeline/scripts/fidelity.py').read_text()
        self.assertIn("phase4_pixel_agreed", f)
        self.assertIn("phase4_mismatch", f)
        for name in ('phase5_export_evidence.py',
                     'phase4_answer_key_evidence.py',
                     'phase3_interaction_reconstruction.py'):
            self.assertTrue(
                (self.root / 'pipeline/scripts' / name).is_file())
        before = e
        patch_upstream(self.root / 'pipeline', self.root / 'skill')
        self.assertEqual(
            before,
            (self.root / 'pipeline/scripts/build_technical_export.py').read_text())

    def test_patcher_fails_on_mismatched_upstream(self):
        (self.root / 'pipeline/scripts/build_technical_export.py').write_text(
            'new, unrelated converter')
        (self.root / 'pipeline/scripts/fidelity.py').write_text(FIDELITY_ANCHOR)
        for name in ('phase5_export_evidence.py',
                     'phase4_answer_key_evidence.py',
                     'phase3_interaction_reconstruction.py'):
            (self.root / 'skill' / name).write_text('# test\n')
        with self.assertRaisesRegex(ValueError,
                                    'Pinned canonical upstream mismatch'):
            patch_upstream(self.root / 'pipeline', self.root / 'skill')


if __name__ == '__main__':
    unittest.main()
