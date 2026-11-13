"""Synthetic structured/v1 fixture builder for public Phase 1 tests.

Everything here is 100% synthetic: no real exam content, no owner data.
Builds a minimal but contract-accurate structured/v1 tree + pinned-upstream
split output for 3 questions (typed answer, image-only answer, typed+image
answer) so build_exports / reconcile / validator behaviors can be tested on
a stdlib-only environment.
"""
from __future__ import annotations

import hashlib
import json
import os


def _q(n, *, source_kind, answer_raw, options_mode, entries, media_usages,
       site_type, marker, upstream_pages):
    return {
        "schema_version": "structured-v1",
        "source_number": n,
        "marker": marker,
        "pages": [1],
        "upstream_pages_field": upstream_pages,
        "stem": {"raw": f"Synthetic stem {n}", "upstream_normalized": f"Synthetic stem {n}"},
        "options": {"mode": options_mode, "entries": entries,
                    "labels_present_in_text_layer": [e["label"] for e in entries]},
        "answer": {
            "raw_text": answer_raw,
            "source_kind": source_kind,
            "selection_candidates_unapproved": source_kind != "owner_typed_text",
            "privacy": "private_reviewer_only" if source_kind != "owner_typed_text" else "private",
        },
        "media_usages": media_usages,
        "question_type": {"site_format_type": site_type, "basis": "synthetic test basis",
                          "confidence": "measured"},
        "layout_profile": "question_n_correct_answer",
        "editorial_overlay_status": None,
        "unresolved": [],
    }


