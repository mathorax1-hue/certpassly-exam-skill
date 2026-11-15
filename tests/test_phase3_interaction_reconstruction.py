#!/usr/bin/env python3
"""Phase 3 interaction reconstruction contract tests (synthetic only).

Covers: matrix row reconstruction with scaffolding exclusion and multi-line
statement merging; enclosed-control drop-downs; unboxed option stacks;
stacked control rows; UI-chrome stripping; template-label exclusion;
fail-closed behavior (no structure without evidence, ambiguous statement
grouping holds, unreadable controls hold, no answer keys ever); the visual
draft fill contract; and the evidence report branches.
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'scripts'))
sys.path.insert(0, str(HERE / 'fixtures'))

import phase3_interaction_reconstruction as P3  # noqa: E402
import phase3_layouts as FX  # noqa: E402


class MatrixReconstruction(unittest.TestCase):
    def test_rows_from_matrix_bands_excluding_scaffolding(self):
        rows, uncertain = P3.reconstruct_matrix_rows(FX.matrix_item())
        texts = [r['text'] for r in rows]
        self.assertEqual(texts, ['Users can create agents here',
                                 'Licenses are assigned here',
                                 'Reports show usage data continues here'])
        self.assertFalse(uncertain)
        self.assertTrue(all(r['strict'] for r in rows))

    def test_band_and_localized_collapse_to_one_row(self):
        rows, _ = P3.reconstruct_matrix_rows(FX.matrix_item())
        # Three statements, not six: band + localized variants merge.
        self.assertEqual(len(rows), 3)

    def test_multi_line_statement_merges_on_overlap(self):
        rows, uncertain = P3.reconstruct_matrix_rows(FX.matrix_item())
        self.assertIn('continues here', rows[-1]['text'])
        self.assertFalse(uncertain)

    def test_ambiguous_grouping_is_flagged_not_guessed(self):
        rows, uncertain = P3.reconstruct_matrix_rows(FX.ambiguous_matrix_item())
        self.assertTrue(uncertain)
        rec = P3.reconstruct_item(FX.ambiguous_matrix_item(),
                                  FX.visual_rec('yes_no'))
        self.assertFalse(rec['filled'])
        self.assertTrue(any('reviewer confirmation' in b
                            for b in rec['blockers']))

    def test_yes_no_requires_instruction_for_unknown_kind(self):
        item = FX.matrix_item()
        item['stem'] = 'Some other instruction entirely.'
        rec = P3.reconstruct_item(item, FX.visual_rec('unknown'))
        # No yes/no instruction and no dropdown layout: nothing to map.
        self.assertEqual(rec['kind'], 'unknown')
        self.assertFalse(rec['filled'])


class DropdownReconstruction(unittest.TestCase):
    def test_enclosed_control_with_option_bands(self):
        item = FX.control_dropdown_item()
        blanks, text_lines, unreadable = P3.reconstruct_dropdown(item)
        self.assertEqual(unreadable, [])
        self.assertEqual(len(blanks), 1)
        blank = blanks[0]
        self.assertEqual(blank['structure'], 'control')
        self.assertEqual([c['text'] for c in blank['choices']],
                         ['option one', 'option two', 'option three',
                          'option four'])
        self.assertEqual([c['strict'] for c in blank['choices']],
                         [True, True, True, False])

    def test_unboxed_option_stack(self):
        item = FX.unboxed_stack_item()
        ocr_lines = [
            {'text': 'Sentence part one', 'x': 0.05, 'y': 0.15},
            {'text': 'First option', 'x': 0.45, 'y': 0.27},
            {'text': 'Sentence part two', 'x': 0.05, 'y': 0.60},
        ]
        blanks, text_lines, unreadable = P3.reconstruct_dropdown(
            item, ocr_lines)
        self.assertEqual(len(blanks), 1)
        blank = blanks[0]
        self.assertEqual(blank['structure'], 'option_stack')
        self.assertEqual([c['text'] for c in blank['choices']],
                         ['First option', 'Second option', 'Third option',
                          'Fourth option'])
        sentence = ' '.join(t['t'] for t in text_lines)
        self.assertIn('Sentence part one', sentence)
        self.assertIn('Sentence part two', sentence)
        for choice in blank['choices']:
            self.assertNotIn(choice['text'], sentence)

    def test_stacked_controls_are_one_option_list(self):
        item = FX.stacked_controls_item()
        blanks, _, _ = P3.reconstruct_dropdown(item)
        self.assertEqual(len(blanks), 1)
        self.assertEqual([c['text'] for c in blanks[0]['choices']],
                         ['First report', 'Second report', 'Third report'])

    def test_unreadable_control_holds_instead_of_guessing(self):
        item = FX.control_dropdown_item(unreadable=True)
        blanks, _, unreadable = P3.reconstruct_dropdown(item)
        self.assertEqual(len(unreadable), 1)
        rec = P3.reconstruct_item(item, FX.visual_rec('dropdown'))
        self.assertFalse(rec['filled'])
        self.assertTrue(any('no OCR pass could read' in b
                            for b in rec['blockers']))

    def test_sentence_lines_outside_blank_boxes(self):
        item = FX.control_dropdown_item()
        ocr_lines = [
            {'text': 'Sentence before the blank', 'x': 0.05, 'y': 0.13},
            {'text': 'option two', 'x': 0.52, 'y': 0.47},
            {'text': 'Sentence after the blank', 'x': 0.05, 'y': 0.85},
        ]
        blanks, text_lines, _ = P3.reconstruct_dropdown(item, ocr_lines)
        texts = [t['t'] for t in text_lines]
        self.assertEqual(texts, ['Sentence before the blank',
                                 'Sentence after the blank'])


class ChromeAndScaffolding(unittest.TestCase):
    def test_leading_and_trailing_chrome_stripped(self):
        self.assertEqual(P3._strip_chrome('O Statement text'), 'Statement text')
        self.assertEqual(P3._strip_chrome('@) Public'), 'Public')
        self.assertEqual(P3._strip_chrome('| Agent insights'), 'Agent insights')
        self.assertEqual(P3._strip_chrome('Site policy comparison |'),
                         'Site policy comparison')
        # Sentence punctuation is content, not chrome.
        self.assertEqual(P3._strip_chrome('Ends with a period.'),
                         'Ends with a period.')

    def test_template_labels_excluded_including_headers(self):
        self.assertTrue(P3._is_template_label('Answer Area'))
        self.assertTrue(P3._is_template_label('Statements'))
        self.assertTrue(P3._is_template_label('Statements Yes No'))
        self.assertFalse(P3._is_template_label('A real statement'))


class FillContract(unittest.TestCase):
    def test_fill_only_when_empty_and_never_keys(self):
        item = FX.control_dropdown_item()
        d = FX.visual_rec('dropdown')
        d['ocr'] = [{'text': 'Sentence before the blank', 'x': 0.05,
                     'y': 0.13}]
        filled = P3.fill_item_structure(d, item)
        self.assertEqual(len(filled['blanks']), 1)
        blank = filled['blanks'][0]
        self.assertIsNone(blank['selected'])
        self.assertNotIn('key', filled)
        self.assertTrue(filled['phase3_reconstruction']['filled_structure'])

    def test_canonical_structure_preserved_with_corroboration(self):
        item = FX.control_dropdown_item()
        d = FX.visual_rec('dropdown')
        d['blanks'] = [{'id': 'blank1', 'choices': ['canonical one',
                                                    'canonical two'],
                        'selected': 'canonical one'}]
        d['key'] = {'blank1': 'canonical one'}
        filled = P3.fill_item_structure(d, item)
        # Canonical blanks and key survive untouched.
        self.assertEqual(filled['blanks'][0]['choices'][0], 'canonical one')
        self.assertEqual(filled['key'], {'blank1': 'canonical one'})
        self.assertFalse(filled['phase3_reconstruction'].get(
            'filled_structure'))
        self.assertTrue(filled['phase3_reconstruction'][
            'corroborated_canonical'])

    def test_unknown_kind_filled_from_layout_evidence(self):
        item = FX.control_dropdown_item()
        d = FX.visual_rec('unknown')
        filled = P3.fill_item_structure(d, item)
        self.assertEqual(len(filled['blanks']), 1)
        marker = filled['phase3_reconstruction']
        self.assertEqual(marker['kind_evidence'], 'phase3_region_structure')
        self.assertEqual(marker['classifier_kind'], 'unknown')

    def test_no_regions_no_fill(self):
        item = FX.control_dropdown_item()
        item['source_region_candidates'] = []
        d = FX.visual_rec('dropdown')
        filled = P3.fill_item_structure(d, item)
        self.assertNotIn('blanks', filled)
        self.assertTrue(filled['phase3_reconstruction']['blockers'])

    def test_options_items_untouched(self):
        item = FX.control_dropdown_item()
        item['options'] = {'a': 'one', 'b': 'two'}
        d = FX.visual_rec('dropdown')
        filled = P3.fill_item_structure(d, item)
        self.assertNotIn('phase3_reconstruction', filled)


class Report(unittest.TestCase):
    def test_report_branches_and_summary(self):
        split = {
            'qX': FX.matrix_item('qX'),
            'qY': FX.control_dropdown_item('qY'),
            'qZ': FX.unboxed_stack_item('qZ'),
            'qV': FX.ambiguous_matrix_item('qV'),
        }
        split['qY']['options'] = {'a': 'one', 'b': 'two'}
        visual = {
            'qX': FX.visual_rec('yes_no'),
            'qY': FX.visual_rec('selection'),
            'qZ': {'kind': 'unknown', 'ocr': [], 'notes': [],
                   'phase3_reconstruction': {
                       'structure_source': 'phase3_strict_source_regions',
                       'suggested_type': 'inline_dropdown',
                       'filled': True, 'blockers': [],
                       'filled_structure': True},
                   'blanks': [{'id': 'blank1',
                               'choices': ['First option',
                                           'Second option'],
                               'selected': None}]},
            'qV': FX.visual_rec('yes_no'),
        }
        report = P3.build_report(split, visual)
        self.assertEqual(report['status'],
                         'PHASE3_INTERACTION_STRUCTURE_EVIDENCE_NOT_RELEASE')
        self.assertFalse(report['answer_keys_extracted'])
        self.assertFalse(report['release_approved'])
        by_key = {r['question_key']: r for r in report['questions']}
        self.assertEqual(by_key['qY']['structure_source'],
                         'text_layer_options')
        self.assertEqual(by_key['qZ']['structure_source'],
                         'phase3_strict_source_regions')
        self.assertEqual(by_key['qX']['structure_source'],
                         'phase3_strict_source_regions')
        self.assertTrue(by_key['qX']['filled'])
        self.assertFalse(by_key['qV']['filled'])
        self.assertEqual(report['summary']['questions'], 4)
        self.assertEqual(report['summary']['held_with_blockers'], 1)

    def test_coverage_attached_without_changing_verdicts(self):
        split = {'qX': FX.matrix_item('qX')}
        coverage = {'questions': [{
            'question_key': 'qX',
            'reference_content_token_count': 10,
            'verified_token_count': 8,
            'uncovered_token_count': 2,
        }]}
        report = P3.build_report(split, {'qX': FX.visual_rec('yes_no')},
                                 coverage)
        cov = report['questions'][0]['source_coverage']
        self.assertEqual(cov['reference_tokens'], 10)
        self.assertEqual(cov['evidenced_deficient_tokens'], 2)


class PatchContract(unittest.TestCase):
    """Same fail-closed contract as the Phase 2 patch tests: synthetic
    upstream files assembled from the exact guarded anchors."""

    def setUp(self):
        import tempfile
        self.t = tempfile.TemporaryDirectory()
        self.root = Path(self.t.name)
        spec = importlib.util.spec_from_file_location(
            'patch_phase3', HERE.parent / 'scripts' /
            'patch_phase3_upstream_visual_structure.py')
        self.patch_phase3 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.patch_phase3)

    def tearDown(self):
        self.t.cleanup()

    def _make_upstream(self):
        (self.root / 'pipeline/scripts').mkdir(parents=True,
                                               exist_ok=True)
        (self.root / 'skill').mkdir(exist_ok=True)
        analyze = self.root / 'pipeline/scripts/analyze_visual.py'
        analyze.write_text(
            self.patch_phase3.ANALYZE_IMPORT_ANCHOR
            + 'def run(out, split=None):\n'
            + '    for k, r in split.items():\n'
            + '        if True:\n'
            + self.patch_phase3.ANALYZE_ITEM_ANCHOR,
            encoding='utf-8')
        export = self.root / 'pipeline/scripts/build_technical_export.py'
        export.write_text(
            'def export_one():\n'
            + self.patch_phase3.EXPORT_INIT_ANCHOR
            + self.patch_phase3.EXPORT_GATE_ANCHOR
            + self.patch_phase3.EXPORT_TAIL_ANCHOR,
            encoding='utf-8')
        helper = self.root / 'skill/phase3_interaction_reconstruction.py'
        helper.write_text('# synthetic helper\n', encoding='utf-8')
        return analyze, export

    def test_patch_idempotent_and_anchors_patched(self):
        analyze, export = self._make_upstream()
        self.patch_phase3.patch(self.root / 'pipeline', self.root / 'skill')
        a = analyze.read_text(encoding='utf-8')
        e = export.read_text(encoding='utf-8')
        self.assertIn('PHASE3.fill_item_structure', a)
        self.assertIn('built_structure', e)
        self.assertIn('structure_blocker', e)
        self.assertIn('native_structure', e)
        # Idempotent: the second patch changes nothing.
        self.patch_phase3.patch(self.root / 'pipeline', self.root / 'skill')
        self.assertEqual(a, analyze.read_text(encoding='utf-8'))
        self.assertEqual(e, export.read_text(encoding='utf-8'))
        # The helper is installed alongside the canonical modules.
        self.assertTrue((self.root / 'pipeline/scripts/'
                         'phase3_interaction_reconstruction.py').is_file())

    def test_patch_fails_closed_on_mismatched_upstream(self):
        self._make_upstream()
        (self.root / 'pipeline/scripts/analyze_visual.py').write_text(
            'new, unrelated analyzer\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError,
                                    'Pinned canonical upstream mismatch'):
            self.patch_phase3.patch(self.root / 'pipeline', self.root / 'skill')

    def test_patch_fails_closed_on_changed_export(self):
        self._make_upstream()
        (self.root / 'pipeline/scripts/build_technical_export.py').write_text(
            'rewritten export\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError,
                                    'Pinned canonical upstream mismatch'):
            self.patch_phase3.patch(self.root / 'pipeline', self.root / 'skill')


if __name__ == '__main__':
    unittest.main()
