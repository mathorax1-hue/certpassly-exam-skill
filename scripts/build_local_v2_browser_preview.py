#!/usr/bin/env python3
"""Produce a local, learner-only AB-900 V2 interactive preview HTML.

This is an OFFLINE TEST HARNESS, NOT the CertPassly website renderer/importer.
No answer keys, explanations, meta/reference images or scoring are embedded.
"""
from __future__ import annotations
import argparse
from collections import Counter
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re

NAME=re.compile(r"^q[0-9]{3}\.v[1-9][0-9]*\.json$")
TYPES={"single_choice","multiple_select","inline_dropdown","multi_blank_dropdown","yes_no_matrix"}
SAFE_TAGS={"p","b","strong","i","em","u","ul","ol","li","table","thead","tbody","tr","th","td","code","pre","blockquote"}
VOID=set()

class Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]
        self.stack=[]
    def handle_starttag(self,tag,attrs):
        if tag not in SAFE_TAGS or attrs:
            raise ValueError("Unsafe stem HTML element/attribute")
        self.parts.append("<"+tag+">")
        self.stack.append(tag)
    def handle_endtag(self,tag):
        if not self.stack or self.stack[-1]!=tag:
            raise ValueError("Unbalanced HTML")
        self.parts.append("</"+tag+">")
        self.stack.pop()
    def handle_startendtag(self,tag,attrs):
        raise ValueError("Self-closing tags unsupported in preview")
    def handle_data(self,data):
        self.parts.append(escape(data,quote=False))
    def handle_entityref(self,name):
        self.parts.append(escape("&"+name+";",quote=False))
    def handle_charref(self,name):
        self.parts.append(escape("&#"+name+";",quote=False))
    def finish(self):
        if self.stack:
            raise ValueError("Unclosed HTML tags")
        return "".join(self.parts)

def load(folder, expected=None):
    folder=Path(folder)
    files=sorted(p for p in folder.glob("*.json") if NAME.fullmatch(p.name))
    if expected is not None and len(files)!=expected:
        raise ValueError(f"Expected {expected} V2 files; found {len(files)}")
    out=[]
    keys=set()
    for path in files:
        doc=json.loads(path.read_text(encoding="utf-8"))
        key=doc.get("question_key")
        if key in keys or key!=path.name.split(".")[0]:
            raise ValueError("Duplicate/mismatched question key")
        keys.add(key)
        kind=doc.get("type")
        if kind not in TYPES:
            raise ValueError(f"Unsupported question type: {key}/{kind}")
        learner=doc.get("learner")
        if not isinstance(learner,dict):
            raise ValueError("Missing learner data")
        # Retain strictly the properties required to draw interactive controls.
        stem=learner.get("stem",{})
        parser=Sanitizer()
        if not isinstance(stem,dict) or stem.get("format")!="html":
            raise ValueError(f"Stem must be HTML: {key}")
        parser.feed(stem.get("text",""))
        sanitized=parser.finish()
        interaction=learner.get("interaction",{})
        if not isinstance(interaction,dict):
            raise ValueError("Invalid interaction")
        safe={"key":key,"type":kind,"stem":sanitized}
        if kind in {"single_choice","multiple_select"}:
            choices=interaction.get("options",[])
            safe["options"]=[{"id":c["id"],"text":c["text"]} for c in choices]
            safe["choose_n"]=interaction.get("choose_n")
        elif kind in {"inline_dropdown","multi_blank_dropdown"}:
            safe["prompt"]=interaction.get("prompt_with_slots")
            safe["slots"]=[{"id":s["id"],"choices":[{"id":c["id"],"text":c["text"]} for c in s["choices"]]}
                           for s in interaction.get("slots",[])]
        else:
            safe["rows"]=[{"id":r["id"],"text":r["text"]} for r in interaction.get("rows",[])]
            safe["columns"]=[{"id":c["id"],"text":c["text"]} for c in interaction.get("columns",[])]
        out.append(safe)
    return out

