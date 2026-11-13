#!/usr/bin/env python3
"""Phase 1 extraction: deterministic export adapters for structured/v1 (public toolkit).

Usage: python -m certpassly.phase1.build_exports <config.json>

1. upstream-extract-compatible/
   - split.original.json   exact copy of the reproduced pinned-extractor output
   - roundtrip-check.json  split-format records rebuilt FROM structured/v1 and compared
   - field-mapping.json    field-by-field mapping documentation
2. site-format-v1-draft/
   - question-type-draft.json  site types + basis only (no answers/media exports)
   - export-blockers.json      fail-closed reasons per blocked export field

Fail-closed: nothing learner-facing is exported here; the site-format draft is
blocked per question pending independent review. Config-driven; no exam-specific
values are hardcoded (notes come from config).
"""
from __future__ import annotations
import hashlib, json, os, sys
from collections import Counter

from . import p1common as P


def main(cfg_path):
    cfg = P.load_config(cfg_path)
    paths = cfg["paths"]
    V1, UP = paths["out_dir"], paths["upstream_out"]
    notes = cfg.get("export_notes", {})

    # ---- 1. upstream-extract-compatible ----
    split = P.jload(f"{UP}/extracted/split.json")
    with open(f"{UP}/extracted/split.json", encoding='utf-8') as f:
        split_text = f.read()
    os.makedirs(f"{V1}/export/upstream-extract-compatible", exist_ok=True)
    with open(f"{V1}/export/upstream-extract-compatible/split.original.json", "w", encoding='utf-8') as f:
        f.write(split_text)

    qs = {}
    qdir = f"{V1}/questions"
    for fname in sorted(os.listdir(qdir)):
        if fname.endswith(".json"):
            qs[fname[:-5]] = P.jload(f"{qdir}/{fname}")

    rebuilt = {}
    for q, r in qs.items():
        rec = {}
        rec["question_key"] = q
        rec["source_number"] = r["source_number"]
        rec["marker"] = r["marker"]
        rec["pages"] = r["upstream_pages_field"]
        rec["stem"] = r["stem"]["upstream_normalized"]
        rec["options"] = {e["label"].lower(): e["text"] for e in r["options"].get("entries", [])}
        rec["answer_raw"] = r["answer"]["raw_text"]
        rec["question_images"] = [u["pdftohtml_name"] for u in r["media_usages"]
                                  if u["role"] in ("question_prompt", "exhibit")]
        rec["answer_images"] = [u["pdftohtml_name"] for u in r["media_usages"]
                                if u["role"] == "answer_reference"]
        rec["layout_profile"] = r["layout_profile"]
        rebuilt[q] = rec

    diffs = []
    for q in split:
        a, b = split[q], rebuilt[q]
        for k in ("question_key", "source_number", "marker", "pages", "stem", "options",
                  "answer_raw", "question_images", "answer_images", "layout_profile"):
            if a.get(k) != b.get(k):
                diffs.append({"question": q, "field": k, "pinned_extractor": a.get(k),
                              "rebuilt_from_structured": b.get(k)})

    roundtrip = {
        "description": ("Deterministic adapter: pinned-extractor split-format records rebuilt from "
                        "structured/v1 question records only, then compared field-by-field with the "
                        "reproduced pinned extraction"
                        + notes.get("roundtrip_description_suffix", "") + "."),
        "pinned_split_sha256": hashlib.sha256(split_text.encode()).hexdigest(),
        "fields_compared": ["question_key", "source_number", "marker", "pages", "stem", "options",
                            "answer_raw", "question_images", "answer_images", "layout_profile"],
        "questions_compared": len(split),
        "field_mismatches": len(diffs),
        "result": "IDENTICAL" if not diffs else "DIFFERS",
        "mismatches": diffs[:20],
    }
    P.jdump(roundtrip, f"{V1}/export/upstream-extract-compatible/roundtrip-check.json")

    mapping = {
        "description": "How structured/v1 fields map to the pinned upstream extracted/split.json fields.",
        "field_map": {
            "question_key": "question_id",
            "source_number": "source_number",
            "marker": "marker",
            "pages": "upstream_pages_field (upstream counts body+image element pages; structured pages additionally includes the marker's own page)",
            "stem": "stem.upstream_normalized (structured keeps stem.raw AND the upstream-normalized form with logged normalizations)",
            "options": "options.entries (label->text) when mode=text_options; {} when mode=in_question_image (upstream drops empty A-D labels; structured preserves them in labels_present_in_text_layer)",
            "answer_raw": "answer.raw_text (unmodified)",
            "question_images": "media_usages[role in question_prompt,exhibit].pdftohtml_name in reading order",
            "answer_images": "media_usages[role=answer_reference].pdftohtml_name",
            "layout_profile": "layout_profile"
        },
        "known_divergences": notes.get("known_divergences", []),
        "machine_regenerable": True,
        # provenance chain: export_notes.regeneration_command > provenance block >
        # legacy private-toolkit default (byte-compat with accepted extractions)
        "regeneration_command": notes.get("regeneration_command",
                                           P.provenance(cfg, "exports_regeneration_command",
                                                        "python3 tools/phase1-extraction/build_exports.py <config.json> "
                                                        "(tools/phase1-extraction/)"))
    }
    P.jdump(mapping, f"{V1}/export/upstream-extract-compatible/field-mapping.json")

    # ---- 2. site-format-v1-draft (fail-closed) ----
    blocked = []
    typed = {}
    has_combined = any(r["answer"]["source_kind"] == "typed_text_with_answer_image"
                       for r in qs.values())
    reason_answer = ("cannot_export_answer_without_review: answer exists only as (or is corroborated "
                     "by) a marked answer-reference image; candidate transcriptions are unapproved"
                     if has_combined else
                     "cannot_export_answer_without_review: answer exists only as a marked "
                     "answer-reference image; candidate transcriptions are unapproved")
    for q, r in qs.items():
        typed[q] = {
            "site_format_type": r["question_type"]["site_format_type"],
            "basis": r["question_type"]["basis"],
            "confidence": r["question_type"]["confidence"],
            "status": "type_draft_only",
        }
        reasons = []
        if r["answer"]["source_kind"] in ("answer_reference_image", "typed_text_with_answer_image"):
            reasons.append(reason_answer)
        if r["answer"]["selection_candidates_unapproved"]:
            reasons.append("cannot_export_key: machine/manual candidates are explicitly unapproved")
        if r["options"]["mode"] == "in_question_image":
            reasons.append("cannot_export_options: option list lives inside the question image; requires approved visual transcription")
        if r["question_type"]["site_format_type"] == "unknown":
            reasons.append("cannot_export_type: no justified site type")
        if r.get("editorial_overlay_status") == "superseded_by_editorial_replacement":
            reasons.append(f"superseded_by_editorial_replacement: {r['editorial_replacement_id']} (separate layer)")
        blocked.append({"question": q, "cannot_export_without_review": reasons})

    site = {
        "description": ("Fail-closed draft export to CertPassly site-format v1 taxonomy. Contains ONLY "
                        "question type classifications with their basis. No stems, options, answers, keys or "
                        "media are exported here: those require approved visual transcriptions, verified keys "
                        "and human review that do not exist yet (Phase 1 is the source-capture layer)."),
        "site_format_version": "v1",
        "source": (f"reference/site-format/v1/question_types.json of the pinned upstream "
                   f"{cfg.get('upstream', {}).get('commit', '')}"),
        "type_counts": {},
        "question_types": typed,
        "note": notes.get("site_taxonomy_note", "30-type site taxonomy."),
    }
    site["type_counts"] = dict(Counter(v["site_format_type"] for v in typed.values()))
    P.jdump(site, f"{V1}/export/site-format-v1-draft/question-type-draft.json")
    P.jdump({"description": "Per-question fail-closed export blockers; nothing is exported past these gates without review.",
             "blocked_questions": len(blocked), "items": blocked},
            f"{V1}/export/site-format-v1-draft/export-blockers.json")

    print("roundtrip:", roundtrip["result"], "| field mismatches:", roundtrip["field_mismatches"])
    print("site types:", site["type_counts"])
    print("blocked questions with at least one gate:", len(blocked))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
