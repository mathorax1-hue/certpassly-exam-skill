#!/usr/bin/env python3
"""Phase 4 answer-key evidence contract tests (synthetic only).

Covers: text-key mapping and choose-N; matrix mapping with structure-guided
segmentation, correspondence validation, column fallbacks and the unchanged
two-agreeing-methods rule; drop-down mapping with per-blank geometry,
widget exclusion and fuzzy choice matching; owner selection-box candidates;
structure selection (region first, canonical fallback) and fail-closed
blocking. Collectors are faked: no images, no private content.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'scripts'))

import phase4_answer_key_evidence as P4  # noqa: E402


def matrix_item(key='qX', n_rows=3):
    return {
        'question_key': key,
        'source_number': 1,
        'stem': ('For each of the following statements, select Yes if the '
                 'statement is true. Otherwise, select No.'),
        'options': {},
        'question_images': ['q.png'],
        'answer_images': ['a.png'],
        'source_region_candidates': [],
    }


def matrix_visual(rows, ocr=None):
    return {'kind': 'yes_no', 'rows': rows, 'ocr': ocr or [], 'notes': []}


def rows_of(*texts):
    return [{'id': 'r%d' % (i + 1), 'text': t, 'minconf': 90}
            for i, t in enumerate(texts)]


def ocr_line(text, y, x=0.1, x1=None, words=None):
    return {'text': text, 'x': x, 'y': y, 'x1': x1 if x1 is not None
            else x + 0.5, 'y1': y + 0.05, 'words': words or []}


def word(t, x, w=0.04):
    return {'t': t, 'x': x, 'w': w}


def mark(x, y, w=0.03, h=0.05):
    return {'x': x, 'y': y, 'w': w, 'h': h}


class FakeCollectors(P4.Collectors):
    """Deterministic evidence source: marks and OCR lines per image."""

    def __init__(self, marks=None, lines=None, selection=None):
        super().__init__(None)
        self.marks = marks or {}
        self.lines = lines or []
        self.selection = selection

    def mark_methods(self, answer_path, cfg=None):
        return {name: [dict(m) for m in self.marks.get(name, [])]
                for name in ('marker_box', 'checked_box', 'highlight')}

    def ocr_lines(self, image_path):
        return [dict(l) for l in self.lines]

    def selection_box(self, question_path, answer_path):
        return dict(self.selection) if self.selection else {
            'status': 'HELD_UNCERTAIN_MARK'}


MATRIX_LINES = [
    ocr_line('Answer Area', 0.01),
    ocr_line('Statements', 0.06),
    ocr_line('Yes', 0.06, x=0.72, x1=0.75),
    ocr_line('No', 0.06, x=0.90, x1=0.92),
    ocr_line('Statement one text here', 0.20),
    ocr_line('Statement two text here', 0.40),
    ocr_line('Statement two second line', 0.46),
    ocr_line('Statement three text here', 0.70),
]
MATRIX_ROWS = rows_of('Statement one text here',
                      'Statement two text here second line',
                      'Statement three text here')
# three marks: r1 yes-column, r2 no-column, r3 no-column
MATRIX_MARKS_MB = [mark(0.73, 0.20), mark(0.91, 0.42), mark(0.91, 0.71)]
MATRIX_MARKS_CB = [mark(0.73, 0.20), mark(0.91, 0.42), mark(0.91, 0.71)]


def media_dir():
    """A temp media dir whose files exist, so image-presence checks pass."""
    tmp = tempfile.mkdtemp()
    for name in ('q.png', 'a.png', 'b.png'):
        (Path(tmp) / name).write_bytes(b'')
    return tmp


class MatrixMapping(unittest.TestCase):
    def test_two_agreeing_methods_verify(self):
        rec = P4.verify_visual_item(
            matrix_item(), matrix_visual(MATRIX_ROWS),
            media_dir(), FakeCollectors(
                marks={'marker_box': MATRIX_MARKS_MB,
                       'checked_box': MATRIX_MARKS_CB},
                lines=MATRIX_LINES), {})
        self.assertEqual(rec['status'], 'verified_pixel_agreed')
        self.assertEqual(rec['answer_key'],
                         {'rows': {'r1': 'yes', 'r2': 'no', 'r3': 'no'}})
        self.assertEqual(sorted(rec['agreeing_methods']),
                         ['checked_box', 'marker_box'])

    def test_structure_guided_segmentation_of_two_line_statement(self):
        reading, notes = P4.map_matrix_marks(
            MATRIX_MARKS_MB,
            [r for r in P4.group_lines(MATRIX_LINES)
             if r['text'] and not P4.is_template_row(r['text'])],
            MATRIX_ROWS, 0.735, 0.91)
        self.assertEqual(reading, {'r1': 'yes', 'r2': 'no', 'r3': 'no'})
        self.assertEqual(notes, [])

    def test_correspondence_failure_blocks(self):
        other_rows = rows_of('Unrelated first statement',
                             'Unrelated second statement',
                             'Unrelated third statement')
        reading, notes = P4.map_matrix_marks(
            MATRIX_MARKS_MB, [], other_rows, 0.735, 0.91)
        self.assertIsNone(reading)
        self.assertTrue(any('does not show' in n or 'does not correspond'
                            in n for n in notes))

    def test_partial_row_coverage_is_not_a_reading(self):
        marks = [mark(0.73, 0.20)]  # only r1
        reading, notes = P4.map_matrix_marks(
            marks,
            [r for r in P4.group_lines(MATRIX_LINES)
             if r['text'] and not P4.is_template_row(r['text'])],
            MATRIX_ROWS, 0.735, 0.91)
        self.assertIsNone(reading)
        self.assertTrue(any('cover 1 of 3' in n for n in notes))

    def test_both_columns_on_one_row_blocks(self):
        marks = [mark(0.73, 0.20), mark(0.91, 0.21)]
        reading, notes = P4.map_matrix_marks(
            marks,
            [r for r in P4.group_lines(MATRIX_LINES)
             if r['text'] and not P4.is_template_row(r['text'])],
            MATRIX_ROWS, 0.735, 0.91)
        self.assertIsNone(reading)

    def test_no_only_column_fallback(self):
        """No header: marks left of the No column are Yes."""
        lines = [l for l in MATRIX_LINES
                 if l['text'] not in ('Yes', 'No')]
        rec = P4.verify_visual_item(
            matrix_item(),
            matrix_visual(MATRIX_ROWS, ocr=[{'t': 'No', 'x': 0.90,
                                             'y': 0.06}]),
            media_dir(), FakeCollectors(
                marks={'marker_box': MATRIX_MARKS_MB,
                       'checked_box': MATRIX_MARKS_CB},
                lines=lines), {})
        self.assertEqual(rec['status'], 'verified_pixel_agreed')
        self.assertEqual(rec['answer_key']['rows']['r1'], 'yes')

    def test_yes_no_columns_from_combined_header_words(self):
        line = ocr_line('Statements Yes No', 0.06,
                        words=[word('Statements', 0.10),
                               word('Yes', 0.72), word('No', 0.90)])
        yes_x, no_x = P4.yes_no_columns([line])
        self.assertAlmostEqual(yes_x, 0.74, places=2)
        self.assertAlmostEqual(no_x, 0.92, places=2)

    def test_methods_disagree_blocked_with_readings_recorded(self):
        rec = P4.verify_visual_item(
            matrix_item(), matrix_visual(MATRIX_ROWS),
            media_dir(), FakeCollectors(
                marks={'marker_box': MATRIX_MARKS_MB,
                       'checked_box': [mark(0.73, 0.20), mark(0.91, 0.42),
                                       mark(0.73, 0.71)]},
                lines=MATRIX_LINES), {})
        self.assertEqual(rec['status'], 'blocked_contradictory_marks')
        self.assertIn('marker_box', rec['method_readings'])
        self.assertTrue(rec['blocker'])


class DropdownMapping(unittest.TestCase):
    def blank(self, bid, choices, bbox=(0.40, 0.20, 0.95, 0.60)):
        return {'id': bid, 'bbox': list(bbox),
                'choices': [{'text': c, 'strict': True} for c in choices]}

    def dropdown_item(self, key='qY'):
        return {
            'question_key': key,
            'source_number': 2,
            'stem': 'Select the answer that correctly completes the '
                    'sentence.',
            'options': {},
            'question_images': ['q.png'],
            'answer_images': ['a.png'],
            'source_region_candidates': [],
        }

    def dropdown_visual(self, blanks):
        return {'kind': 'dropdown', 'blanks': blanks, 'notes': []}

    def test_selection_marked_option_maps_to_choice(self):
        blanks = [self.blank('blank1', ['First option', 'Second option',
                                        'Third option'])]
        lines = [
            ocr_line('Answer Area', 0.01),
            ocr_line('First option', 0.25, x=0.42, x1=0.60),
            ocr_line('Second option', 0.40, x=0.42, x1=0.60),
            ocr_line('Third option', 0.55, x=0.42, x1=0.60),
        ]
        reading, notes = P4.map_dropdown_marks(
            [mark(0.45, 0.40)], lines, blanks)
        self.assertEqual(reading, {'blank1': 'Second option'})
        self.assertEqual(notes, [])

    def test_widget_geometry_is_never_a_selection(self):
        blanks = [self.blank('blank1', ['First option', 'Second option'])]
        lines = [
            ocr_line('First option', 0.25, x=0.42, x1=0.60),
            ocr_line('Second option', 0.40, x=0.42, x1=0.60),
        ]
        # one tall box covering the whole list
        reading, notes = P4.map_dropdown_marks(
            [mark(0.45, 0.25, w=0.2, h=0.25)], lines, blanks)
        self.assertIsNone(reading)
        self.assertTrue(any('widget' in n for n in notes))

    def test_two_options_marked_is_ambiguous(self):
        blanks = [self.blank('blank1', ['First option', 'Second option'])]
        lines = [
            ocr_line('First option', 0.25, x=0.42, x1=0.60),
            ocr_line('Second option', 0.40, x=0.42, x1=0.60),
        ]
        reading, notes = P4.map_dropdown_marks(
            [mark(0.45, 0.25), mark(0.45, 0.40)], lines, blanks)
        self.assertIsNone(reading)
        self.assertTrue(any('two different options' in n for n in notes))

    def test_multi_blank_lists_share_choice_texts(self):
        """Two blanks with identical choice lists are distinguished by
        list geometry, not by text."""
        blanks = [self.blank('blank1', ['Alpha', 'Beta'],
                             bbox=(0.40, 0.10, 0.95, 0.40)),
                  self.blank('blank2', ['Alpha', 'Beta'],
                             bbox=(0.40, 0.55, 0.95, 0.85))]
        lines = [
            ocr_line('Alpha', 0.15, x=0.42, x1=0.60),
            ocr_line('Beta', 0.28, x=0.42, x1=0.60),
            ocr_line('Alpha', 0.60, x=0.42, x1=0.60),
            ocr_line('Beta', 0.73, x=0.42, x1=0.60),
        ]
        reading, notes = P4.map_dropdown_marks(
            [mark(0.45, 0.28), mark(0.45, 0.60)], lines, blanks)
        self.assertEqual(reading, {'blank1': 'Beta', 'blank2': 'Alpha'})

    def test_fuzzy_tokens_survive_one_ocr_misread(self):
        self.assertTrue(P4.token_matches('claim', 'ciaim'))
        self.assertFalse(P4.token_matches('claim', 'queue'))
        self.assertFalse(P4.token_matches('an', 'am'))
        self.assertEqual(P4.match_token_ratio(
            'An auto-claim policy', 'An auto-ciaim policy'), 1.0)

    def test_subset_ties_resolve_to_more_matching_tokens(self):
        """A label matching every token of the longer choice outranks a
        subset match on the shorter choice."""
        scored = P4.best_text_matches(
            'are not assigned a license',
            [{'text': 'are assigned a license'},
             {'text': 'are not assigned a license'}])
        self.assertEqual(scored[0]['text'], 'are not assigned a license')
        self.assertEqual(scored[0]['hits'], 5)
        matched, ratio = P4.unique_text_match(
            'are not assigned a license',
            [{'text': 'are assigned a license'},
             {'text': 'are not assigned a license'}])
        self.assertEqual(matched['text'], 'are not assigned a license')


class SelectionBox(unittest.TestCase):
    def dropdown_case(self, selection):
        item = {
            'question_key': 'qZ', 'source_number': 3,
            'stem': 'Select the answer that correctly completes the '
                    'sentence.',
            'options': {}, 'question_images': ['q.png'],
            'answer_images': ['a.png'], 'source_region_candidates': [],
        }
        blanks = [{'id': 'blank1', 'bbox': [0.4, 0.2, 0.95, 0.6],
                   'choices': [{'text': 'First option', 'strict': True},
                               {'text': 'Second option', 'strict': True}]}]
        visual = {'kind': 'dropdown', 'blanks': blanks, 'notes': []}
        lines = [ocr_line('First option', 0.25, x=0.42, x1=0.60),
                 ocr_line('Second option', 0.40, x=0.42, x1=0.60)]
        return P4.verify_visual_item(
            item, visual, media_dir(),
            FakeCollectors(marks={'checked_box': []}, lines=lines,
                           selection=selection), {})

    def test_verified_selection_without_second_method_is_candidate(self):
        rec = self.dropdown_case({
            'status': 'OWNER_MARK_CANDIDATE_VERIFIED',
            'selected_label': 'second option',
            'bbox': [10, 20, 100, 30],
            'evidence': 'Two pixel thresholds; answer OCR PSM 6/7',
        })
        self.assertEqual(rec['status'], 'candidate_single_chain')
        self.assertEqual(rec['selection_box']['maps_to_choice_text'],
                         'Second option')
        self.assertIn('reviewer or owner confirmation', rec['blocker'])

    def test_selection_label_not_matching_structure_is_not_candidate(self):
        rec = self.dropdown_case({
            'status': 'OWNER_MARK_CANDIDATE_VERIFIED',
            'selected_label': 'something else entirely',
            'bbox': [10, 20, 100, 30],
        })
        self.assertNotEqual(rec['status'], 'candidate_single_chain')


class TextKeys(unittest.TestCase):
    def text_item(self, raw, options, stem='Which two should you choose?'):
        return {
            'question_key': 'qT', 'source_number': 4, 'stem': stem,
            'options': options, 'question_images': [],
            'answer_images': [], 'answer_raw': raw,
        }

    def test_single_letter_maps(self):
        item = self.text_item('B', {'a': 'one', 'b': 'two', 'c': 'three'},
                              stem='Which one should you choose?')
        rec = P4.verify_text_key(item, {})
        self.assertEqual(rec['status'], 'verified_text')
        self.assertEqual(rec['answer_key'], {'correct_option_ids': ['b']})
        self.assertEqual(rec['scoring']['type'], 'single_choice')

    def test_choose_n_mismatch_blocks(self):
        item = self.text_item('A', {'a': 'one', 'b': 'two'})
        rec = P4.verify_text_key(item, {})
        self.assertEqual(rec['status'], 'blocked_text_choose_n')

    def test_multi_letters_with_choose_two(self):
        item = self.text_item('AC', {'a': 'one', 'b': 'two', 'c': 'three'})
        rec = P4.verify_text_key(item, {})
        self.assertEqual(rec['status'], 'verified_text')
        self.assertEqual(rec['answer_key'],
                         {'correct_option_ids': ['a', 'c']})
        self.assertEqual(rec['scoring']['choose_n'], 2)

    def test_unmapped_letter_blocks(self):
        item = self.text_item('H', {'a': 'one'})
        rec = P4.verify_text_key(item, {})
        self.assertEqual(rec['status'], 'blocked_text_unmapped')


class StructureAndFailClosed(unittest.TestCase):
    def test_no_structure_blocks(self):
        item = matrix_item()
        item['answer_images'] = ['a.png']
        rec = P4.verify_visual_item(
            item, {'kind': 'unknown', 'notes': []}, media_dir(),
            FakeCollectors(), {})
        self.assertEqual(rec['status'], 'blocked_no_structure')

    def test_structure_blocker_input_respected(self):
        item = matrix_item()
        rec = P4.verify_question(
            item, {'kind': 'yes_no', 'rows': MATRIX_ROWS}, '/media',
            FakeCollectors(), {},
            structure_blockers={'qX': 'Phase 3 blocker: ambiguous'})
        self.assertEqual(rec['status'], 'blocked_structure_under_review')
        self.assertIn('Phase 3 blocker', rec['blocker'])

    def test_multiple_answer_images_block(self):
        item = matrix_item()
        item['answer_images'] = ['a.png', 'b.png']
        rec = P4.verify_visual_item(
            item, matrix_visual(MATRIX_ROWS), media_dir(),
            FakeCollectors(), {})
        self.assertEqual(rec['status'], 'blocked_multiple_answer_images')

    def test_no_marks_blocks_with_positions_recorded(self):
        item = matrix_item()
        rec = P4.verify_visual_item(
            item, matrix_visual(MATRIX_ROWS), media_dir(),
            FakeCollectors(marks={}, lines=MATRIX_LINES), {})
        self.assertEqual(rec['status'], 'blocked_no_marks')

    def test_region_structure_preferred_with_deviation_recorded(self):
        """When the region structure exists it is used, and canonical
        differences become Phase 5 findings, not silent changes."""
        item = matrix_item()
        item['source_region_candidates'] = [
            {'kind': 'matrix_statement_column_text_band',
             'bbox_pixels': [0, 72, 900, 99], 'source_dimensions': [1000, 300],
             'ocr_text_candidate': 'Statement one text here',
             'two_pass_agreement': True,
             'usable_as_verified_source': True, 'passes': []},
            {'kind': 'matrix_statement_column_text_band',
             'bbox_pixels': [0, 127, 900, 153],
             'source_dimensions': [1000, 300],
             'ocr_text_candidate': 'Statement two text here',
             'two_pass_agreement': True,
             'usable_as_verified_source': True, 'passes': []},
            {'kind': 'matrix_statement_column_text_band',
             'bbox_pixels': [0, 182, 900, 209],
             'source_dimensions': [1000, 300],
             'ocr_text_candidate': 'Statement three text here',
             'two_pass_agreement': True,
             'usable_as_verified_source': True, 'passes': []},
        ]
        visual = matrix_visual(rows_of('Different first row',
                                       'Statement two text here',
                                       'Statement three text here'))
        structure = P4.structure_of(item, visual)
        self.assertEqual(structure['source'],
                         'phase3_strict_source_regions')
        self.assertTrue(structure['deviations_from_canonical'])

    def test_summary_counts_and_no_release_flags(self):
        split = {'qA': {'question_key': 'qA', 'source_number': 1,
                        'stem': 'Which one?', 'options': {'a': 'x'},
                        'answer_raw': 'A', 'question_images': [],
                        'answer_images': []}}
        doc = P4.build_evidence(split, {}, '/media',
                                collectors=FakeCollectors(), cfg={})
        self.assertEqual(doc['status'],
                         'PHASE4_ANSWER_KEY_EVIDENCE_NOT_RELEASE')
        self.assertTrue(doc['no_key_guessed'])
        self.assertFalse(doc['release_approved'])
        self.assertEqual(doc['summary']['verified_text'], 1)
        self.assertEqual(doc['summary']['verified'], 1)
        self.assertEqual(doc['questions'][0]['release_approved'], False)


if __name__ == '__main__':
    unittest.main()
