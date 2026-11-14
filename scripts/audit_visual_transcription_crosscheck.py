#!/usr/bin/env python3
"""Compare private visual transcription ledger with generated learner V2 structures.

Technical consistency only. Ledger is NOT independent source-PDF visual proof.
Do not compare, research, or expose answers; reports remain PRIVATE.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

KEY = re.compile(r"^q\d{3}$")
def norm(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()

def inspect(ledger, flagged, folder):
    results = []
    for key in sorted(set(flagged)):
        problems = []
        if not KEY.fullmatch(key):
            results.append({"question_key": key, "status": "INVALID_KEY", "problems": ["invalid_key"]})
            continue
        reference = ledger.get(key)
        source = Path(folder) / (key + ".v1.json")
        if not isinstance(reference, dict):
            problems.append("visual_transcription_ledger_missing")
        if not source.is_file():
            problems.append("v2_file_missing")
        if problems:
            results.append({"question_key": key, "status": "REVIEW_REQUIRED", "problems": problems})
            continue
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
            learner = data.get("learner") or {}
            interaction = learner.get("interaction") or {}
            if "rows" in reference:
                rows = [norm(v) for v in reference["rows"]]
                actual = [norm(x.get("text")) for x in interaction.get("rows", [])]
                if rows != actual:
                    problems.append("matrix_rows_differ")
                if data.get("type") != "yes_no_matrix":
                    problems.append("matrix_type_differ")
                if len(interaction.get("columns", [])) != 2:
                    problems.append("matrix_columns_count_differ")
            if "blanks" in reference:
                choices = [[norm(t) for t in group] for group in reference["blanks"]]
                actual = [[norm(c.get("text")) for c in slot.get("choices", [])]
                          for slot in interaction.get("slots", [])]
                if choices != actual:
                    problems.append("dropdown_choice_text_or_count_differ")
                expected_type = "inline_dropdown" if len(choices) == 1 else "multi_blank_dropdown"
                if data.get("type") != expected_type:
                    problems.append("dropdown_type_differ")
            if "template" in reference:
                if norm(reference["template"]) != norm(interaction.get("prompt_with_slots")):
                    problems.append("prompt_template_differ")
            if "exhibit" in reference:
                problems.append("exhibit_needs_independent_visual_review")
            if not ("rows" in reference or "blanks" in reference):
                problems.append("unsupported_ledger_shape")
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            problems.append("malformed_record:" + type(exc).__name__)
        results.append({"question_key": key,
                        "status": "LEDGER_CONSISTENT_NOT_PDF_VERIFIED" if not problems else "REVIEW_REQUIRED",
                        "problems": problems})
    issues = [x for x in results if x["problems"]]
    return {"schema": "certpassly.visual-transcription-crosscheck.v1",
            "original_pdf_independently_verified": False, "answer_accuracy_assessed": False,
            "website_import_tested": False, "publish_approved": False,
            "flagged_count": len(set(flagged)), "ledger_consistent": len(results)-len(issues),
            "review_required": len(issues), "results": results,
            "status": "SOURCE_VISUAL_REVIEW_REQUIRED",
            "caution": "Comparison to an existing authored ledger is not direct PDF visual evidence."}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", required=True, type=Path)
    ap.add_argument("--cannot-convert", required=True, type=Path)
    ap.add_argument("--v2-dir", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    flags = json.loads(args.cannot_convert.read_text(encoding="utf-8"))
    keys = flags.get("question_keys") or [x["question_key"] for x in flags.get("items") or []]
    report = inspect(ledger, keys, args.v2_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({x: report[x] for x in ("flagged_count","ledger_consistent","review_required","status")}))
    return 0 if report["review_required"] == 0 else 2

if __name__ == "__main__":
    raise SystemExit(main())
