#!/usr/bin/env python3
"""Synthetic Phase 3 fixtures: layout shapes seen in real owner PDFs,
reproduced with invented text so no private exam content enters the public
repository. Geometry mirrors the real region record schema exactly
(kind, bbox_pixels, source_dimensions, two_pass_agreement,
usable_as_verified_source, ocr_text_candidate, passes).
"""
import copy


def region(kind, bbox, text, *, strict=True, agreed=True, dims=(1000, 300),
           source='q.png', word_conf=96, overall_conf=97):
    return {
        'kind': kind,
        'bbox_pixels': list(bbox),
        'source_dimensions': list(dims),
        'source_file': source,
        'crop_sha256': 'fixture-%s-%s' % (kind, bbox[1]),
        'ocr_text_candidate': text,
        'two_pass_agreement': agreed,
        'confidence_pass': strict,
        'usable_as_verified_source': strict,
        'passes': [
            {'id': 'psm3', 'min_confidence': word_conf,
             'mean_confidence': overall_conf, 'word_count': 3},
            {'id': 'psm6', 'min_confidence': word_conf,
             'mean_confidence': overall_conf, 'word_count': 3},
        ],
    }


def matrix_item(key='qX'):
    """Three statements in matrix statement bands, with scaffolding."""
    bands = [
        region('matrix_statement_column_text_band', [0, 7, 900, 25],
               'Answer Area'),
        region('matrix_statement_column_text_band_localized', [4, 7, 90, 25],
               'Answer Area'),
        region('matrix_statement_column_text_band', [0, 41, 900, 66],
               'Statements'),
        region('matrix_statement_column_text_band_localized',
               [116, 41, 200, 66], 'Statements'),
        region('matrix_statement_column_text_band', [0, 72, 900, 99],
               'Users can create agents here'),
        region('matrix_statement_column_text_band_localized',
               [117, 72, 760, 99], 'Users can create agents here'),
        region('matrix_statement_column_text_band', [0, 127, 900, 153],
               'Licenses are assigned here'),
        region('matrix_statement_column_text_band_localized',
               [117, 127, 682, 153], 'Licenses are assigned here'),
        region('matrix_statement_column_text_band', [0, 182, 900, 209],
               'Reports show usage data'),
        region('matrix_statement_column_text_band', [0, 207, 900, 229],
               'continues here'),
    ]
    return {
        'question_key': key,
        'source_number': 1,
        'stem': ('For each of the following statements, select Yes if the '
                 'statement is true. Otherwise, select No.'),
        'options': {},
        'question_images': ['q.png'],
        'source_region_candidates': bands,
    }


def control_dropdown_item(key='qY', unreadable=False):
    """Sentence bands plus one enclosed control with four option bands."""
    bands = [
        region('unboxed_source_text_text_band', [0, 7, 985, 24],
               'Answer Area', strict=False),
        region('unboxed_source_text_text_band_localized', [2, 7, 109, 24],
               'Answer Area', strict=False),
        region('unboxed_source_text_text_band', [0, 39, 985, 67],
               'Sentence before the blank'),
        region('unboxed_source_text_text_band_localized', [53, 39, 818, 67],
               'Sentence before the blank'),
        region('light_ui_text_control', [522, 76, 973, 95], ''),
        region('enclosed_text_control', [521, 104, 970, 280],
               'option one option two option three option four'),
        region('enclosed_text_control_text_band', [521, 111, 970, 132],
               'option one'),
        region('enclosed_text_control_text_band_localized',
               [522, 111, 693, 132], 'option one'),
        region('enclosed_text_control_text_band', [521, 140, 970, 171],
               'option two'),
        region('enclosed_text_control_text_band_localized',
               [522, 140, 793, 171], 'option two'),
        region('enclosed_text_control_text_band', [521, 174, 970, 207],
               'option three'),
        region('enclosed_text_control_text_band_localized',
               [522, 174, 886, 207], 'option three'),
        region('enclosed_text_control_text_band', [521, 209, 970, 233],
               'option four', strict=False),
        region('unboxed_source_text_text_band', [0, 256, 985, 283],
               'Sentence after the blank'),
        region('unboxed_source_text_text_band_localized',
               [50, 256, 683, 283], 'Sentence after the blank'),
    ]
    if unreadable:
        bands.append(region('enclosed_text_control_text_band',
                            [521, 238, 970, 258], ''))
        bands.append(region('enclosed_text_control_text_band',
                            [521, 258, 970, 278], ''))
    return {
        'question_key': key,
        'source_number': 2,
        'stem': ('Select the answer that correctly completes the sentence. '
                 'To answer, select the appropriate choice in the answer '
                 'area.'),
        'options': {},
        'question_images': ['q.png'],
        'source_region_candidates': bands,
    }


