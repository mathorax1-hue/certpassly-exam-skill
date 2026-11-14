#!/usr/bin/env python3
"""Apply private, image-hash-bound exhibit transcription as learner HTML.

Only copies inspected source descriptions into a question's learner stem.
No answer/key changes, no screenshots in learner UI, no publication claims.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

KEY = re.compile(r"q\d{3}")
IMAGE = re.compile(r"(q\d{3})-exhibit\.(jpg|png)")
SAFE_TAG = re.compile(r"</?(?:p|strong|em|ul|li|table|thead|tbody|tr|th|td)>")

def sha256(blob):
    return hashlib.sha256(blob).hexdigest()

def apply(ledger, media_dir, v2_dir):
    media_dir, v2_dir = Path(media_dir).resolve(), Path(v2_dir).resolve()
    records = ledger.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("empty transcription ledger")
    prepared = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("invalid record")
        key, name, expected, addition = (record.get(k) for k in
            ("question_key", "source_filename", "source_sha256", "html"))
        if not isinstance(key, str) or not KEY.fullmatch(key) or key in seen:
            raise ValueError("invalid or duplicate key")
        seen.add(key)
        m = IMAGE.fullmatch(name or "")
        if not m or m.group(1) != key:
            raise ValueError("image path is not an exhibit for this question")
        source = media_dir / name
        if source.is_symlink() or not source.is_file():
            raise ValueError("source exhibit missing or symlink")
        actual = sha256(source.read_bytes())
        if actual != expected:
            raise ValueError("source image SHA256 mismatch")
        if not isinstance(addition, str) or not addition.strip() or not addition.startswith("<p>"):
            raise ValueError("missing safe HTML transcription")
        clean = SAFE_TAG.sub("", addition)
        if "<" in clean or ">" in clean:
            raise ValueError("unexpected HTML element or attribute")
        path = v2_dir / (key + ".v1.json")
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing V2 question")
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("question_key") != key or doc.get("version") != 1:
            raise ValueError("question identity changed")
        stem = (doc.get("learner") or {}).get("stem")
        if not isinstance(stem, dict) or stem.get("format") != "html":
            raise ValueError("HTML learner stem required")
        previous = stem.get("text")
        if not isinstance(previous, str) or not previous.strip() or addition in previous:
            raise ValueError("stem is blank or transcription already applied")
        answer_before = sha256(json.dumps(doc.get("answer"), sort_keys=True).encode("utf-8"))
        stem["text"] = previous + addition
        answer_after = sha256(json.dumps(doc.get("answer"), sort_keys=True).encode("utf-8"))
        if answer_before != answer_after:
            raise ValueError("answer payload was changed")
        prepared.append((path, doc, {"question_key": key, "source_filename": name,
            "source_exhibit_sha256": actual,
            "learner_stem_sha256_before": sha256(previous.encode()),
            "learner_stem_sha256_after": sha256(stem["text"].encode()),
            "answer_block_sha256_unchanged": answer_before,
            "native_html_inserted": True,
            "entire_question_pdf_fidelity_approved": False}))
    for path, doc, _ in prepared:
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"schema":"certpassly.source-exhibit-patch.v1",
            "patched":len(prepared),
            "no_answer_research":True,"learner_source_images_added":0,
            "entire_question_source_fidelity_approved":False,
            "source_evidence_records":[entry for _,__,entry in prepared]}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger",required=True,type=Path)
    ap.add_argument("--media-dir",required=True,type=Path)
    ap.add_argument("--v2-dir",required=True,type=Path)
    ap.add_argument("--report",required=True,type=Path)
    args=ap.parse_args()
    ledger=json.loads(args.ledger.read_text(encoding="utf-8"))
    report=apply(ledger,args.media_dir,args.v2_dir)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"patched":report["patched"],"source_fidelity_approved":False}))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
