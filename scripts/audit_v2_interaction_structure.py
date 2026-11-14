#!/usr/bin/env python3
"""Fail-closed technical-only V2 interaction audit; never approves PDF fidelity or publishing."""
from __future__ import annotations
import argparse
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re

QFILE = re.compile(r'^(q\d{3})\.v(\d+)\.json$')
SLOTS = re.compile(r'\{\{([A-Za-z][A-Za-z0-9_-]*)\}\}')
PRIVATE_MEDIA = re.compile(r'answer[-_ ]?(area|review|key)|reviewer|correct[_-]?answer', re.I)
TYPES = {'single_choice', 'multiple_select', 'inline_dropdown', 'multi_blank_dropdown', 'yes_no_matrix'}
FORBIDDEN_ELEMENTS = {'script','iframe','object','embed','form','input','button','select','textarea','link','meta','base','style','svg','math','template','video','audio','source','track','canvas','foreignobject'}
FORBIDDEN_ATTRIBUTES = {'srcdoc', 'style', 'formaction', 'action', 'xlink:href', 'srcset', 'http-equiv'}
LINK_ATTRS = {'href', 'src', 'poster'}
SECRET_KEYS = {'answer', 'answer_key', 'answers', 'correct_answers', 'correct_option_ids', 'solution', 'explanation', 'per_option', 'partial_credit'}

