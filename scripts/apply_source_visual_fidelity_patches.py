#!/usr/bin/env python3
"""Apply reviewer-inspected source-media-bound V2 native content corrections.

Repairs are data-driven from a PRIVATE ledger with SHA256-checked source media.
No factual research, publication, or release approval. Only menu-to-choice
migration performs a mechanical server-key ID remapping and records it.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

KEY = re.compile(r"q\d{3}")
IMAGE = re.compile(r"q\d{3}-(?:answer-area|exhibit)\.(?:jpg|png)")
SAFE_TAG = re.compile(r"</?(?:p|strong|em|ul|li|table|thead|tbody|tr|th|td)>")
SLOT = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def source_checks(row, media_dir, key):
    sources = list(row.get("source_images") or []) + list(row.get("additional_source_images") or [])
    if not sources:
        raise ValueError("no original visual evidence")
    hashes = []
    for asset in sources:
        name, expected = asset["filename"], asset["sha256"]
        if not isinstance(name, str) or not IMAGE.fullmatch(name) or not name.startswith(key + "-"):
            raise ValueError("source filename/key mismatch")
        path = media_dir / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("source missing or symlink")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if not isinstance(expected, str) or len(expected) != 64 or actual != expected:
            raise ValueError("visual source hash mismatch")
        hashes.append({"filename": name, "sha256": actual})
    return hashes

def valid_html(value):
    if not isinstance(value, str) or not value.startswith("<p>"):
        raise ValueError("missing HTML stem")
    plain = SAFE_TAG.sub("", value)
    if "<" in plain or ">" in plain:
        raise ValueError("unsafe markup")

def apply(ledger, media_dir, v2_dir):
    media_dir, v2_dir = Path(media_dir).resolve(), Path(v2_dir).resolve()
    rows = ledger.get("records")
    if not isinstance(rows, list) or not rows:
        raise ValueError("missing visual patch records")
    proposed, seen = [], set()
    for patch in rows:
        key = patch.get("question_key")
        if not isinstance(key, str) or not KEY.fullmatch(key) or key in seen:
            raise ValueError("duplicate or invalid key")
        seen.add(key)
        proofs = source_checks(patch, media_dir, key)
        file = v2_dir / (key + ".v1.json")
        if file.is_symlink() or not file.is_file():
            raise ValueError("V2 file missing or symlink")
        doc = json.loads(file.read_text(encoding="utf-8"))
        if doc.get("question_key") != key or doc.get("version") != 1:
            raise ValueError("V2 identity drift")
        learner = doc.get("learner")
        answer = doc.get("answer")
        if not isinstance(learner, dict) or not isinstance(answer, dict):
            raise ValueError("missing learner/answer")
        stem = learner.get("stem")
        interaction = learner.get("interaction")
        if not isinstance(stem, dict) or not isinstance(interaction, dict):
            raise ValueError("missing stem/interaction")
        learner_before, answer_before = digest(learner), digest(answer)
        kind = patch.get("kind")
        if kind == "prompt_and_stem":
            if doc.get("type") not in ("inline_dropdown", "multi_blank_dropdown"):
                raise ValueError("expected dropdown")
            prompt = patch.get("prompt")
            valid_html(patch.get("stem"))
            ids = [slot.get("id") for slot in interaction.get("slots", [])]
            if not isinstance(prompt, str) or sorted(SLOT.findall(prompt)) != sorted(ids):
                raise ValueError("corrected prompt slots do not match")
            interaction["prompt_with_slots"] = prompt
            stem["text"] = patch["stem"]
        elif kind == "rows_replace":
            if doc.get("type") != "yes_no_matrix":
                raise ValueError("expected yes_no_matrix")
            replacements = patch.get("replacements")
            if not isinstance(replacements, list) or not replacements:
                raise ValueError("missing row replacements")
            for pair in replacements:
                old, new = pair.get("old"), pair.get("new")
                if not isinstance(old,str) or not old or not isinstance(new,str) or not new:
                    raise ValueError("malformed row replacement")
                matches = sum(old in r.get("text","") for r in interaction.get("rows",[]))
                if matches < 1 or old not in stem.get("text",""):
                    raise ValueError("row source text not found in both structures")
                for r in interaction["rows"]:
                    r["text"] = r["text"].replace(old,new)
                stem["text"] = stem["text"].replace(old,new)
        elif kind == "menu_to_single_choice":
            if doc.get("type") != "inline_dropdown":
                raise ValueError("expected original inline_dropdown")
            valid_html(patch.get("stem"))
            old_slots = interaction.get("slots") or []
            if len(old_slots) != 1:
                raise ValueError("expected one old slot")
            original = answer.get("answer_key",{}).get("slots",{}).get(old_slots[0].get("id"))
            keyed_old = next((c.get("text") for c in old_slots[0].get("choices",[]) if c.get("id")==original),None)
            if keyed_old != patch.get("expected_old_keyed_label"):
                raise ValueError("original server-side key label does not match preserved source")
            options = patch.get("options")
            if not isinstance(options,list) or len(options)<2 or len(options)>26 or not all(isinstance(x,str) and x for x in options) or len(set(options))!=len(options):
                raise ValueError("invalid menu options")
            new_options = [{"id":chr(97+i),"text":s} for i,s in enumerate(options)]
            target = patch.get("new_keyed_option_id")
            if target not in [x["id"] for x in new_options]:
                raise ValueError("remapped option missing")
            if options[ord(target)-97].lstrip("[ ").strip() != keyed_old.lstrip("[ ").strip():
                raise ValueError("remap is not text-equivalent")
            # Only mechanical ID migration of original owner key; accuracy NOT researched.
            explanation = answer.get("explanation")
            if not isinstance(explanation,dict):
                raise ValueError("original explanation missing")
            old_per = explanation.get("per_option") or {}
            new_per = {}
            for old_choice in old_slots[0].get("choices",[]):
                oldlabel = old_choice.get("text","").lstrip("[ ").strip()
                matched = next((c["id"] for c in new_options if c["text"]==oldlabel),None)
                legacy_ref = old_slots[0]["id"] + "." + old_choice["id"]
                if matched and legacy_ref in old_per:
                    new_per[matched] = old_per[legacy_ref]
            explanation["per_option"] = new_per
            answer["answer_key"] = {"correct_option_ids":[target]}
            doc["type"] = "single_choice"
            stem["text"] = patch["stem"]
            learner["interaction"] = {"options":new_options,"choose_n":1}
            learner.pop("constraints",None)
            doc.setdefault("meta",{})["type_reason"] = "Source UI menu reconstructed as a native six-option single choice"
        else:
            raise ValueError("unrecognized patch type")
        valid_html(stem.get("text"))
        if digest(learner) == learner_before:
            raise ValueError("patch made no learner change")
        answer_after = digest(answer)
        if kind != "menu_to_single_choice" and answer_before != answer_after:
            raise ValueError("unexpected answer mutation")
        doc.setdefault("meta",{}).setdefault("flags",[]).append(
            "Technical source-image transcription corrected; owner answer factual accuracy remains unverified.")
        proposed.append((file,doc,{"question_key":key,"repair_kind":kind,
          "source_images":proofs,"learner_before_sha256":learner_before,
          "learner_after_sha256":digest(learner),"answer_before_sha256":answer_before,
          "answer_after_sha256":answer_after,
          "answer_structural_id_remapped":kind=="menu_to_single_choice",
          "answer_accuracy_researched":False,"source_pdf_whole_question_approved":False}))
    for file,doc,_ in proposed:
        file.write_text(json.dumps(doc,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return {"schema":"certpassly.source-visual-native-patches.v1","patched":len(proposed),
            "no_answer_research":True,"source_pdf_complete_review":False,
            "website_import_tested":False,"published":False,
            "records":[record for _,__,record in proposed]}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ("ledger","media-dir","v2-dir","report"):
        ap.add_argument("--"+arg,required=True,type=Path)
    args=ap.parse_args()
    ledger=json.loads(args.ledger.read_text(encoding="utf-8"))
    report=apply(ledger,args.media_dir,args.v2_dir)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"patched":report["patched"],"no_answer_research":True}))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
