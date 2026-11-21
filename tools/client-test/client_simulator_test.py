#!/usr/bin/env python3
"""Client-side test of site v2 questions in the CertPassly timed exam simulator.

Drives the real simulator pages of a THROWAWAY local site copy in headless
Chromium as a learner: for every question type it checks the render, works the
interaction (radio, checkbox, drop-down, grid radio, pointer drag for ordering,
categorization and drag_drop, hotspot list and image click), saves a correct
answer in one attempt and a near-miss wrong answer in a second attempt, submits
both and reads the score and per-item verdict the results page shows. A short
practice session on a real exam is run too.

Only 127.0.0.1 hosts are allowed; never point it at production. The site DB is
read only to map question ids to question keys and to cross-check grading.

Usage:
  python3 client_simulator_test.py --base http://127.0.0.1:8761 --db /path/sandbox.sqlite \
      --fixture-site FIXTURE.site-format.v2.json --fixture-slug vendor-QTYPE-FIXTURE \
      [--session-site AB-730.site-format.v2.json --session-slug microsoft-AB-730 --session-count 10] \
      --out /workspace/qtypes/client-test
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

SINGLE = {'single_choice', 'true_false', 'image_based_choice', 'hotspot_single', 'scenario_standalone', 'case_study_group'}
SETS = {'multiple_select', 'hotspot_multi'}
MATRIX = {'yes_no_matrix', 'single_choice_matrix'}
DRAG = {'categorization', 'drag_drop'}


def first(v):
    if isinstance(v, list):
        return v[0] if v else None
    if isinstance(v, dict):
        return next(iter(v.values()), None)
    return v


def site_index(path):
    doc = json.loads(Path(path).read_text(encoding='utf-8'))
    return {q['question_key']: q for q in doc['questions']}, doc


def ids_for(q):
    """Values a single or set answer can take, from the learner payload."""
    L = q['learner']
    regions = (L.get('interaction') or {}).get('hotspot_regions')
    if regions:
        return [r['id'] for r in regions]
    return [str(i) for i in range(len(L.get('choices') or []))]


def plan(q, wrong=False):
    """What to set in the UI: a list of (kind, name, value)."""
    t = q['type']
    key = q['answer']['answer_key']
    L = q['learner']
    inter = L.get('interaction') or {}
    if t in SINGLE:
        v = str(first(key))
        if wrong:
            v = next(x for x in ids_for(q) if x != v)
        return [('check', 'sf_response', v)]
    if t in SETS:
        vals = [str(x) for x in key]
        if wrong:
            vals = vals[1:] if len(vals) > 1 else vals + [next(x for x in ids_for(q) if x not in vals)]
        return [('check', 'sf_response[]', v) for v in vals]
    if t in MATRIX:
        cols = [c['id'] for c in inter['matrix']['columns']]
        items = list(key.items())
        if wrong:
            r, c = items[0]
            items[0] = (r, next(x for x in cols if x != c))
        return [('check', 'sf_response[%s]' % r, c) for r, c in items]
    if t == 'inline_dropdown' and L.get('choices'):
        # site dropdown component: one select over learner.choices, value = index
        v = str(first(key))
        if wrong:
            v = next(x for x in ids_for(q) if x != v)
        return [('select', 'sf_response', v)]
    if t == 'inline_dropdown':
        blanks = inter['cloze']['blanks']
        v = first(key)
        if wrong:
            v = next(o['id'] for o in blanks[0]['options'] if o['id'] != v)
        return [('select', 'sf_response', v)]
    if t == 'multi_blank_dropdown':
        opts = {b['id']: [o['id'] for o in b['options']] for b in inter['cloze']['blanks']}
        items = list(key.items())
        if wrong:
            b, v = items[0]
            items[0] = (b, next(x for x in opts[b] if x != v))
        return [('select', 'sf_response[%s]' % b, v) for b, v in items]
    if t == 'ordering':
        pos = {str(item): p + 1 for p, item in enumerate(key)}
        if wrong:
            a, b = list(pos)[:2]
            pos[a], pos[b] = pos[b], pos[a]
        return [('order', 'sf_response[%s]' % i, str(p)) for i, p in pos.items()]
    if t in DRAG or t == 'matching':
        items = [(str(i), str(v)) for i, v in (key.items() if isinstance(key, dict) else enumerate(key))]
        if wrong:
            i, v = items[0]
            n = len(inter.get('drag_slots') or []) or len({p[1] for p in inter.get('matching_pairs') or []})
            items[0] = (i, next(str(x) for x in range(n) if str(x) != v))
        kind = 'drag' if t in DRAG else 'select'
        return [(kind, 'sf_response[%s]' % i, v) for i, v in items]
    return []


class Run:
    def __init__(self, args):
        self.a = args
        self.out = Path(args.out)
        (self.out / 'shots').mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect('file:%s?mode=ro' % args.db, uri=True)
        self.console = []
        self.net_errors = []
        self.findings = []

    # ---------- browser helpers ----------
    def login(self, ctx):
        pg = ctx.new_page()
        pg.goto(self.a.base + '/login')
        pg.fill('input[name=email]', self.a.email)
        pg.fill('input[name=password]', self.a.password)
        pg.click('button[type=submit]')
        pg.wait_for_load_state('networkidle')
        if '/login' in pg.url:
            raise SystemExit('login failed: ' + pg.inner_text('body')[:300])
        return pg

    def start(self, pg, slug, count):
        pg.goto('%s/app/exams/%s/mock?count=%d' % (self.a.base, slug, count))
        pg.wait_for_load_state('networkidle')
        if '/app/exam/session/' not in pg.url:
            raise SystemExit('mock did not start: %s' % pg.url)
        return pg.url.rstrip('/').split('/')[-1]

    def questions(self, pg, uuid):
        out, page = [], 0
        while True:
            d = pg.request.get('%s/app/exam/session/%s/questions?page=%d' % (self.a.base, uuid, page),
                               headers={'Accept': 'application/json'}).json()
            out += d['questions']
            if len(out) >= d['total'] or not d['questions']:
                return out
            page += 1

    def key_of(self, qid):
        r = self.db.execute('select question_key from questions where id=?', (qid,)).fetchone()
        return r[0] if r else None

    def goto_index(self, pg, i):
        # the navigator buttons are numbered; fall back to Next clicks
        for _ in range(200):
            cur = pg.evaluate("() => { const r = document.querySelector('[x-data^=mockExamSimulator]'); return (window.Alpine && r) ? Alpine.$data(r).currentIndex : null }")
            if cur is None:
                raise SystemExit('cannot read the simulator position')
            if cur == i:
                break
            if cur is not None and cur > i:
                pg.get_by_role('button', name=re.compile('Previous')).first.click()
            else:
                pg.get_by_role('button', name=re.compile('Next Question')).first.click()
            pg.wait_for_timeout(250)
        pg.wait_for_function("() => { const p = document.querySelector('[data-testid=site-format-response]'); return p && p.offsetParent !== null && p.innerHTML.trim().length > 0 }", timeout=10000)
        pg.wait_for_timeout(300)

    def render_check(self, pg, q):
        panel = pg.locator('[data-testid=site-format-response]')
        t = q['type']
        L = q['learner']
        inter = L.get('interaction') or {}
        res = {'visible': panel.is_visible()}
        text = panel.inner_text()
        stem = ' '.join(n.get('text', '') for p in L.get('stem') or [] for n in p.get('content') or [])
        res['stem_shown'] = bool(stem) and stem.split()[0] in text
        if L.get('choices') and t not in DRAG:
            res['choices_expected'] = len(L['choices'])
            res['choices_shown'] = (panel.locator('select option:not([value=""])').count() if t == 'inline_dropdown'
                                    else panel.locator('input[type=radio],input[type=checkbox]').count())
        if t in DRAG:
            res['items_shown'] = panel.locator('select[data-sf-item]').count()
            res['items_expected'] = len(L.get('choices') or [])
            res['drop_zones'] = panel.locator('[data-sf-drop]').count()
        if t in MATRIX:
            res['grid_rows_expected'] = len(inter['matrix']['rows'])
            res['grid_cells_shown'] = panel.locator('input[type=radio]').count()
            res['grid_cells_expected'] = len(inter['matrix']['rows']) * len(inter['matrix']['columns'])
        if 'cloze' in inter:
            res['blanks_expected'] = len(inter['cloze']['blanks'])
            res['blanks_shown'] = panel.locator('select').count()
        if t == 'ordering':
            res['ordering_items'] = panel.locator('select[data-sf-item]').count()
        if t == 'matching':
            res['matching_selects'] = panel.locator('select').count()
        media = L.get('media') or []
        imgs = panel.locator('img')
        res['images_expected'] = len(media)
        res['images_shown'] = imgs.count()
        res['images_loaded'] = pg.evaluate("() => Array.from(document.querySelectorAll('[data-testid=site-format-response] img')).filter(i => i.complete && i.naturalWidth > 0).length")
        blocks = L.get('content_blocks') or []
        res['content_blocks_expected'] = len(blocks)
        if blocks:
            btxt = ' '.join(n.get('text', '') for b in blocks for p in (b.get('content') or []) if isinstance(p, dict) for n in p.get('content') or [])
            res['content_block_text_shown'] = bool(btxt.strip()) and btxt.split()[0] in text
        # stem shown twice (page prompt plus component legend)
        res['stem_repeated_on_page'] = pg.locator('main').inner_text().count(stem[:40]) > 1 if stem else False
        ok = res['visible'] and res['stem_shown']
        for a, b in (('choices_shown', 'choices_expected'), ('items_shown', 'items_expected'), ('grid_cells_shown', 'grid_cells_expected'),
                     ('blanks_shown', 'blanks_expected'), ('images_loaded', 'images_expected')):
            if a in res and res[a] < res[b]:
                ok = False
        if blocks and not res.get('content_block_text_shown'):
            ok = False
        res['ok'] = ok
        return res

    def drag(self, pg, panel, handle_sel, zone_sel):
        h = panel.locator(handle_sel).first
        z = panel.locator(zone_sel).first
        h.scroll_into_view_if_needed()
        hb, zb = h.bounding_box(), z.bounding_box()
        if not hb or not zb:
            return False
        pg.mouse.move(hb['x'] + hb['width'] / 2, hb['y'] + hb['height'] / 2)
        pg.mouse.down()
        pg.mouse.move(zb['x'] + zb['width'] / 2, zb['y'] + zb['height'] / 2, steps=8)
        pg.mouse.up()
        pg.wait_for_timeout(200)
        return True

    def interact(self, pg, q, steps):
        panel = pg.locator('[data-testid=site-format-response]')
        t = q['type']
        info = {'method': [], 'ok': True}
        if t == 'hotspot_single' or t == 'hotspot_multi':
            # try the image first: a click inside the region
            regions = {r['id']: r for r in q['learner']['interaction']['hotspot_regions']}
            img = panel.locator('img').first
            box = img.bounding_box()
            rid = steps[0][2]
            x, y, w, h = regions[rid]['coords']
            pg.mouse.click(box['x'] + (x + w / 2) * box['width'], box['y'] + (y + h / 2) * box['height'])
            pg.wait_for_timeout(200)
            info['image_click_selects_region'] = panel.locator('input[value="%s"]' % rid).is_checked()
        if t == 'ordering':
            # pointer drag: put item 'first-by-key' where it belongs using drag handles
            target = {int(n[len('sf_response['):-1]): int(v) for _, n, v in steps}
            for pos in range(1, len(target) + 1):
                item = next(i for i, p in target.items() if p == pos)
                # current positions
                cur = [panel.locator('select[data-sf-item="%d"]' % i).input_value() for i in range(len(target))]
                order = sorted(range(len(cur)), key=lambda i: (int(cur[i]) if cur[i] else 99, i))
                to_item = order[pos - 1]
                if to_item != item:
                    self.drag(pg, panel, '[data-sf-drag="%d"]' % item, '[data-sf-drop="%d"]' % to_item)
            got = {i: panel.locator('select[data-sf-item="%d"]' % i).input_value() for i in target}
            info['drag_result'] = got
            info['method'].append('pointer drag')
            if any(str(target[i]) != got[i] for i in target):
                info['method'].append('select fallback')
                for i, p in target.items():
                    panel.locator('select[data-sf-item="%d"]' % i).select_option(str(p))
        for kind, name, value in steps:
            try:
                self._step(pg, panel, kind, name, value, info)
            except Exception as e:  # a control the plan needs is missing in the page
                info['ok'] = False
                info.setdefault('errors', []).append('%s %s=%s: %s' % (kind, name, value, str(e).splitlines()[0][:160]))
        return self._verify(pg, panel, q, steps, info)

    def _step(self, pg, panel, kind, name, value, info):
        T = 4000
        if True:
            if kind == 'check':
                loc = panel.locator('input[name="%s"][value="%s"]' % (name, value))
                loc.wait_for(state='attached', timeout=T)
                if not loc.is_checked():
                    pg.locator('label[for="%s"]' % loc.get_attribute('id')).click()
                info['method'].append('click label')
            elif kind == 'select':
                panel.locator('select[name="%s"]' % name).select_option(value, timeout=T)
                info['method'].append('select option')
            elif kind == 'drag':
                item = name[len('sf_response['):-1]
                zone = '[data-sf-drop="%s"]' % value
                dragged = False
                if panel.locator(zone).count():
                    dragged = self.drag(pg, panel, '[data-sf-drag="%s"]' % item, zone)
                sel = panel.locator('select[name="%s"]' % name)
                if dragged and sel.input_value() == value:
                    info['method'].append('pointer drag')
                else:
                    info['method'].append('select fallback (drag did not set the slot)')
                    sel.select_option(value, timeout=T)

    def _verify(self, pg, panel, q, steps, info):
        t = q['type']
        # verify the controls hold the planned values
        for kind, name, value in steps:
            try:
                if kind == 'check':
                    if not panel.locator('input[name="%s"][value="%s"]' % (name, value)).is_checked(timeout=2000):
                        info['ok'] = False
                elif panel.locator('select[name="%s"]' % name).input_value(timeout=2000) != value:
                    info['ok'] = False
            except Exception:
                info['ok'] = False
        # unchecked set members must stay unchecked
        if t in SETS:
            want = {v for _, _, v in steps}
            for el in panel.locator('input[type=checkbox]').all():
                if el.is_checked() != (el.get_attribute('value') in want):
                    info['ok'] = False
        pg.wait_for_timeout(700)  # serialized saver
        return info

    def submit(self, pg, uuid):
        # The site shares one per-user throttle counter across all throttle:N,1
        # routes, so recent answer saves count against the submit limit of 10.
        # Wait out the window (recorded as a site bug).
        pg.wait_for_timeout(self.a.submit_wait * 1000)
        pg.get_by_role('button', name=re.compile('Finish Exam', re.I)).last.click()
        pg.wait_for_timeout(400)
        dlg = pg.locator('[role=dialog][aria-labelledby=exam-submit-confirm-title]')
        pg.screenshot(path=str(self.out / 'shots' / 'debug-submit-dialog.png'))
        with pg.expect_navigation(timeout=30000):
            dlg.get_by_role('button', name=re.compile('Confirm', re.I)).click()
        pg.wait_for_load_state('networkidle')
        if '/results' not in pg.url:
            pg.screenshot(path=str(self.out / 'shots' / 'debug-after-submit.png'), full_page=True)
            raise SystemExit('submit did not reach results: %s %s' % (pg.url, pg.inner_text('body')[:500]))
        pg.wait_for_load_state('networkidle')

    def results(self, pg):
        body = pg.inner_text('main') if pg.locator('main').count() else pg.inner_text('body')
        m = re.search(r'Correct Answers\s*(\d+)\s*/\s*(\d+)', body, re.I)
        items = re.findall(r'Item\s+(\d+)\s*\u2022\s*(Correct|Incorrect)', body, re.I)
        sc = re.search(r'(\d+)%\s*SCORE', body, re.I)
        return {'correct': int(m.group(1)) if m else None, 'total': int(m.group(2)) if m else None,
                'score_pct': int(sc.group(1)) if sc else None,
                'items': {int(n): v.capitalize() for n, v in items}, 'text_sample': body[:400]}

    def db_verdicts(self, uuid):
        rows = self.db.execute(
            'select aq.question_id, aq.is_correct, aq.response_json, aq.response_status from attempt_questions aq '
            'join attempts a on a.id = aq.attempt_id where a.uuid = ?', (uuid,)).fetchall()
        return {r[0]: {'is_correct': r[1], 'response': r[2], 'status': r[3]} for r in rows}

    # ---------- flows ----------
    def attempt(self, pg, slug, site, count, label, wrong_for=lambda key: False, shots=False):
        uuid = self.start(pg, slug, count)
        qs = self.questions(pg, uuid)
        rows = []
        for i, item in enumerate(qs):
            key = self.key_of(item['question_id'])
            q = site.get(key)
            row = {'index': i + 1, 'question_id': item['question_id'], 'question_key': key, 'type': item.get('type')}
            if not q or not item.get('site_format'):
                row['error'] = 'not a site v2 question in this session'
                rows.append(row)
                continue
            self.goto_index(pg, i)
            row['render'] = self.render_check(pg, q)
            wrong = wrong_for(key)
            row['answered'] = 'wrong' if wrong else 'correct'
            row['interaction'] = self.interact(pg, q, plan(q, wrong=wrong))
            if shots:
                path = self.out / 'shots' / ('%02d-%s-%s.png' % (i + 1, q['type'], label))
                pg.locator('main').screenshot(path=str(path))
                row['screenshot'] = str(path)
            rows.append(row)
        self.submit(pg, uuid)
        res = self.results(pg)
        rp = self.out / 'shots' / ('results-%s-%s.png' % (slug, label))
        pg.screenshot(path=str(rp), full_page=True)
        dbv = self.db_verdicts(uuid)
        for r in rows:
            r['ui_verdict'] = res['items'].get(r['index'])
            v = dbv.get(r['question_id'], {})
            r['db_is_correct'] = v.get('is_correct')
            r['saved_response'] = v.get('response')
        return {'uuid': uuid, 'results': res, 'results_screenshot': str(rp), 'rows': rows}

    def main(self):
        for u in (self.a.base,):
            if urlparse(u).hostname not in ('127.0.0.1', 'localhost') or urlparse(u).port in (8330,):
                raise SystemExit('refusing: only a local throwaway site (not 8330)')
        report = {'base': self.a.base}
        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context(viewport={'width': 1366, 'height': 1000})
            pg = self.login(ctx)
            pg.on('console', lambda m: self.console.append('%s: %s' % (m.type, m.text)) if m.type in ('error', 'warning') else None)
            pg.on('response', lambda r: self.net_errors.append('%s %s' % (r.status, r.url)) if r.status >= 400 else None)
            fx, _ = site_index(self.a.fixture_site)
            n = len(fx)
            report['fixture_correct'] = self.attempt(pg, self.a.fixture_slug, fx, n, 'correct', shots=True)
            report['fixture_wrong'] = self.attempt(pg, self.a.fixture_slug, fx, n, 'wrong', wrong_for=lambda k: True)
            if self.a.session_site:
                ss, _ = site_index(self.a.session_site)
                # half right, half near-miss wrong, so the result page must show a mixed score
                keys = sorted(ss)
                wrong = set(keys[1::2])
                report['session'] = self.attempt(pg, self.a.session_slug, ss, self.a.session_count, 'session',
                                                 wrong_for=lambda k: k in wrong, shots=False)
            b.close()
        report['console'] = sorted(set(self.console))[:50]
        report['http_errors'] = sorted(set(self.net_errors))[:50]
        (self.out / 'client-test-report.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
        return report


def summarize(report):
    by_type = {}
    c = {r['question_key']: r for r in report['fixture_correct']['rows']}
    w = {r['question_key']: r for r in report['fixture_wrong']['rows']}
    for k, r in c.items():
        t = r['type']
        rw = w.get(k, {})
        s = by_type.setdefault(t, {'render': True, 'interaction': True, 'correct_scored': True, 'wrong_rejected': True, 'keys': []})
        s['keys'].append(k)
        s['render'] &= bool((r.get('render') or {}).get('ok'))
        s['interaction'] &= bool((r.get('interaction') or {}).get('ok')) and bool((rw.get('interaction') or {}).get('ok'))
        # Per item verdict from the attempt rows; the results page lists items in a
        # different order than the session, so its Item N labels are not matched by
        # index. The UI totals (Correct Answers X / Y) are checked in the report.
        s['correct_scored'] &= r.get('db_is_correct') == 1
        s['wrong_rejected'] &= rw.get('db_is_correct') == 0
    return by_type


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8761')
    ap.add_argument('--db', required=True)
    ap.add_argument('--email', default='learner@client-test.local')
    ap.add_argument('--password', default='client-test-only')
    ap.add_argument('--fixture-site', required=True)
    ap.add_argument('--fixture-slug', required=True)
    ap.add_argument('--session-site')
    ap.add_argument('--session-slug')
    ap.add_argument('--session-count', type=int, default=10)
    ap.add_argument('--out', required=True)
    ap.add_argument('--submit-wait', type=int, default=62, help='seconds to wait before submit (site throttle)')
    a = ap.parse_args()
    rep = Run(a).main()
    summ = summarize(rep)
    print(json.dumps({'by_type': summ,
                      'fixture_correct_score': rep['fixture_correct']['results'].get('correct'),
                      'fixture_wrong_score': rep['fixture_wrong']['results'].get('correct'),
                      'session_score': (rep.get('session') or {}).get('results', {}).get('correct'),
                      'session_total': (rep.get('session') or {}).get('results', {}).get('total')}, indent=1))