class SafeFragment(HTMLParser):
    """Conservative HTML *audit*, not a sanitizer or browser security proof."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.errors = []
    def handle_starttag(self, tag, attrs):
        self._check(tag, attrs)
    def handle_startendtag(self, tag, attrs):
        self._check(tag, attrs)
    def _check(self, tag, attrs):
        if tag.lower() in FORBIDDEN_ELEMENTS:
            self.errors.append('unsafe HTML detected')
        for name, value in attrs:
            name = name.lower()
            if name.startswith('on') or name in FORBIDDEN_ATTRIBUTES:
                self.errors.append('unsafe HTML detected')
            if name in LINK_ATTRS:
                target = re.sub(r'[\x00-\x20\x7f]+', '', value or '').lower()
                if not (target.startswith('#') or target.startswith('/') and not target.startswith('//')):
                    self.errors.append('unsafe HTML detected')
    def handle_entityref(self, name):
        pass

def secret_paths(node, path='learner'):
    found=[]
    if isinstance(node, dict):
        for key, value in node.items():
            next_path=f'{path}.{key}'
            if key.lower() in SECRET_KEYS: found.append(next_path)
            found.extend(secret_paths(value,next_path))
    elif isinstance(node,list):
        for i,value in enumerate(node): found.extend(secret_paths(value,f'{path}[{i}]'))
    return found

def identity_list(rows, label, minimum=1):
    errors=[]
    if not isinstance(rows,list) or len(rows)<minimum:
        return [f'{label}: missing or too few elements']
    ids=set()
    for i,item in enumerate(rows):
        if not isinstance(item,dict):
            errors.append(f'{label}: invalid element {i}');continue
        ident, content=item.get('id'),item.get('text')
        if not isinstance(ident,str) or not ident.strip() or ident in ids:
            errors.append(f'{label}: missing/duplicate ID')
        if isinstance(ident,str): ids.add(ident)
        if not isinstance(content,str) or not content.strip():
            errors.append(f'{label}: missing visible text')
    return errors

def audit_one(doc, filename):
    m=QFILE.fullmatch(filename)
    key=m.group(1) if m else filename
    if not isinstance(doc,dict):
        return {'question_key':key,'type':None,'errors':['document is not an object']}
    errors=[]
    if not m or doc.get('question_key')!=key: errors.append('file ID mismatch')
    if m and (type(doc.get('version')) is not int or doc.get('version')!=int(m.group(2))):
        errors.append('file version mismatch')
    kind=doc.get('type')
    if kind not in TYPES: errors.append('unsupported interaction type')
    learner=doc.get('learner')
    if not isinstance(learner,dict):
        return {'question_key':key,'type':kind,'errors':sorted(set(errors+['missing learner payload']))}
    if secret_paths(learner): errors.append('answer material embedded in learner object')
    stem=learner.get('stem'); html=stem.get('text') if isinstance(stem,dict) else None
    if not isinstance(html,str) or not html.strip(): errors.append('missing HTML stem')
    else:
        check=SafeFragment()
        try:
            check.feed(html);check.close()
            errors.extend(check.errors)
        except (ValueError,TypeError): errors.append('invalid HTML fragment')
    interaction=learner.get('interaction')
    if not isinstance(interaction,dict):
        return {'question_key':key,'type':kind,'errors':sorted(set(errors+['missing interaction']))}
    if kind in ('single_choice','multiple_select'):
        options=interaction.get('options')
        errors.extend(identity_list(options,'options',minimum=2))
        n=interaction.get('choose_n')
        if type(n) is not int or n<1 or (isinstance(options,list) and n>len(options)):
            errors.append('invalid choose_n')
        if kind=='single_choice' and n!=1: errors.append('single_choice requires choose_n=1')
    elif kind in ('inline_dropdown','multi_blank_dropdown'):
        slots=interaction.get('slots');prompt=interaction.get('prompt_with_slots')
        if not isinstance(prompt,str) or not prompt.strip():errors.append('missing prompt_with_slots')
        if not isinstance(slots,list) or not slots:errors.append('missing slots')
        else:
            ids=[x.get('id') for x in slots if isinstance(x,dict)]
            if len(ids)!=len(slots) or not all(isinstance(i,str) and i for i in ids) or len(ids)!=len(set(str(i) for i in ids)):
                errors.append('duplicate or missing slot IDs')
            used=SLOTS.findall(prompt) if isinstance(prompt,str) else []
            if sorted(used)!=sorted(str(i) for i in ids):errors.append('slot references do not match slot definitions')
            if kind=='inline_dropdown' and len(slots)!=1:errors.append('inline dropdown must have one slot')
            for slot in slots:
                if not isinstance(slot,dict):errors.append('invalid slot entry');continue
                if slot.get('input')!='dropdown':errors.append('unsupported slot control')
                errors.extend(identity_list(slot.get('choices'),'slot choices',minimum=2))
    elif kind=='yes_no_matrix':
        errors.extend(identity_list(interaction.get('rows'),'rows'))
        errors.extend(identity_list(interaction.get('columns'),'columns',minimum=2))
    media=learner.get('media',[])
    if not isinstance(media,list):errors.append('malformed learner media')
    else:
        for item in media:
            if not isinstance(item,dict):errors.append('malformed learner media');continue
            if PRIVATE_MEDIA.search(json.dumps(item,ensure_ascii=False)):
                errors.append('reviewer/answer media leaked to learner')
            href=item.get('href')
            if not isinstance(href,str) or not href.startswith('/media/') or '..' in href or '\\' in href or '?' in href or '#' in href:
                errors.append('invalid learner media href')
    return {'question_key':key,'type':kind,'errors':sorted(set(errors))}

def audit_directory(folder,expected=89):
    paths=sorted(Path(folder).glob('*.json'))
    files=[p for p in paths if QFILE.fullmatch(p.name)]
    results=[]
    for file in files:
        try:results.append(audit_one(json.loads(file.read_text(encoding='utf-8')),file.name))
        except (json.JSONDecodeError,UnicodeError):
            results.append({'question_key':file.name[:4],'type':None,'errors':['invalid JSON']})
    keys=[r['question_key'] for r in results]
    problems=[r for r in results if r['errors']]
    return {'schema':'certpassly.v2-interaction-inventory.v2','technical_only':True,
            'source_fidelity_verified':False,'schema_validated_by_this_tool':False,
            'importer_tested':False,'answer_accuracy_assessed':False,'published':False,
            'expected':expected,'count':len(results),'unique':len(set(keys)),
            'type_counts':dict(Counter(r['type'] for r in results)),
            'problems':problems,'problem_question_count':len(problems),
            'automated_structure_pass':len(results)==expected and len(set(keys))==expected and not problems,
            'caution':'Technical heuristics only. PDF comparison, browser security, importer and accessibility require separate evidence.'}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--v2-dir',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--expected',default=89,type=int)
    opts=ap.parse_args()
    report=audit_directory(opts.v2_dir,opts.expected)
    opts.output.parent.mkdir(parents=True,exist_ok=True)
    opts.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('count','problem_question_count','automated_structure_pass')}))
    return 0 if report['automated_structure_pass'] else 2
if __name__=='__main__':raise SystemExit(main())