def build_fixture(root: str) -> dict:
    """Create the synthetic tree under root; return the config dict for tools."""
    v1 = os.path.join(root, "structured", "v1")
    up = os.path.join(root, "upstream-out")
    os.makedirs(os.path.join(v1, "questions"), exist_ok=True)
    os.makedirs(os.path.join(v1, "pages"), exist_ok=True)
    os.makedirs(os.path.join(v1, "assets"), exist_ok=True)
    os.makedirs(os.path.join(up, "extracted"), exist_ok=True)

    # 3 synthetic asset binaries (content-addressed names)
    assets = {}
    for i in (1, 2, 3):
        blob = f"synthetic-image-{i}".encode()
        sha = hashlib.sha256(blob).hexdigest()
        assets[i] = sha
        with open(os.path.join(v1, "assets", f"{sha}.png"), "wb") as f:
            f.write(blob)

    q1 = _q(1, source_kind="owner_typed_text", answer_raw="A",
            options_mode="text_options",
            entries=[{"label": "A", "text": "synthetic option A"},
                     {"label": "B", "text": "synthetic option B"}],
            media_usages=[{"usage_id": "u1", "xref": 11, "asset": assets[1],
                           "role": "question_prompt", "privacy": "learner_visible",
                           "pdftohtml_name": "p-001_001.png", "question_key": "q001",
                           "page": 1, "active_packaged_media_status": "active"}],
            site_type="single_choice", marker="QUESTION 1", upstream_pages=[1])
    q2 = _q(2, source_kind="answer_reference_image", answer_raw="",
            options_mode="in_question_image", entries=[],
            media_usages=[{"usage_id": "u2", "xref": 12, "asset": assets[2],
                           "role": "question_prompt", "privacy": "learner_visible",
                           "pdftohtml_name": "p-002_001.png", "question_key": "q002",
                           "page": 1, "active_packaged_media_status": "active"},
                          {"usage_id": "u3", "xref": 13, "asset": assets[3],
                           "role": "answer_reference", "privacy": "private_reviewer_only",
                           "pdftohtml_name": "p-002_002.png", "question_key": "q002",
                           "page": 1, "active_packaged_media_status": "active"}],
            site_type="single_choice", marker="QUESTION 2", upstream_pages=[1])
    q3 = _q(3, source_kind="typed_text_with_answer_image", answer_raw="B",
            options_mode="text_options",
            entries=[{"label": "A", "text": "synthetic option A3"},
                     {"label": "B", "text": "synthetic option B3"}],
            media_usages=[{"usage_id": "u4", "xref": 13, "asset": assets[3],
                           "role": "answer_reference", "privacy": "private_reviewer_only",
                           "pdftohtml_name": "p-002_002.png", "question_key": "q003",
                           "page": 1, "active_packaged_media_status": "active"}],
            site_type="multiple_select", marker="QUESTION 3", upstream_pages=[1])

    for name, rec in (("q001", q1), ("q002", q2), ("q003", q3)):
        with open(os.path.join(v1, "questions", f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1)

    usages = [u for q in (q1, q2, q3) for u in q["media_usages"]]
    with open(os.path.join(v1, "asset-usage.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": "structured-v1", "usages": usages}, f, indent=1)

    with open(os.path.join(v1, "source-answer-index.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": "structured-v1",
                   "questions": {"q001": {"source_kind": "owner_typed_text"},
                                 "q002": {"source_kind": "answer_reference_image"},
                                 "q003": {"source_kind": "typed_text_with_answer_image"}}}, f, indent=1)

    with open(os.path.join(v1, "source-manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": "structured-v1", "exam_code": "SYN-001",
                   "source_pdf": {"verified": {"page_count": 1}}}, f, indent=1)

    # one page record with fully classified synthetic text runs
    with open(os.path.join(v1, "pages", "page-0001.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": "structured-v1", "page": 1, "text_runs": [
            {"classification": "question_content", "text": "QUESTION 1"},
            {"classification": "question_content", "text": "Synthetic stem 1"},
            {"classification": "question_content", "text": "QUESTION 2"},
            {"classification": "question_content", "text": "Synthetic stem 2"},
            {"classification": "question_content", "text": "QUESTION 3"},
            {"classification": "question_content", "text": "Synthetic stem 3"},
        ]}, f, indent=1)

    # pinned-upstream split format (what extract_owner_pdf.py would emit)
    def split_rec(q, key):
        return {"question_key": key, "source_number": q["source_number"],
                "marker": q["marker"], "pages": q["upstream_pages_field"],
                "stem": q["stem"]["upstream_normalized"],
                "options": {e["label"].lower(): e["text"] for e in q["options"]["entries"]},
                "answer_raw": q["answer"]["raw_text"],
                "question_images": [u["pdftohtml_name"] for u in q["media_usages"]
                                    if u["role"] in ("question_prompt", "exhibit")],
                "answer_images": [u["pdftohtml_name"] for u in q["media_usages"]
                                  if u["role"] == "answer_reference"],
                "layout_profile": q["layout_profile"]}
    split = {k: split_rec(q, k) for k, q in (("q001", q1), ("q002", q2), ("q003", q3))}
    with open(os.path.join(up, "extracted", "split.json"), "w", encoding="utf-8") as f:
        json.dump(split, f, indent=1, sort_keys=True)

    cfg = {
        "schema_version": "structured-v1",
        "exam_code": "SYN-001",
        "generated_by": {"worker": "public synthetic tests", "date": "2026-11-13",
                         "environment": "unittest"},
        "paths": {"pdf": os.path.join(root, "synthetic.pdf"),
                  "repo": root, "out_dir": v1, "upstream_out": up,
                  "pmap": os.path.join(root, "pmap.json"),
                  "build_stats": os.path.join(root, "build-stats.json"),
                  "repo_relative_out_dir": "structured/v1"},
        "source": {"expected_pdf_sha256": "0" * 64, "expected_bytes": 0},
        "upstream": {"repo": "msaqlainhaneef1/certpassly-exam-pipeline",
                     "commit": "13dea6bab662ab1c4bbf87017e912e519907c8bc"},
        "layout": {"cover_pages": [], "marketing_pages": [],
                   "visual_option_placeholder_texts": []},
        "evidence": {}, "carried_unresolved": [],
        "schema": {"title": "synthetic", "description": "synthetic",
                   "source_kind_extension": ["typed_text_with_answer_image"]},
        "expected": {
            "pages": 1, "questions": 3, "assets": 3, "usages": 4,
            "roles": {"question_prompt": 2, "exhibit": 0, "answer_reference": 2,
                      "cover_decoration": 0},
            "answer_kinds": {"owner_typed_text": 1, "typed_text_with_answer_image": 1,
                             "answer_reference_image": 1},
            "unknown_types": 0,
            "cover_marketing_runs": 0, "question_content_runs": 6,
            "unresolved_min": 0,
        },
        "report_notes": {"known_limitations": ["synthetic fixture"],
                         "no_false_completion_statement": "synthetic"},
        "reconcile_notes": {"count_systems_explained": ["synthetic"],
                            "no_silent_drops_statement": "synthetic"},
        "manifest": {"pdf_repo_path": "synthetic.pdf", "extract_log_line": "synthetic",
                     "inventory": [], "immutability_untouched": [],
                     "immutability_added": []},
        "export_notes": {"known_divergences": [], "site_taxonomy_note": "synthetic"},
    }
    return cfg
