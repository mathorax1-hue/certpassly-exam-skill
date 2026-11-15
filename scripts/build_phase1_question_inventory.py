#!/usr/bin/env python3
"""Phase 1: immutable-source, 89-question CertPassly AB-900 engineering inventory.

No publication, no answer inference, no changed gate. Inputs remain private:
original owner PDF, pinned upstream technical evidence, native V2 review bundle.
Only use on a private runner; output includes source-image SHA256 metadata.
"""
import argparse
import collections
import hashlib
import json
import re
import zipfile
from pathlib import Path

import fitz

SOURCE_SHA = "e0e989699408066d157b41929d2b2bbaec6386e596a9645adacb0b48f3bc6001"
UPSTREAM_SHA = "d9b6bf67efb870019dd88caeffa90952b7e000d3"
SCHEMA_SHA = "da9331c562a0e08cd156cc5efe6181cb8910ec19c523ff83dc43687190dc728e"

FLAG_TO_STAGE = {
    "ocr_pass_disagreement": "source_ocr",
    "ocr_low_word_confidence": "source_ocr",
    "ocr_low_overall_confidence": "source_ocr",
    "source_words_missing": "content_fidelity",
    "non_source_words_added": "content_fidelity",
    "question_type_unresolved": "interaction_mapping",
    "answer_evidence_unresolved": "answer_key",
    "other_fidelity_or_interaction_hold": "content_fidelity",
}
STAGE_TO_PHASE = {
    "source_ocr": 2, "content_fidelity": 2,
    "interaction_mapping": 3, "answer_key": 4,
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_index(data):
    doc = fitz.open(stream=data, filetype="pdf")
    marker_counts = collections.Counter()
    indexed = collections.defaultdict(lambda: {"pages": set(), "images": []})
    current = None
    for page_number, page in enumerate(doc, 1):
        axis = 0 if page.rotation in (90, 270) else 1
        events = []
        for block in page.get_text("dict")["blocks"]:
            if block["type"] == 0:
                for line in block["lines"]:
                    text = " ".join(span["text"] for span in line["spans"])
                    for match in re.finditer(r"\bQUESTION\s+(\d+)\b", text, re.I):
                        number = int(match.group(1))
                        if 1 <= number <= 89:
                            events.append((line["bbox"][axis], 0, f"q{number:03d}"))
            elif block["type"] == 1 and block.get("image"):
                events.append((block["bbox"][axis], 1, block["image"]))
        for _, typ, value in sorted(events, key=lambda t: (
                -t[0] if page.rotation == 270 else t[0], t[1])):
            if typ == 0:
                current = value
                marker_counts[current] += 1
                indexed[current]["pages"].add(page_number)
            elif current:
                indexed[current]["pages"].add(page_number)
                indexed[current]["images"].append({
                    "page": page_number, "sha256": sha(value)
                })
    out = {k: {"pages": sorted(v["pages"]), "images": v["images"]}
           for k, v in indexed.items()}
    return len(doc), marker_counts, out


def inventory(pdf, upstream_zip, review):
    source_bytes = Path(pdf).read_bytes()
    if sha(source_bytes) != SOURCE_SHA:
        raise ValueError("Original PDF SHA-256 mismatch")
    with zipfile.ZipFile(upstream_zip) as z:
        required = [
            "export/fidelity.json", "export/cannot-convert.json",
            "export/technical_report.json", "AB-900.site-format.v2.json",
        ]
        if any(p not in z.namelist() for p in required):
            raise ValueError("Canonical evidence files missing")
        fid, held, tech, original = [
            json.loads(z.read(p)) for p in required
        ]
        input_hashes = {p: sha(z.read(p)) for p in required}
    review_bytes = Path(review).read_bytes()
    reviewed = json.loads(review_bytes)
    if not (fid["total"] == tech["total"] == 89
            and fid["exported"] == tech["detected"] == 36
            and fid["held"] == tech["held"] == 53
            and len(original["questions"]) == 36
            and len(held) == 53
            and len(reviewed["questions"]) == 43):
        raise ValueError("Upstream baseline changed; reconcile before inventory")
    fids = {q["question_key"]: q for q in fid["items"]}
    holds = {q["question_key"]: q for q in held}
    accepted = {q["question_key"]: q for q in original["questions"]}
    review_items = {q["question_key"]: q for q in reviewed["questions"]}
    keys = {f"q{i:03d}" for i in range(1, 90)}
    extra = set(review_items) - set(accepted)
    if not (len(fids) == 89 and len(holds) == 53
            and len(accepted) == 36 and len(review_items) == 43
            and set(fids) == keys
            and set(holds).isdisjoint(accepted)
            and set(holds) | set(accepted) == keys
            and extra == {"q002", "q010", "q043", "q045",
                          "q070", "q082", "q083"}):
        raise ValueError("Duplicate, missing, or unexpected question IDs")
    page_count, markers, indexed = source_index(source_bytes)
    if not (page_count == 92 and set(markers) == keys
            and all(count == 1 for count in markers.values())
            and all(indexed[q]["images"] for q in holds)):
        raise ValueError("Original source question/image mapping incomplete")

    flags_count = collections.Counter()
    types_count = collections.Counter()
    stage_items = collections.defaultdict(set)
    questions = []
    for num in range(1, 90):
        key = f"q{num:03d}"
        f, held = fids[key], holds.get(key)
        flags = []
        if held:
            reason = held.get("reason") or ""
            low = reason.lower()
            rules = f.get("type_rules") or []
            if f.get("ocr_agree") is False or "ocr passes disagree" in low:
                flags.append("ocr_pass_disagreement")
            if ("ocr words below 90" in low or
                    (f.get("ocr_min_word_confidence") is not None
                     and f["ocr_min_word_confidence"] < 90)):
                flags.append("ocr_low_word_confidence")
            if ("ocr overall confidence" in low or
                    (f.get("ocr_overall_confidence") is not None
                     and f["ocr_overall_confidence"] < 95)):
                flags.append("ocr_low_overall_confidence")
            if f.get("missing_words"):
                flags.append("source_words_missing")
            if f.get("extra_words"):
                flags.append("non_source_words_added")
            if len(rules) != 1 or not f.get("type_rule"):
                flags.append("question_type_unresolved")
            evidence_method = f.get("key_source")
            if not evidence_method or any(word in str(evidence_method).lower()
                                          for word in ("disagree", "uncertain", "not_found")):
                flags.append("answer_evidence_unresolved")
            if not flags:
                flags.append("other_fidelity_or_interaction_hold")
            types_count[held.get("suggested_type") or "unclassified"] += 1
            for flag in flags:
                flags_count[flag] += 1
                stage_items[FLAG_TO_STAGE[flag]].add(key)
        stages = sorted({FLAG_TO_STAGE[flag] for flag in flags})
        questions.append({
            "question_key": key,
            "source_pages": indexed[key]["pages"],
            "original_pdf_image_count": len(indexed[key]["images"]),
            "original_pdf_images": indexed[key]["images"],
            "upstream_status": "held" if held else "exported",
            "upstream_type": (accepted.get(key) or {}).get("type") or
                             (held or {}).get("suggested_type"),
            "matched_type_rules": f.get("type_rules") or [],
            "review_bundle_status": (
                "native_unscored_review" if key in extra
                else "baseline_export" if key in accepted
                else "not_represented"),
            "hard_blockers": flags,
            "next_engineering_stages": stages,
            "next_plan_phases": sorted({STAGE_TO_PHASE[stage] for stage in stages}),
            "missing_word_count": len(f.get("missing_words") or []),
            "extra_word_count": len(f.get("extra_words") or []),
            "ocr_min_word_confidence": f.get("ocr_min_word_confidence"),
            "ocr_overall_confidence": f.get("ocr_overall_confidence"),
            "ocr_two_pass_agreement": f.get("ocr_agree"),
            "key_evidence_method": f.get("key_source"),
            "upstream_hold_reason": (held or {}).get("reason"),
            "source_fidelity_certified": False,
            "answer_scoring_certified": False,
            "website_import_certified": False,
            "release_approved": False,
        })
    if sum(bool(q["hard_blockers"]) for q in questions) != 53:
        raise ValueError("Every held question needs an actionable defect")
    summary = {
        "source_pages": page_count, "source_question_markers": 89,
        "source_questions": 89, "canonical_upstream_exported": 36,
        "canonical_upstream_held": 53, "private_v2_review_records": 43,
        "additional_native_unscored_reviews": 7,
        "not_represented_in_review": 46,
        "held_source_image_mapped": 53,
        "nonexclusive_blockers": dict(sorted(flags_count.items())),
        "held_type_suggestions": dict(sorted(types_count.items())),
        "unique_held_questions_by_engineering_stage": {
            k: len(v) for k, v in sorted(stage_items.items())
        },
        "canonical_pipeline_execution": "SUCCESS",
        "canonical_release": "BLOCKED",
        "website_staging": "NOT_TESTED",
    }
    return {
        "status": "PHASE_1_LOCKED_BASELINE_NOT_PUBLICATION",
        "source_sha256": SOURCE_SHA, "upstream_commit": UPSTREAM_SHA,
        "schema_sha256": SCHEMA_SHA,
        "upstream_evidence_sha256": input_hashes,
        "review_bundle_sha256": sha(review_bytes),
        "scope": "CertPassly v1.0 Phase 1, AB-900 only",
        "summary": summary, "questions": questions,
        "phase_1_exit": {
            "all_89_source_questions_indexed": True,
            "all_53_held_questions_have_actionable_blockers": True,
            "all_held_source_images_mapped": True,
            "thresholds_or_release_gate_changed": False,
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--upstream-zip", required=True)
    ap.add_argument("--review", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    result = inventory(a.pdf, a.upstream_zip, a.review)
    dest = Path(a.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print("Inventory source SHA-256:", result["source_sha256"])
    print("Inventory file SHA-256:", sha(dest.read_bytes()))


if __name__ == "__main__":
    main()
