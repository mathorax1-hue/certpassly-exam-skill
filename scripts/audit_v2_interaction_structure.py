#!/usr/bin/env python3
"""Fail-closed technical interaction inventory for Question Format V2 drafts.

Generic, synthetic-testable checker: does not approve source fidelity, answers,
schema compatibility, accessibility in a browser or actual importer behavior.
Generated exam reports must remain in PRIVATE raw-exam.
"""
from __future__ import annotations
import argparse
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re

QFILE = re.compile(r"^(q\d{3})\.v\d+\.json$")
SLOTS = re.compile(r"\{\{([A-Za-z][A-Za-z0-9_-]*)\}\}")
BLOCKED_HTML = re.compile(r"<\s*(script|iframe|object|embed|form)\b|\son[a-z]+\s*=", re.I)
PRIVATE_MEDIA = re.compile(r"answer[-_ ]?(area|review|key)|reviewer|correct[_-]?answer", re.I)
TYPES = {"single_choice", "multiple_select", "inline_dropdown",
         "multi_blank_dropdown", "yes_no_matrix"}

class Fragment(HTMLParser):
    def error(self, message):
        raise ValueError(message)

def identity_list(rows, label, minimum=1):
    errors = []
    if not isinstance(rows, list) or len(rows) < minimum:
        return [label + ": missing or too few elements"]
    seen = set()
    for i, item in enumerate(rows):
        if not isinstance(item, dict):
            errors.append(label + ": invalid element " + str(i))
            continue
        ident, content = item.get("id"), item.get("text")
        if not isinstance(ident, str) or not ident.strip() or ident in seen:
            errors.append(label + ": missing/duplicate ID")
        seen.add(ident)
        if not isinstance(content, str) or not content.strip():
            errors.append(label + ": missing visible text")
    return errors

def audit_one(doc, filename):
    errors = []
    m = QFILE.fullmatch(filename)
    key = m.group(1) if m else filename
    if not m or doc.get("question_key") != key:
        errors.append("file ID mismatch")
    kind = doc.get("type")
    if kind not in TYPES:
        errors.append("unsupported interaction type")
    learner = doc.get("learner")
    if not isinstance(learner, dict):
        return {"question_key": key, "type": kind, "errors": ["missing learner payload"]}
    if any(name in learner for name in ("answer", "answer_key", "correct_option_ids", "explanation")):
        errors.append("answer material embedded in learner object")
    stem = learner.get("stem")
    html = stem.get("text") if isinstance(stem, dict) else None
    if not isinstance(html, str) or not html.strip():
        errors.append("missing HTML stem")
    else:
        if BLOCKED_HTML.search(html):
            errors.append("unsafe HTML detected")
        try:
            Fragment().feed(html)
        except (ValueError, TypeError) as exc:
            errors.append("invalid HTML fragment: " + type(exc).__name__)
    interaction = learner.get("interaction")
    if not isinstance(interaction, dict):
        return {"question_key": key, "type": kind, "errors": errors + ["missing interaction"]}
    if kind in ("single_choice", "multiple_select"):
        options = interaction.get("options")
        errors += identity_list(options, "options", minimum=2)
        n = interaction.get("choose_n")
        if not isinstance(n, int) or isinstance(n, bool) or n < 1 or (
            isinstance(options, list) and n > len(options)):
            errors.append("invalid choose_n")
        if kind == "single_choice" and n != 1:
            errors.append("single_choice requires choose_n=1")
    elif kind in ("inline_dropdown", "multi_blank_dropdown"):
        slots = interaction.get("slots")
        prompt = interaction.get("prompt_with_slots")
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append("missing prompt_with_slots")
        if not isinstance(slots, list) or not slots:
            errors.append("missing slots")
        else:
            ids = [x.get("id") for x in slots if isinstance(x, dict)]
            if len(ids) != len(slots) or len(ids) != len(set(ids)) or not all(ids):
                errors.append("duplicate or missing slot IDs")
            used = SLOTS.findall(prompt or "")
            if sorted(used) != sorted(ids):
                errors.append("slot references do not match slot definitions")
            if kind == "inline_dropdown" and len(slots) != 1:
                errors.append("inline dropdown must have one slot")
            for s in slots:
                if not isinstance(s, dict):
                    errors.append("invalid slot entry")
                    continue
                if s.get("input") != "dropdown":
                    errors.append("unsupported slot control")
                errors += identity_list(s.get("choices"), "slot choices", minimum=2)
    elif kind == "yes_no_matrix":
        errors += identity_list(interaction.get("rows"), "rows", minimum=1)
        errors += identity_list(interaction.get("columns"), "columns", minimum=2)
    for media in learner.get("media") or []:
        if not isinstance(media, dict):
            errors.append("malformed learner media")
        elif PRIVATE_MEDIA.search(json.dumps(media, ensure_ascii=False)):
            errors.append("reviewer/answer media leaked to learner")
    return {"question_key": key, "type": kind, "errors": sorted(set(errors))}

def audit_directory(folder, expected=89):
    files = [p for p in sorted(Path(folder).glob("*.json")) if QFILE.fullmatch(p.name)]
    results = []
    for p in files:
        try:
            results.append(audit_one(json.loads(p.read_text(encoding="utf-8")), p.name))
        except (json.JSONDecodeError, UnicodeError) as exc:
            results.append({"question_key": p.name[:4], "type": None,
                            "errors": ["invalid JSON: " + type(exc).__name__]})
    keys = [r["question_key"] for r in results]
    problems = [r for r in results if r["errors"]]
    return {
        "schema": "certpassly.v2-interaction-inventory.v1",
        "technical_only": True, "source_fidelity_verified": False,
        "schema_validated_by_this_tool": False, "importer_tested": False,
        "answer_accuracy_assessed": False, "published": False,
        "expected": expected, "count": len(results), "unique": len(set(keys)),
        "type_counts": dict(Counter(r["type"] for r in results)),
        "problems": problems, "problem_question_count": len(problems),
        "automated_structure_pass": len(results) == expected and
             len(set(keys)) == expected and not problems,
        "caution": "Automated structure checks cannot certify original PDF transcription, "
                   "HTML browser behavior, upstream schema or live website importer."
    }

def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--v2-dir", required=True, type=Path)
    a.add_argument("--output", required=True, type=Path)
    a.add_argument("--expected", type=int, default=89)
    opts = a.parse_args()
    report = audit_directory(opts.v2_dir, opts.expected)
    opts.output.parent.mkdir(parents=True, exist_ok=True)
    opts.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"count": report["count"], "problem_question_count":
        report["problem_question_count"], "automated_structure_pass":
        report["automated_structure_pass"]}))
    return 0 if report["automated_structure_pass"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
