#!/usr/bin/env python3
"""Build the TEST-ONLY question-type fixture PDF and its truth file.

TEST FIXTURE. NOT A REAL EXAM. NEVER PROMOTE. The questions are synthetic and
exist only so the PDF to site v2 path can be checked for every supported
question type. The truth file (truth.json) is written from the same spec that
draws the PDF, so a test can compare what the pipeline read with what was
drawn.

Needs reportlab and Pillow (local only; CI uses the committed PDF and truth).
Usage: python make_fixtures.py [out_dir]
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FONT_B = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
EXAM = 'QTYPE-FIXTURE'
GREY = (150, 150, 150)
RADIO = (110, 110, 110)


def font(size, bold=False):
    return ImageFont.truetype(FONT_B if bold else FONT, size)


def new_img(w, h):
    im = Image.new('RGB', (w, h), 'white')
    return im, ImageDraw.Draw(im)


def answer_area_label(d):
    d.text((14, 10), 'Answer Area', fill='black', font=font(20, True))


# ------------------------------------------------------------------ image builders

def grid_images(headers, rows, key, col_x, text_x=40, row_h=64, top=110):
    """A grid of radio controls. key: list of column index per row."""
    W, H = 980, top + row_h * len(rows) + 30
    out = []
    for marked in (False, True):
        im, d = new_img(W, H)
        answer_area_label(d)
        for h, x in zip(headers, col_x):
            tw = d.textlength(h, font=font(20, True))
            d.text((x - tw / 2, top - 52), h, fill='black', font=font(20, True))
        for i, (text, k) in enumerate(zip(rows, key)):
            y = top + i * row_h
            d.text((text_x, y), text, fill='black', font=font(20))
            picked = k if isinstance(k, (list, tuple)) else [k]
            for j, x in enumerate(col_x):
                cy = y + 13
                d.ellipse((x - 10, cy - 10, x + 10, cy + 10), outline=RADIO, width=2)
                if marked and j in picked:
                    d.ellipse((x - 5, cy - 5, x + 5, cy + 5), fill='black')
                    d.rectangle((x - 17, cy - 17, x + 17, cy + 17), outline='black', width=3)
        out.append(im)
    return out


def yes_no_images(spec):
    rows = [r['text'] for r in spec['rows']]
    key = [0 if r['answer'] == 'yes' else 1 for r in spec['rows']]
    ims = grid_images(['Yes', 'No'], rows, key, [820, 920], text_x=40)
    for im in ims:
        ImageDraw.Draw(im).text((40, 58), 'Statements', fill='black', font=font(20, True))
    return ims


def matrix_images(spec):
    rows = [r['text'] for r in spec['rows']]
    cols = spec['columns']
    key = [cols.index(r['answer']) for r in spec['rows']]
    return grid_images(cols, rows, key, [640, 770, 900], text_x=40)


def multi_matrix_images(spec):
    rows = [r['text'] for r in spec['rows']]
    cols = spec['columns']
    key = []
    for r in spec['rows']:
        ans = r['answer'] if isinstance(r['answer'], (list, tuple)) else [r['answer']]
        key.append([cols.index(a) for a in ans])
    return grid_images(cols, rows, key, [640, 770, 900], text_x=40)


def dropdown_images(spec):
    """Each sentence line: text, a closed drop-down box, then its open list below."""
    W = 980
    line_gap = 30
    blocks = []
    y = 60
    for part in spec['sentences']:
        list_h = 38 * len(part['choices']) + 10
        blocks.append((y, part, list_h))
        y += 40 + list_h + line_gap
    H = y + 10
    out = []
    for marked in (False, True):
        im, d = new_img(W, H)
        answer_area_label(d)
        for (y, part, list_h) in blocks:
            f = font(20)
            d.text((40, y + 6), part['before'], fill='black', font=f)
            bx = 40 + int(d.textlength(part['before'], font=f)) + 16
            bw = 330
            d.rectangle((bx, y, bx + bw, y + 34), outline=GREY, width=2)
            ax = bx + bw - 24
            d.polygon([(ax, y + 13), (ax + 12, y + 13), (ax + 6, y + 21)], fill=(60, 60, 60))
            if part.get('after'):
                d.text((bx + bw + 14, y + 6), part['after'], fill='black', font=f)
            ly = y + 36
            d.rectangle((bx, ly, bx + bw, ly + list_h), outline=GREY, width=2)
            for i, ch in enumerate(part['choices']):
                cy = ly + 8 + i * 38
                d.text((bx + 10, cy), ch, fill='black', font=f)
                if marked and ch == part['answer']:
                    d.rectangle((bx + 4, cy - 5, bx + 8 + d.textlength(ch, font=f) + 8, cy + 30), outline='black', width=3)
        out.append(im)
    return out


def hotspot_images(spec):
    W, H = 900, 420
    boxes = spec['regions']
    out = []
    for marked in (False, True):
        im, d = new_img(W, H)
        for r in boxes:
            x, y, w, h = r['px']
            d.rectangle((x, y, x + w, y + h), outline=GREY, width=2)
            f = font(22)
            tw = d.textlength(r['label'], font=f)
            d.text((x + (w - tw) / 2, y + h / 2 - 14), r['label'], fill='black', font=f)
            if marked and r['label'] in spec['answer']:
                d.rectangle((x - 10, y - 10, x + w + 10, y + h + 10), outline='black', width=4)
        out.append(im)
    return out


def exhibit_image(lines):
    W, H = 700, 40 + 40 * len(lines)
    im, d = new_img(W, H)
    for i, t in enumerate(lines):
        d.text((24, 20 + i * 40), t, fill='black', font=font(22))
    return im


# ------------------------------------------------------------------ the spec

HOT_REGIONS = [
    {'label': 'Web Server', 'px': (60, 50, 300, 120)},
    {'label': 'App Server', 'px': (500, 50, 300, 120)},
    {'label': 'Database', 'px': (60, 250, 300, 120)},
    {'label': 'Cache', 'px': (500, 250, 300, 120)},
]

SPEC = [
    {'type': 'single_choice',
     'stem': ['Which service stores files as objects in buckets?'],
     'options': ['Block storage', 'Object storage', 'A message queue', 'A load balancer'], 'answer': 'B'},
    {'type': 'multiple_select',
     'stem': ['Which two items are input devices?', 'Each correct answer presents a complete solution.'],
     'options': ['Keyboard', 'Monitor', 'Mouse', 'Printer'], 'answer': 'AC'},
    {'type': 'true_false',
     'stem': ['A solid state drive has no moving parts.'],
     'options': ['True', 'False'], 'answer': 'A'},
    {'type': 'image_based_choice',
     'stem': ['Refer to the exhibit.', 'What is the state of the server?'],
     'exhibit': ['Server name: alpha', 'Status: Stopped', 'Region: East'],
     'options': ['Running', 'Starting', 'Stopped', 'Deleted'], 'answer': 'C'},
    {'type': 'scenario_standalone',
     'stem': ['Scenario: A team runs a web shop on one server.', 'The server is slow at peak times.',
              'What should the team do first?'],
     'options': ['Measure the load on the server', 'Buy a second shop', 'Delete old orders', 'Turn off the server'],
     'answer': 'A'},
    {'type': 'yes_no_matrix',
     'stem': ['HOTSPOT -', 'For each of the following statements, select Yes if the statement is true.',
              'Otherwise, select No.'],
     'rows': [{'text': 'A router forwards packets between networks.', 'answer': 'yes'},
              {'text': 'A switch stores files for users.', 'answer': 'no'},
              {'text': 'A firewall can block network traffic.', 'answer': 'yes'}]},
    {'type': 'single_choice_matrix',
     'stem': ['HOTSPOT -', 'For each requirement, select the service to use.'],
     'columns': ['Storage', 'Compute', 'Network'],
     'rows': [{'text': 'Run a batch job every night.', 'answer': 'Compute'},
              {'text': 'Keep backup copies of files.', 'answer': 'Storage'},
              {'text': 'Connect two office sites.', 'answer': 'Network'}]},
    {'type': 'inline_dropdown',
     'stem': ['HOTSPOT -', 'Select the answer that correctly completes the sentence.'],
     'sentences': [{'before': 'To keep files, you should use', 'after': 'storage.',
                    'choices': ['queue', 'object', 'compute'], 'answer': 'object'}]},
    {'type': 'multi_blank_dropdown',
     'stem': ['HOTSPOT -', 'To answer, select the appropriate options in the answer area.'],
     'sentences': [{'before': 'A backup copy should be', 'after': '',
                    'choices': ['stored offsite', 'deleted daily'], 'answer': 'stored offsite'},
                   {'before': 'A restore test should run', 'after': '',
                    'choices': ['never', 'every month'], 'answer': 'every month'}]},
    {'type': 'ordering',
     'stem': ['You need to publish a web page.', 'Arrange the steps in the correct order.'],
     'options': ['Upload the files', 'Write the page', 'Test the page', 'Share the link'],
     'answer': 'B, C, A, D'},
    {'type': 'matching',
     'stem': ['Match each device to its job.', '1. Printer', '2. Scanner', '3. Speaker'],
     'options': ['Plays sound', 'Makes paper copies', 'Reads paper pages'],
     'answer': '1-B, 2-C, 3-A'},
    {'type': 'categorization',
     'stem': ['Categorize each item as hardware or software.', '1. Keyboard', '2. Web browser',
              '3. Text editor', '4. Hard drive'],
     'options': ['Hardware', 'Software'],
     'answer': '1-A, 2-B, 3-B, 4-A'},
    {'type': 'drag_drop',
     'stem': ['DRAG DROP -', 'Drag each tool to the task it does.', '1. Hammer', '2. Saw', '3. Ruler'],
     'options': ['Measure a board', 'Drive a nail', 'Cut a board'],
     'answer': '1-B, 2-C, 3-A'},
    {'type': 'hotspot_single',
     'stem': ['HOTSPOT -', 'In the diagram, select the part that keeps the data.'],
     'regions': HOT_REGIONS, 'answer': ['Database']},
    {'type': 'hotspot_multi',
     'stem': ['HOTSPOT -', 'In the diagram, select the parts that run program code.'],
     'regions': HOT_REGIONS, 'answer': ['Web Server', 'App Server']},
    {'type': 'case_study_group',
     'stem': ['Case Study: Fabrikam', 'Fabrikam is a small company with two offices.',
              'It plans to move its file server to the cloud.',
              'Question: Which service should Fabrikam use for the files?'],
     'options': ['A message queue', 'Object storage', 'A load balancer'], 'answer': 'B'},
    {'type': 'case_study_group',
     'stem': ['Case Study: Fabrikam', 'Question: What should Fabrikam do first?'],
     'options': ['List the files to move', 'Close one office', 'Buy new printers'], 'answer': 'A'},
    {'type': None, 'expect_hold': 'reviewer-graded type lab_task',
     'stem': ['LAB -', 'Simulation: sign in to the lab and set up the network as described.'],
     'options': [], 'answer': ''},
    {'type': None, 'expect_hold': 'ordering answer does not use every step',
     'stem': ['Arrange the three steps you need in the correct order.'],
     'options': ['Plan', 'Build', 'Wait', 'Test'], 'answer': 'A, B, D'},
    {'type': 'multi_select_matrix',
     'stem': ['HOTSPOT -', 'For each requirement, select all services that apply.',
              'You may select more than one column.'],
     'columns': ['Storage', 'Compute', 'Network'],
     'rows': [{'text': 'Run a batch job every night.', 'answer': ['Compute']},
              {'text': 'Keep backup copies of files and serve them.', 'answer': ['Storage', 'Network']},
              {'text': 'Connect two office sites.', 'answer': ['Network']}]},
    {'type': 'text_cloze',
     'stem': ['Type the missing word in each blank.',
              'A ______ stores objects in buckets.',
              'A ______ forwards packets between networks.'],
     'answer': '1. object 2. router'},
    {'type': 'short_text',
     'stem': ['Type a short answer in the box.',
              'What protocol assigns addresses automatically?'],
     'answer': 'DHCP (also accept: Dynamic Host Configuration Protocol)'},
    {'type': 'numeric',
     'stem': ['Enter the number. The accepted tolerance is 0.5. The unit is ms.',
              'A signal takes 10 ms to travel the wire. What is the delay?'],
     'answer': '10 ms'},
    {'type': None, 'expect_hold': 'does not give a value for every blank',
     'stem': ['Type the missing word in each blank.',
              'A ______ stores objects.',
              'A ______ forwards packets.'],
     'answer': '1. object'},
    {'type': None, 'expect_hold': 'no number in the answer line',
     'stem': ['Enter the number.', 'What is the delay?'],
     'answer': 'about ten'},
    {'type': None, 'expect_hold': 'no answer in the PDF',
     'stem': ['Type a short answer in the box.', 'What is the name of the protocol?'],
     'answer': ''},
    {'type': None, 'expect_hold': 'answer key is not certain',
     'stem': ['HOTSPOT -', 'For each requirement, select all services that apply.'],
     'columns': ['Storage', 'Compute', 'Network'],
     'rows': [{'text': 'Run a batch job every night.', 'answer': ['Compute']},
              {'text': 'Keep backup copies of files.', 'answer': []}]},
    {'type': None, 'expect_hold': 'reviewer-graded type lab_task',
     'stem': ['LAB -', 'Sign in to the lab and create a user account.'],
     'options': ['Create the account in the portal', 'Delete the account',
                 'Reset the password', 'Assign a licence'],
     'answer': 'A'},
]


def truth_for(i, s):
    letters = 'ABCDEF'
    t = {'question_key': 'q%03d' % (i + 1), 'type': s['type']}
    if s.get('expect_hold'):
        t['held'] = True
        t['hold_reason_contains'] = s['expect_hold']
        return t
    typ = s['type']
    if typ in ('single_choice', 'true_false', 'image_based_choice', 'scenario_standalone', 'case_study_group'):
        t['answer_key'] = [letters.index(s['answer'])]
        t['choices'] = s['options']
    elif typ == 'multiple_select':
        t['answer_key'] = [letters.index(c) for c in s['answer']]
        t['choices'] = s['options']
    elif typ in ('yes_no_matrix',):
        t['rows'] = [r['text'] for r in s['rows']]
        t['answer_key'] = {'r%d' % (j + 1): r['answer'] for j, r in enumerate(s['rows'])}
    elif typ == 'single_choice_matrix':
        t['rows'] = [r['text'] for r in s['rows']]
        t['columns'] = s['columns']
        t['answer_key'] = {'r%d' % (j + 1): 'c%d' % (s['columns'].index(r['answer']) + 1) for j, r in enumerate(s['rows'])}
    elif typ == 'multi_select_matrix':
        t['rows'] = [r['text'] for r in s['rows']]
        t['columns'] = s['columns']
        t['answer_key'] = {
            'r%d' % (j + 1): ['c%d' % (s['columns'].index(a) + 1) for a in (
                r['answer'] if isinstance(r['answer'], (list, tuple)) else [r['answer']])]
            for j, r in enumerate(s['rows'])
        }
    elif typ == 'text_cloze':
        # two blank sentences after the instruction line
        t['answer_key'] = {'blank1': 'object', 'blank2': 'router'}
    elif typ == 'short_text':
        t['answer_key'] = {'accepted': ['DHCP', 'Dynamic Host Configuration Protocol'], 'match': 'text'}
    elif typ == 'numeric':
        t['answer_key'] = {'value': '10', 'unit': 'ms', 'tolerance': '0.5', 'tolerance_type': 'absolute'}
    elif typ in ('inline_dropdown', 'multi_blank_dropdown'):
        segs = []
        key = {}
        for j, p in enumerate(s['sentences']):
            bid = 'blank%d' % (j + 1)
            segs.append(p['before'])
            segs.append('[%s]' % bid)
            if p.get('after'):
                segs.append(p['after'])
            key[bid] = '%s_o%d' % (bid, p['choices'].index(p['answer']) + 1)
        t['cloze'] = ' '.join(segs)
        t['answer_key'] = key
        t['blank_options'] = {'blank%d' % (j + 1): p['choices'] for j, p in enumerate(s['sentences'])}
    elif typ == 'ordering':
        order = [letters.index(c) for c in s['answer'].replace(',', ' ').split()]
        t['ordering'] = s['options']
        t['answer_key'] = order
    elif typ in ('matching', 'categorization', 'drag_drop'):
        items = [l.split('. ', 1)[1] for l in s['stem'] if l[:1].isdigit()]
        pairs = [p.strip().split('-') for p in s['answer'].split(',')]
        if typ == 'matching':
            targets = sorted(s['options'], key=lambda x: x.lower())
            t['answer_key'] = {str(int(n) - 1): str(targets.index(s['options'][letters.index(L)])) for n, L in pairs}
            t['matching_pairs'] = [[items[int(n) - 1], s['options'][letters.index(L)]] for n, L in pairs]
        else:
            t['answer_key'] = {str(int(n) - 1): str(letters.index(L)) for n, L in pairs}
            t['items'] = items
            t['slots'] = s['options']
    elif typ in ('hotspot_single', 'hotspot_multi'):
        order = sorted(range(len(s['regions'])), key=lambda j: (s['regions'][j]['px'][1], s['regions'][j]['px'][0]))
        ids = {s['regions'][j]['label']: 'h%d' % (n + 1) for n, j in enumerate(order)}
        t['regions'] = {ids[r['label']]: r['label'] for r in s['regions']}
        picked = sorted((ids[a] for a in s['answer']), key=lambda x: int(x[1:]))
        t['answer_key'] = picked[0] if typ == 'hotspot_single' else picked
    return t


def build(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    img_dir = os.path.join(out_dir, '_img')
    os.makedirs(img_dir, exist_ok=True)
    pdf = os.path.join(out_dir, 'TEST-FIXTURE-question-types.pdf')
    c = canvas.Canvas(pdf, pagesize=A4)
    c.setTitle('TEST FIXTURE - synthetic question types - not a real exam - never promote')
    W, H = A4
    c.setFont('Helvetica-Bold', 16)
    c.drawString(50, H - 80, 'TEST FIXTURE - SYNTHETIC QUESTION TYPES')
    c.setFont('Helvetica', 12)
    c.drawString(50, H - 110, 'Not a real exam. For pipeline tests only. Never promote.')
    c.showPage()
    truth = []
    for i, s in enumerate(SPEC):
        y = H - 60
        c.setFont('Helvetica', 11)

        def line(t, yy):
            c.drawString(50, yy, t)
            return yy - 18
        y = line('QUESTION %d' % (i + 1), y)
        for t in s['stem']:
            y = line(t, y)
        q_img = a_img = None
        typ = s['type']
        if typ == 'image_based_choice':
            q_img = exhibit_image(s['exhibit'])
        elif typ == 'yes_no_matrix':
            q_img, a_img = yes_no_images(s)
        elif typ == 'single_choice_matrix':
            q_img, a_img = matrix_images(s)
        elif typ == 'multi_select_matrix' or (s.get('columns') and s.get('rows') and typ is None):
            q_img, a_img = multi_matrix_images(s)
        elif typ in ('inline_dropdown', 'multi_blank_dropdown'):
            q_img, a_img = dropdown_images(s)
        elif typ in ('hotspot_single', 'hotspot_multi'):
            q_img, a_img = hotspot_images(s)

        def place(im, name, yy):
            p = os.path.join(img_dir, name)
            im.save(p)
            w = 480.0
            h = w * im.size[1] / im.size[0]
            c.drawImage(p, 50, yy - h, width=w, height=h)
            return yy - h - 16
        if q_img is not None:
            y = place(q_img, 'q%03d-question.png' % (i + 1), y - 4)
        for j, o in enumerate(s.get('options') or []):
            y = line('%s. %s' % ('ABCDEF'[j], o), y)
        y = line('Correct Answer: %s' % s['answer'] if s.get('answer') else 'Correct Answer:', y)
        if a_img is not None:
            y = place(a_img, 'q%03d-answer.png' % (i + 1), y - 4)
        y = line('Section: (none)', y)
        c.showPage()
        truth.append(truth_for(i, s))
    c.save()
    doc = {'exam_code': EXAM, 'test_only': True, 'never_promote': True,
           'note': 'TEST FIXTURE. Synthetic questions, one per supported type, plus held cases. Staging types stay draft only.',
           'questions': truth}
    with open(os.path.join(out_dir, 'truth.json'), 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
        fh.write('\n')
    for f in os.listdir(img_dir):
        os.remove(os.path.join(img_dir, f))
    os.rmdir(img_dir)
    return pdf


if __name__ == '__main__':
    print(build(sys.argv[1] if len(sys.argv) > 1 else HERE))
