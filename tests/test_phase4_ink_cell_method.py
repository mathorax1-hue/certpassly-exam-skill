#!/usr/bin/env python3
"""ink_cell mark-method contract tests (synthetic only).

Synthetic answer-area images are drawn with OpenCV (header row, statement
rows, owner-drawn cell marks); OCR lines are injected so no pipeline
dependency exists. Covers: column cluster detection, decisive-cell mark
emission, and the fail-closed abstentions (missing anchor, single column,
non-matrix structure, segmentation mismatch, no decisive ink, overlapping
row bands). Also covers the extended-collector method-pool attachment.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'scripts'))

import phase4_answer_key_evidence as P4  # noqa: E402
import phase4_ink_cell_method as INK  # noqa: E402

W, H = 1000, 300
ROW_BANDS = [(70, 100), (140, 170), (210, 240)]
HEADER_Y = (30, 55)
YES_X, NO_X = 860, 965
CELL_BOX_W, CELL_BOX_H = 70, 30


def draw_matrix(path, cells, statements=('row one text', 'row two text',
                                         'row three text'),
                headers=('Statements', 'Yes', 'No')):
    """Draw a synthetic matrix answer image.

    ``cells`` maps row index (0-based) to 'yes'/'no'/'None' (no mark).
    """
    img = np.full((H, W), 255, dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    if headers[0]:
        cv2.putText(img, headers[0], (50, HEADER_Y[1]), font, 0.5, 0, 1)
    if headers[1]:
        cv2.putText(img, headers[1], (YES_X - 20, HEADER_Y[1]), font, 0.5,
                    0, 1)
    if headers[2]:
        cv2.putText(img, headers[2], (NO_X - 15, HEADER_Y[1]), font, 0.5,
                    0, 1)
    for i, (y0, y1) in enumerate(ROW_BANDS):
        cv2.putText(img, statements[i], (50, y1 - 8), font, 0.45, 0, 1)
        cell = cells.get(i)
        if cell and cell in ('yes', 'no'):
            cx = YES_X if cell == 'yes' else NO_X
            cy = (y0 + y1) // 2
            cv2.rectangle(img, (cx - CELL_BOX_W // 2,
                                cy - CELL_BOX_H // 2),
                          (cx + CELL_BOX_W // 2, cy + CELL_BOX_H // 2),
                          0, thickness=3)
    cv2.imwrite(str(path), img)
    return path


def ocr_lines_fn(statements=('row one text', 'row two text',
                             'row three text')):
    """Synthetic OCR lines matching the drawn layout (normalized)."""

    def fn(path):
        lines = []
        lines.append({'text': 'Statements', 'x': 0.05, 'x1': 0.15,
                      'y': HEADER_Y[0] / H, 'y1': HEADER_Y[1] / H,
                      'words': []})
        for text, (y0, y1) in zip(statements, ROW_BANDS):
            lines.append({'text': text, 'x': 0.05, 'x1': 0.75,
                          'y': y0 / H, 'y1': y1 / H, 'words': []})
        return lines

    return fn


def matrix_item_and_visual(n_rows=3):
    rows = [{'id': 'r%d' % (i + 1),
             'text': 'row %s text' % ['one', 'two', 'three'][i]}
            for i in range(n_rows)]
    item = {'question_key': 'qX', 'answer_images': ['a.png'],
            'question_images': ['q.png'], 'options': {},
            'source_region_candidates': []}
    visual = {'kind': 'yes_no', 'rows': rows, 'ocr': [], 'notes': []}
    return item, visual


class InkCellMarksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'a.png'

    def marks(self, cells, **kw):
        draw_matrix(self.path, cells, **kw)
        item, visual = matrix_item_and_visual()
        return INK.ink_cell_marks(self.path, item, visual,
                                  'unused-pipeline-scripts',
                                  ocr_lines_fn=ocr_lines_fn())

    def test_decisive_rows_emit_marks(self):
        cells = {0: 'yes', 1: 'no', 2: 'yes'}
        marks = self.marks(cells)
        self.assertEqual(len(marks), 3, marks)
        by_y = sorted(marks, key=lambda m: m['y'])
        self.assertEqual([m['cell'] for m in by_y], ['yes', 'no', 'yes'])
        self.assertEqual([m['kind'] for m in marks],
                         ['ink_cell'] * 3)
        # marks sit in the winning column
        self.assertTrue(all(
            abs(m['x'] - (YES_X if m['cell'] == 'yes' else NO_X) / W)
            < 0.01 for m in marks))

    def test_no_ink_no_marks(self):
        marks = self.marks({})
        self.assertEqual(marks, [])

    def test_missing_header_anchor_abstains(self):
        # no 'Statements' anchor line: column detection fails
        draw_matrix(self.path, {0: 'yes', 1: 'no', 2: 'yes'})
        item, visual = matrix_item_and_visual()

        def fn(path):
            return [{'text': t, 'x': 0.05, 'x1': 0.75,
                     'y': y0 / H, 'y1': y1 / H, 'words': []}
                    for t, (y0, y1) in zip(
                        ('row one text', 'row two text', 'row three text'),
                        ROW_BANDS)]

        marks = INK.ink_cell_marks(self.path, item, visual, 'x',
                                   ocr_lines_fn=fn)
        self.assertEqual(marks, [])

    def test_single_column_abstains(self):
        marks = self.marks({0: 'yes', 1: 'no', 2: 'yes'},
                           headers=('Statements', 'Yes', None))
        self.assertEqual(marks, [])

    def test_non_matrix_structure_abstains(self):
        draw_matrix(self.path, {0: 'yes', 1: 'no', 2: 'yes'})
        item, visual = matrix_item_and_visual()
        visual['kind'] = 'dropdown'
        visual['blanks'] = [{'id': 'b1', 'choices': ['x', 'y']}]
        visual.pop('rows')
        marks = INK.ink_cell_marks(self.path, item, visual, 'x',
                                   ocr_lines_fn=ocr_lines_fn())
        self.assertEqual(marks, [])

    def test_segmentation_mismatch_abstains(self):
        draw_matrix(self.path, {0: 'yes', 1: 'no', 2: 'yes'})
        item, visual = matrix_item_and_visual(n_rows=3)
        # only two OCR statement lines for three structure rows
        lines = ocr_lines_fn()('')
        marks = INK.ink_cell_marks(
            self.path, item, visual, 'x',
            ocr_lines_fn=lambda p: [l for l in lines
                                    if l['text'] != 'row three text'])
        self.assertEqual(marks, [])

    def test_overlapping_row_bands_abstain(self):
        draw_matrix(self.path, {0: 'yes', 1: 'no', 2: 'yes'})
        item, visual = matrix_item_and_visual()

        def fn(path):
            base = ocr_lines_fn()('')
            # stretch the first row into the second row's band
            base[1]['y1'] = base[2]['y'] + (base[2]['y1'] - base[2]['y'])
            return base

        marks = INK.ink_cell_marks(self.path, item, visual, 'x',
                                   ocr_lines_fn=fn)
        self.assertEqual(marks, [])

    def test_text_correspondence_failure_abstains(self):
        draw_matrix(self.path, {0: 'yes', 1: 'no', 2: 'yes'})
        item, visual = matrix_item_and_visual()
        for row in visual['rows']:
            row['text'] = 'completely different words here'
        marks = INK.ink_cell_marks(self.path, item, visual, 'x',
                                   ocr_lines_fn=ocr_lines_fn())
        self.assertEqual(marks, [])


class HeaderColumnsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'a.png'

    def test_two_clusters_ordered(self):
        draw_matrix(self.path, {})
        cols = INK.header_columns(self.path, ocr_lines_fn()(''))
        self.assertIsNotNone(cols)
        self.assertEqual(len(cols), 2)
        self.assertLess(cols[0], cols[1])
        self.assertAlmostEqual(cols[0], YES_X / W, delta=0.03)
        self.assertAlmostEqual(cols[1], NO_X / W, delta=0.03)

    def test_missing_image(self):
        self.assertIsNone(
            INK.header_columns(Path('/nonexistent.png'), []))


class ExtendedCollectorsTest(unittest.TestCase):
    def test_pool_attachment(self):
        import phase4_extended_evidence_run as RUN
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'a.png'
        draw_matrix(path, {0: 'yes', 1: 'no', 2: 'yes'})
        item, visual = matrix_item_and_visual()
        split = {'qX': item}
        collectors = RUN.ExtendedCollectors('unused', split, {'qX': visual},
                                            ocr_lines_fn=ocr_lines_fn())
        with mock.patch.object(
                P4.Collectors, 'mark_methods',
                return_value={'marker_box': [{'x': 0.5, 'y': 0.5,
                                              'w': 0.02, 'h': 0.02}]}):
            out = collectors.mark_methods(str(path))
        self.assertIn('marker_box', out)
        self.assertIn('ink_cell', out)
        self.assertEqual([m['cell'] for m in out['ink_cell']],
                         ['yes', 'no', 'yes'])

    def test_pool_attachment_abstain(self):
        import phase4_extended_evidence_run as RUN
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'a.png'
        draw_matrix(path, {})  # no marks: ink_cell abstains
        item, visual = matrix_item_and_visual()
        collectors = RUN.ExtendedCollectors(
            'unused', {'qX': item}, {'qX': visual})
        with mock.patch.object(P4.Collectors, 'mark_methods',
                               return_value={}):
            out = collectors.mark_methods(str(path))
        self.assertNotIn('ink_cell', out)

    def test_unknown_answer_image_abstains(self):
        import phase4_extended_evidence_run as RUN
        collectors = RUN.ExtendedCollectors('unused', {}, {})
        with mock.patch.object(P4.Collectors, 'mark_methods',
                               return_value={}):
            out = collectors.mark_methods('/nowhere/a.png')
        self.assertNotIn('ink_cell', out)


if __name__ == '__main__':
    unittest.main()
