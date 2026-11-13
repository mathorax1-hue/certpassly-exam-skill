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
        "exam_code": "SYN-001",
        "question_id": f"q{n:03d}",
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
            "selection_candidates_unapproved": [],
            "privacy": "private_reviewer_only" if source_kind != "owner_typed_text" else "private",
        },
        "media_usages": media_usages,
        "question_type": {"site_format_type": site_type, "basis": "synthetic test basis",
                          "confidence": "high"},
        "layout_profile": "question_n_correct_answer",
        "editorial_overlay_status": "active_in_current_site_draft",
        "provenance": {"pdf_sha256": "0" * 64,
                       "extracted_by": "synthetic fixture",
                       "upstream_split_question_key": f"q{n:03d}"},
        "review": {"status": "machine_extracted", "human_approved": False,
                   "visual_review_required": source_kind != "owner_typed_text"},
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
            media_usages=[{"usage_id": "u-p1-1-x11", "xref": 11, "asset": f"{assets[1]}.png", "asset_sha256": assets[1],
                           "role": "question_prompt", "privacy": "learner_visible_after_review",
                           "pdftohtml_name": "p-001_001.png", "question_key": "q001",
                           "page": 1, "active_packaged_media_status": "active"}],
            site_type="single_choice", marker="QUESTION 1", upstream_pages=[1])
    q2 = _q(2, source_kind="answer_reference_image", answer_raw="",
            options_mode="in_question_image", entries=[],
            media_usages=[{"usage_id": "u-p1-1-x12", "xref": 12, "asset": f"{assets[2]}.png", "asset_sha256": assets[2],
                           "role": "question_prompt", "privacy": "learner_visible_after_review",
                           "pdftohtml_name": "p-002_001.png", "question_key": "q002",
                           "page": 1, "active_packaged_media_status": "active"},
                          {"usage_id": "u-p1-1-x13", "xref": 13, "asset": f"{assets[3]}.png", "asset_sha256": assets[3],
                           "role": "answer_reference", "privacy": "private_reviewer_only",
                           "pdftohtml_name": "p-002_002.png", "question_key": "q002",
                           "page": 1, "active_packaged_media_status": "active"}],
            site_type="single_choice", marker="QUESTION 2", upstream_pages=[1])
    q3 = _q(3, source_kind="typed_text_with_answer_image", answer_raw="B",
            options_mode="text_options",
            entries=[{"label": "A", "text": "synthetic option A3"},
                     {"label": "B", "text": "synthetic option B3"}],
            media_usages=[{"usage_id": "u-p1-2-x13", "xref": 13, "asset": f"{assets[3]}.png", "asset_sha256": assets[3],
                           "role": "answer_reference", "privacy": "private_reviewer_only",
                           "pdftohtml_name": "p-002_002.png", "question_key": "q003",
                           "page": 1, "active_packaged_media_status": "active"}],
            site_type="multiple_select", marker="QUESTION 3", upstream_pages=[1])
    q4 = _q(4, source_kind="missing", answer_raw="",
            options_mode="none", entries=[],
            media_usages=[],
            site_type="unknown", marker="QUESTION 4", upstream_pages=[1])
    q5 = _q(5, source_kind="typed_text_with_answer_image", answer_raw="A",
            options_mode="in_question_image", entries=[],
            media_usages=[{"usage_id": "u-p1-2-x12", "xref": 12, "asset": f"{assets[2]}.png", "asset_sha256": assets[2],
                           "role": "question_prompt", "privacy": "learner_visible_after_review",
                           "pdftohtml_name": "p-001_002.png", "question_key": "q005",
                           "page": 1, "active_packaged_media_status": "active"},
                          {"usage_id": "u-p1-3-x13", "xref": 13, "asset": f"{assets[3]}.png", "asset_sha256": assets[3],
                           "role": "answer_reference", "privacy": "private_reviewer_only",
                           "pdftohtml_name": "p-001_003.png", "question_key": "q005",
                           "page": 1, "active_packaged_media_status": "active"}],
            site_type="inline_dropdown", marker="QUESTION 5", upstream_pages=[1])
    q5["question_type"] = {"site_format_type": "inline_dropdown",
                           "basis": "visual item classified dropdown by pinned analyze_visual.py "
                                    "OCR pass; typed source literal 'A' preserved but not used for "
                                    "typing (key status unknown)",
                           "confidence": "medium"}
    q5["answer"]["typed_key_status"] = (
        "source_literal_only_key_status_unknown: the typed text is preserved verbatim as source "
        "evidence but is NOT a validated widget type or complete key")

    for name, rec in (("q001", q1), ("q002", q2), ("q003", q3), ("q004", q4), ("q005", q5)):
        with open(os.path.join(v1, "questions", f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1)

    usages = [u for q in (q1, q2, q3, q5) for u in q["media_usages"]]
    with open(os.path.join(v1, "asset-usage.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": "structured-v1", "usages": usages}, f, indent=1)

    with open(os.path.join(v1, "source-answer-index.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": "structured-v1",
                   "questions": {"q001": {"source_kind": "owner_typed_text",
                                          "owner_key_verified": False},
                                 "q002": {"source_kind": "answer_reference_image",
                                          "owner_key_verified": False},
                                 "q003": {"source_kind": "typed_text_with_answer_image",
                                          "owner_key_verified": False},
                                 "q004": {"source_kind": "missing",
                                          "owner_key_verified": False},
                                 "q005": {"source_kind": "typed_text_with_answer_image",
                                          "owner_key_verified": False}},
                   "answer_count": {"owner_typed_text": 1, "typed_text_with_answer_image": 2,
                                    "answer_reference_image": 1, "missing": 1}}, f, indent=1)

    with open(os.path.join(v1, "source-manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": "structured-v1", "exam_code": "SYN-001",
                   "source_pdf": {"sha256": "0" * 64, "bytes": 0,
                                  "verified": {"page_count": 1}}}, f, indent=1)

    # question-index / unresolved / visual-transcription-drafts / README
    with open(os.path.join(v1, "question-index.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": "structured-v1", "exam_code": "SYN-001",
                   "question_count": 5,
                   "order": [{"question_id": f"q{n:03d}", "source_number": n, "pages": [1],
                              "type": [q1, q2, q3, q4, q5][n - 1]["question_type"]["site_format_type"],
                              "answer_source_kind": [q1, q2, q3, q4, q5][n - 1]["answer"]["source_kind"],
                              "editorial_overlay_status": "active_in_current_site_draft"}
                             for n in range(1, 6)],
                   "ids_are_sequential_1_to_n": True,
                   "duplicate_or_missing_markers": []}, f, indent=1)
    with open(os.path.join(v1, "unresolved.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": "structured-v1", "exam_code": "SYN-001", "count": 0,
                   "policy": "Fail-closed: every ambiguity is listed, none is silently dropped.",
                   "items": []}, f, indent=1)
    with open(os.path.join(v1, "visual-transcription-drafts.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": "structured-v1", "exam_code": "SYN-001",
                   "status": "PRIVATE_DRAFT_UNAPPROVED",
                   "note": "synthetic fixture; no candidate is approved",
                   "entries": {}}, f, indent=1)
    with open(os.path.join(v1, "README.md"), "w", encoding="utf-8") as f:
        f.write("# SYN-001 structured/v1 - synthetic fixture\n")

    # emit the extraction schema exactly as the real builder would
    # (build_schema is importable without third-party deps)
    from certpassly.phase1.build_structured_v1 import build_schema
    schema_text, _obj = build_schema({
        "schema": {"title": "CertPassly private structured extraction layer v1 (SYN-001 pilot)",
                   "description": "Machine-checkable schema for the source-grounded extraction layer.",
                   "source_kind_extension": ["typed_text_with_answer_image"]}})
    with open(os.path.join(v1, "extraction-schema.json"), "w", encoding="utf-8") as f:
        f.write(schema_text)

    # one page record with fully classified synthetic text runs
    with open(os.path.join(v1, "pages", "page-0001.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": "structured-v1", "page": 1, "rotation": 0,
                   "raw_mediabox": [0, 0, 612, 792], "display_rect": [0, 0, 612, 792],
                   "coordinate_note": "synthetic fixture",
                   "classification": "question_content", "questions_on_page": ["q001", "q002", "q003", "q004", "q005"],
                   "text_runs": [
            {"run_id": f"p0001-r{i:03d}", "text": t, "bbox_display": [60, 60 + 14 * i, 300, 74 + 14 * i],
             "font": "Helv", "size": 11, "flags": 0, "classification": "question_content"}
            for i, t in enumerate([
                "QUESTION 1", "Synthetic stem 1", "QUESTION 2", "Synthetic stem 2",
                "QUESTION 3", "Synthetic stem 3", "QUESTION 4", "Synthetic stem 4",
                "QUESTION 5", "Synthetic stem 5"])
        ],
        "images": [{"xref": 11, "bbox_display": [60, 200, 380, 320],
                    "asset": f"{assets[1]}.png", "asset_sha256": assets[1],
                    "usage_id": "u-p1-1-x11", "role": "question_prompt", "privacy": "learner_visible_after_review"},
                   {"xref": 12, "bbox_display": [60, 200, 380, 360],
                    "asset": f"{assets[2]}.png", "asset_sha256": assets[2],
                    "usage_id": "u-p1-2-x12", "role": "question_prompt", "privacy": "learner_visible_after_review"},
                   {"xref": 13, "bbox_display": [60, 90, 380, 250],
                    "asset": f"{assets[3]}.png", "asset_sha256": assets[3],
                    "usage_id": "u-p1-3-x13", "role": "answer_reference", "privacy": "private_reviewer_only"}],
        "vector_drawings": {"count": 0, "items": [], "note": "synthetic"},
        "links": [], "annotations": []}, f, indent=1)

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
    split = {k: split_rec(q, k) for k, q in (("q001", q1), ("q002", q2), ("q003", q3), ("q004", q4), ("q005", q5))}
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
            "pages": 1, "questions": 5, "assets": 3, "usages": 6,
            "roles": {"question_prompt": 3, "exhibit": 0, "answer_reference": 3,
                      "cover_decoration": 0},
            "answer_kinds": {"owner_typed_text": 1, "typed_text_with_answer_image": 2,
                             "answer_reference_image": 1, "missing": 1},
            "unknown_types": 1,
            "overlay": {"active_in_current_site_draft": 5},
            "cover_marketing_runs": 0, "question_content_runs": 10,
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
