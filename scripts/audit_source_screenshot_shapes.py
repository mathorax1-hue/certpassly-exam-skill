#!/usr/bin/env python3
"""Reproduce private source-screenshot shape checks against all flagged V2 items.

Expectations are manually recorded from actual source screenshots. This audit
checks image identity, interaction type/shape and key contextual text. It does
NOT prove complete PDF wording, answer accuracy or live website behavior.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

KEY=re.compile(r"q\d{3}")
SRC=re.compile(r"q\d{3}-(?:answer-area|exhibit)\.(?:png|jpg)")

def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def inspect(expectations,pdf,media,v2):
    pdf,media,v2=Path(pdf),Path(media),Path(v2)
    pdf_sha=sha(pdf)
    expected_pdf=expectations.get("source_pdf_sha256")
    if pdf_sha != expected_pdf:
        raise ValueError("original PDF SHA256 does not match source provenance")
    rows=expectations.get("records")
    if not isinstance(rows,list) or not rows:
        raise ValueError("no reviewed source shapes")
    seen=set();out=[]
    for x in rows:
        key=x.get("question_key")
        if not isinstance(key,str) or not KEY.fullmatch(key) or key in seen:
            raise ValueError("invalid or duplicate reviewed key")
        seen.add(key)
        problems=[];assets=[]
        for name in x.get("source_images") or []:
            if not isinstance(name,str) or not SRC.fullmatch(name) or not name.startswith(key+"-"):
                problems.append("invalid_source_image_name")
                continue
            path=media/name
            if path.is_symlink() or not path.is_file():
                problems.append("source_image_missing")
                continue
            assets.append({"filename":name,"sha256":sha(path),"bytes":path.stat().st_size})
        if not assets:
            problems.append("no_original_screenshot_evidence")
        docfile=v2/(key+".v1.json")
        if not docfile.is_file() or docfile.is_symlink():
            problems.append("v2_missing")
            doc={}
        else:
            try:
                doc=json.loads(docfile.read_text(encoding="utf-8"))
            except (UnicodeError,json.JSONDecodeError):
                doc={}
                problems.append("invalid_v2_json")
        kind=x.get("kind")
        if doc.get("question_key")!=key or doc.get("type")!=kind:
            problems.append("question_type_or_key_mismatch")
        learner=doc.get("learner") or {}
        interaction=learner.get("interaction") or {}
        if kind=="yes_no_matrix":
            shape=[len(interaction.get("rows") or []),len(interaction.get("columns") or [])]
        elif kind in ("inline_dropdown","multi_blank_dropdown"):
            shape=[len(slot.get("choices") or []) for slot in interaction.get("slots") or []]
        elif kind=="single_choice":
            shape=[len(interaction.get("options") or [])]
        else:
            shape=[]
            problems.append("unknown_expectation_kind")
        if shape!=x.get("shape"):
            problems.append("original_screenshot_shape_mismatch")
        visible=json.dumps(learner,ensure_ascii=False)
        for phrase in x.get("required_terms") or []:
            if phrase not in visible:
                problems.append("missing_source_context_term")
        out.append({"question_key":key,"source_images":assets,"expected_kind":kind,
                   "expected_shape":x.get("shape"),"actual_shape":shape,
                   "problems":sorted(set(problems)),
                   "scoped_shape_reconciled":not problems,
                   "complete_source_question_verified":False})
    fails=[x for x in out if x["problems"]]
    return {"schema":"certpassly.source-screenshot-shape-audit.v1",
       "source_pdf_sha256":pdf_sha,"source_pdf_hash_pass":True,
       "reviewed_count":len(rows),"scoped_shape_pass":not fails,
       "matched":len(rows)-len(fails),"review_required":len(fails),
       "full_pdf_transcription_verified":False,
       "website_import_tested":False,"answers_researched":False,
       "publication_approved":False,
       "records":out,
       "caution":"Matching source screenshot shapes and terms is scoped evidence, not proof of full question PDF fidelity."}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ("expectations","pdf","media-dir","v2-dir","report"):
        ap.add_argument("--"+arg,required=True,type=Path)
    args=ap.parse_args()
    expected=json.loads(args.expectations.read_text(encoding="utf-8"))
    report=inspect(expected,args.pdf,args.media_dir,args.v2_dir)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("reviewed_count","matched","review_required","scoped_shape_pass")}))
    return 0 if report["scoped_shape_pass"] else 2
if __name__=="__main__":
    raise SystemExit(main())