def unboxed_stack_item(key='qZ'):
    """No control chrome: a vertical option stack between sentence lines."""
    bands = [
        region('unboxed_source_text_text_band', [0, 7, 911, 27],
               'Answer Area'),
        region('unboxed_source_text_text_band_localized', [3, 7, 105, 27],
               'Answer Area'),
        region('light_ui_text_control', [446, 44, 694, 63], ''),
        region('unboxed_source_text_text_band_localized', [56, 31, 766, 61],
               'Sentence part one'),
        region('unboxed_source_text_text_band_localized',
               [453, 70, 562, 96], 'First option'),
        region('unboxed_source_text_text_band_localized',
               [454, 107, 564, 132], 'Second option', strict=False),
        region('unboxed_source_text_text_band_localized',
               [454, 140, 652, 167], 'Third option'),
        region('unboxed_source_text_text_band_localized',
               [453, 177, 567, 203], 'Fourth option'),
        region('unboxed_source_text_text_band_localized',
               [57, 175, 452, 196], 'Sentence part two'),
    ]
    return {
        'question_key': key,
        'source_number': 3,
        'stem': 'Select the answer that correctly completes the sentence.',
        'options': {},
        'question_images': ['q.png'],
        'source_region_candidates': bands,
    }


def stacked_controls_item(key='qW'):
    """Each control row is itself one option (expanded settings list)."""
    rows = [
        ('| First report', 'First report', 452, True),
        ('Second report', 'Second report', 491, True),
        ('Third report', 'Third report', 530, False),
    ]
    bands = []
    for raw, clean, y, strict in rows:
        bands.append(region('light_ui_text_control', [41, y, 299, y + 29],
                            raw, strict=strict))
        bands.append(region('light_ui_text_control', [43, y + 2, 295, y + 26],
                            clean, strict=strict))
    return {
        'question_key': key,
        'source_number': 4,
        'stem': ('Which report should you use? To answer, select the '
                 'appropriate report in the answer area.'),
        'options': {},
        'question_images': ['q.png'],
        'source_region_candidates': bands,
    }


def ambiguous_matrix_item(key='qV'):
    """Statement boundary gap below half the row height: must hold."""
    bands = [
        region('matrix_statement_column_text_band_localized',
               [111, 68, 991, 97], 'Statement one'),
        region('matrix_statement_column_text_band_localized',
               [112, 120, 991, 149], 'Statement two first line'),
        region('matrix_statement_column_text_band_localized',
               [111, 141, 729, 167], 'and its second line'),
        # Gap of 6 px on ~27 px rows: too tight to be certain.
        region('matrix_statement_column_text_band_localized',
               [113, 173, 991, 199], 'Statement three'),
    ]
    return {
        'question_key': key,
        'source_number': 5,
        'stem': ('For each of the following statements, select Yes if the '
                 'statement is true. Otherwise, select No.'),
        'options': {},
        'question_images': ['q.png'],
        'source_region_candidates': bands,
    }


def visual_rec(kind, ocr=None):
    return {'kind': kind, 'ocr': ocr or [], 'notes': []}


def deep(thing):
    return copy.deepcopy(thing)
