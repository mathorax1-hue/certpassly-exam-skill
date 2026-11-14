#!/usr/bin/env python3
"""Conservatively restore explicit multiple-select counts from learner stem.

No answer key read or modified. Only restores a count explicitly stated as
'which two' or 'what are two' in the existing source-derived stem. Never
guesses for vague multi-select prompts. Write corrected drafts privately.
"""
from __future__ import annotations
from html import unescape
from html.parser import HTMLParser
import json
import re
from pathlib import Path

QFILE = re.compile(r"^q\d{3}\.v\d+\.json$")
TWO = re.compile(r"\b(?:which\s+two|what\s+are\s+two)\b", re.I)

class Plain(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)

def read_stem(doc):
    stem = (doc.get("learner") or {}).get("stem") or {}
    parser = Plain()
    parser.feed(stem.get("text", "") if isinstance(stem, dict) else "")
    return unescape(" ".join(parser.parts))

def correct(doc):
    if doc.get("type") != "multiple_select":
        return False, "not_multiple_select"
    learner = doc.get("learner")
    if not isinstance(learner, dict) or not isinstance(learner.get("interaction"), dict):
        return False, "missing_interaction"
    inter = learner["interaction"]
    if inter.get("choose_n") is not None:
        return False, "already_explicit"
    options = inter.get("options")
    if not isinstance(options, list) or len(options) < 2:
        return False, "insufficient_options"
    if not TWO.search(read_stem(doc)):
        return False, "no_unambiguous_two_selection_instruction"
    inter["choose_n"] = 2
    learner.setdefault("constraints", {})["choose_n"] = 2
    return True, "explicit_two_selection_restored"

def apply(directory):
    results = []
    for path in sorted(Path(directory).glob("*.json")):
        if not QFILE.fullmatch(path.name):
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        changed, reason = correct(doc)
        if changed:
            path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if doc.get("type") == "multiple_select":
            results.append({"question_key": doc.get("question_key"),
                            "changed": changed, "reason": reason})
    return results

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--v2-dir", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    args = p.parse_args()
    events = apply(args.v2_dir)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"schema": "certpassly.multi-select-count-repair.v1",
      "technical_only": True, "answer_keys_modified": False,
      "source_fidelity_verified": False, "events": events}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"multiple_select": len(events),
        "restored": sum(e["changed"] for e in events)}))