HTML=r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CertPassly AB-900 — local draft-only preview</title>
<style>
:root{font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;color:#152337;background:#f3f6fa}
*{box-sizing:border-box}body{margin:0}header{background:#102a48;color:#fff;padding:18px max(20px,calc((100vw - 920px)/2))}
header h1{font-size:21px;margin:0}header small{color:#c1d6ee}main{max-width:920px;margin:24px auto;padding:0 18px}
.notice{background:#fff8e7;border:1px solid #dfc57e;border-radius:10px;padding:12px 16px;margin-bottom:18px}
.panel{background:white;padding:26px;border-radius:14px;box-shadow:0 4px 20px #1232  }
nav{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:18px 0}
button,select{font:inherit;border:1px solid #b9c8d9;border-radius:7px;background:white;padding:8px 12px;color:#193859}
button{cursor:pointer}button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #0873dc}
button:hover{background:#eaf3ff}button:disabled{opacity:.45;cursor:not-allowed}
.question-stem{overflow-x:auto}.question-stem table{border-collapse:collapse;width:100%}
.question-stem th,.question-stem td{border:1px solid #cdd7e3;padding:8px;text-align:left}
.answer-set{border:0;padding:0;margin:18px 0}.answer-set legend{font-weight:700;margin-bottom:8px}
.choice{display:flex;align-items:start;gap:9px;padding:10px;border:1px solid #dae2ea;border-radius:8px;margin:8px 0}
.choice input{margin-top:6px}table.matrix{border-collapse:collapse;width:100%}
.matrix td,.matrix th{border:1px solid #cbd7e3;padding:11px;text-align:left}.matrix th:not(:first-child),.matrix td:not(:first-child){text-align:center}
.prompt{background:#f3f8fd;padding:14px;border-radius:8px;margin-top:14px}
select{max-width:100%}.details{color:#4b617b;font-size:14px}
@media(max-width:600px){.panel{padding:16px}.matrix{font-size:13px}.matrix td,.matrix th{padding:6px}}
</style></head><body>
<header><h1>CertPassly AB-900 — offline question preview</h1><small>Private pilot • draft only • not the live site</small></header>
<main><div class="notice">This preview lets you test learner-facing controls. It does <strong>not</strong> grade answers, reveal solutions, or prove website integration.</div>
<nav><button id="prev" type="button">Previous</button><label for="jump">Question <select id="jump"></select></label><button id="next" type="button">Next</button></nav>
<section class="panel" aria-live="polite"><h2 id="heading"></h2><div id="stem" class="question-stem"></div><div id="interaction"></div><p id="meta" class="details"></p></section>
</main><script id="question-data" type="application/json">__QUESTIONS_JSON__</script>
<script>
"use strict";
const data=JSON.parse(document.getElementById('question-data').textContent);
const heading=document.getElementById('heading'),stem=document.getElementById('stem');
const interaction=document.getElementById('interaction'),meta=document.getElementById('meta');
const jump=document.getElementById('jump'),prev=document.getElementById('prev'),next=document.getElementById('next');
let pos=0;
const selections=Array.from({length:data.length},()=>({}));
data.forEach((q,i)=>{let option=document.createElement('option');option.value=String(i);option.textContent=q.key;jump.append(option)});
function el(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function makeChoice(name,id,label,type,remember){
  const line=el('label');line.className='choice';
  const input=el('input');input.type=type;input.name=name;input.value=id;
  if(type==='radio')input.checked=selections[pos][name]===id;
  else input.checked=(selections[pos][name]||[]).includes(id);
  input.addEventListener('change',()=>{
    if(type==='radio')selections[pos][name]=id;
    else {
      const selected=new Set(selections[pos][name]||[]);
      if(input.checked)selected.add(id);else selected.delete(id);
      selections[pos][name]=[...selected];
      if(remember)remember();
    }
  });
  line.append(input,el('span',label));return line;
}
function show(){
 const q=data[pos];heading.textContent='Question '+(pos+1)+' of '+data.length+' — '+q.key;
 // Stem is safe-tag-only HTML, verified by the Python generator.
 stem.innerHTML=q.stem;interaction.replaceChildren();
 if(q.type==='single_choice'||q.type==='multiple_select'){
  const fs=el('fieldset'),leg=el('legend',q.type==='single_choice'?'Select one answer':'Select '+(q.choose_n||'all applicable')+' answers');
  fs.className='answer-set';fs.append(leg);
  for(const o of q.options)fs.append(makeChoice('choice',o.id,o.text,q.type==='single_choice'?'radio':'checkbox'));
  interaction.append(fs);
 } else if(q.type==='inline_dropdown'||q.type==='multi_blank_dropdown'){
  const para=el('div');para.className='prompt';
  const slots=Object.fromEntries(q.slots.map(s=>[s.id,s]));
  let prompt=q.prompt||'';
  const token=/\{\{([a-zA-Z][a-zA-Z0-9_-]*)\}\}/g;
  let match,last=0,slotIndex=0;
  while((match=token.exec(prompt))!==null){
   para.append(document.createTextNode(prompt.slice(last,match.index)));
   const s=slots[match[1]];if(!s)throw Error('Missing slot '+match[1]);
   const select=el('select');select.setAttribute('aria-label','Answer blank '+(++slotIndex));
   const initial=el('option','Choose an answer');initial.value='';select.append(initial);
   for(const c of s.choices){const op=el('option',c.text);op.value=c.id;select.append(op);}
   select.value=selections[pos][s.id]||'';
   select.addEventListener('change',()=>{selections[pos][s.id]=select.value});
   para.append(select);last=token.lastIndex;
  }
  para.append(document.createTextNode(prompt.slice(last)));interaction.append(para);
 } else if(q.type==='yes_no_matrix'){
  const tbl=el('table');tbl.className='matrix';
  const head=el('thead'),hrow=el('tr');hrow.append(el('th','Statement'));
  q.columns.forEach(c=>hrow.append(el('th',c.text)));head.append(hrow);tbl.append(head);
  const body=el('tbody');
  q.rows.forEach(r=>{const tr=el('tr');tr.append(el('td',r.text));
   q.columns.forEach(c=>{const td=el('td');const label=el('label');
    const radio=el('input');radio.type='radio';radio.name='row-'+r.id;radio.value=c.id;
    radio.setAttribute('aria-label',r.text+' — '+c.text);
    radio.checked=selections[pos][r.id]===c.id;
    radio.addEventListener('change',()=>{selections[pos][r.id]=c.id});
    label.append(radio);td.append(label);tr.append(td)});
   body.append(tr)});
  tbl.append(body);interaction.append(tbl);
 }
 meta.textContent='Draft V2 type: '+q.type+' • Answers stored only in this browser session. No grading or answer keys.';
 jump.value=String(pos);prev.disabled=pos===0;next.disabled=pos===data.length-1;
}
jump.addEventListener('change',()=>{pos=Number(jump.value);show()});
prev.addEventListener('click',()=>{if(pos>0){pos--;show()}});
next.addEventListener('click',()=>{if(pos<data.length-1){pos++;show()}});
if(data.length)show();
</script></body></html>
"""

def build(folder, output, expected=None):
    entries=load(folder,expected)
    raw=json.dumps(entries,ensure_ascii=False,separators=(",",":"))
    raw=raw.replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(HTML.replace("__QUESTIONS_JSON__",raw),encoding="utf-8")
    return {"questions":len(entries),"types":dict(Counter(x["type"] for x in entries)),
            "output":str(output),"answer_keys_included":False,"live_site_tested":False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--v2-dir",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--expected",type=int,default=89)
    a=p.parse_args()
    print(json.dumps(build(a.v2_dir,a.output,a.expected)))
if __name__=="__main__":main()
