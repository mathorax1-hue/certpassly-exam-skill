#!/usr/bin/env python3
"""Read-only, synthetic-only V2 compatibility and security audit.

Upstream is checked out externally at an immutable Git SHA. Never copy exam
content, answers, source screenshots or third-party source code to this repo.
"""
from __future__ import annotations

import argparse
import copy
import importlib
import json
import subprocess
import sys
from pathlib import Path

UPSTREAM_REPO = "msaqlainhaneef1/certpassly-exam-pipeline"
PIN = "462fd237ae7f0c607bb00229e173b22d0f3298d2"


def summarize_checks(checks):
    counts = {"pass": 0, "fail": 0, "unverified": 0}
    for check in checks:
        counts[check["status"]] += 1
    return counts


def gate_decision(checks):
    if any(c["status"] == "fail" for c in checks):
        return "BLOCKED_FAIL"
    if any(c["status"] == "unverified" for c in checks):
        return "BLOCKED_UNVERIFIED"
    return "PASS_CONTRACT_ONLY"


def run_audit(root: Path):
    checks = []

    def record(check_id, status, detail):
        checks.append({"id": check_id, "status": status, "detail": detail})

    try:
        sha = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        record("immutable_source_pin", "pass" if sha == PIN else "fail", sha)
    except Exception as exc:
        record("immutable_source_pin", "fail", repr(exc))
        sha = None

    sys.path.insert(0, str(root / "scripts"))
    try:
        vq = importlib.import_module("validate_question_v2")
        mv = importlib.import_module("migrate_v1_to_v2")
        import jsonschema
        record("python_dependencies", "pass", "V2 validator, migrator, jsonschema imported")
    except Exception as exc:
        record("python_dependencies", "fail", repr(exc))
        return {"source_sha": sha, "checks": checks}

    registry = vq.load_registry()
    schema = vq.load_schema()
    allow = vq.load_allowlist()
    keys = list(registry["types"])
    enum = schema["properties"]["type"]["enum"]
    good_registry = len(keys) == 30 and set(keys) == set(enum)
    good_registry &= "image_legacy" not in keys
    record("all_30_registry_types", "pass" if good_registry else "fail",
           "Registry has %d types, schema has %d; image_legacy excluded" % (len(keys), len(enum)))

    active = [k for k in keys if registry["types"][k].get("publishable")]
    record("publishable_type_coverage", "unverified",
           "%d of 30 registry types marked publishable; renderer behavior for all 30 not tested" % len(active))

    examples_dir = root / "reference" / "site-format" / "v2" / "examples"
    examples = sorted(examples_dir.glob("*.json"))
    wrong = []
    covered = set()
    for path in examples:
        doc = json.loads(path.read_text(encoding="utf-8"))
        errors = vq.validate_doc(doc, schema, registry, allow, use_jsonschema=True)
        expected_bad = path.name.startswith("invalid-")
        if bool(errors) != expected_bad:
            wrong.append(path.name)
        if not expected_bad:
            covered.add(doc["type"])
    record("official_v2_examples", "pass" if not wrong and examples else "fail",
           "%d examples; unexpected outcomes: %s" % (len(examples), wrong))
    record("type_examples_30_of_30", "unverified" if len(covered) < 30 else "pass",
           "%d/30 types represented by committed valid examples: %s" %
           (len(covered), sorted(covered)))

    base = json.loads((examples_dir / "valid-single_choice.json").read_text(encoding="utf-8"))
    variations = [
        ("nested_answer_key", lambda d: d["learner"].setdefault("interaction", {}).update(
            {"correct_option_ids": ["a"]})),
        ("html_script", lambda d: d["learner"]["stem"].update(
            {"format": "html", "text": "<script>alert(1)</script>"})),
        ("html_unquoted_event", lambda d: d["learner"]["stem"].update(
            {"format": "html", "text": "<p onclick=alert(1)>Question</p>"})),
        ("html_unquoted_javascript_href", lambda d: d["learner"]["stem"].update(
            {"format": "html", "text": "<a href=javascript:alert(1)>Question</a>"})),
        ("svg_event", lambda d: d["learner"]["stem"].update(
            {"format": "svg", "text": "<svg onload='alert(1)'><text>Question</text></svg>"})),
        ("answer_not_found_scored", lambda d: d["meta"].update(
            {"answer_key_status": "answer_not_found", "scoring_excluded": False})),
        ("v1_status_alias", lambda d: d["meta"].update(
            {"answer_key_status": "as_in_source_file"})),
        ("approved_status", lambda d: d["meta"].update(
            {"record_status": "approved"})),
    ]
    for name, mutate in variations:
        doc = copy.deepcopy(base)
        mutate(doc)
        errors = vq.validate_doc(doc, schema, registry, allow, use_jsonschema=True)
        record("reject_" + name, "pass" if errors else "fail",
               "Rejected with %d issue(s)" % len(errors) if errors else
               "Unsafe/forbidden document accepted by validator")

    # Source allow-list permits raster data images only; test that an SVG
    # data URI cannot slip through on the override path.
    doc = copy.deepcopy(base)
    doc["meta"]["allow_data_image"] = True
    doc["meta"]["data_image_justification"] = "Synthetic regression only"
    doc["learner"]["media"] = [{
        "id": "s", "kind": "image", "alt": "Synthetic graphic",
        "sha256": "a" * 64, "href": "data:image/svg+xml,<svg onload=alert(1) />"
    }]
    err = vq.validate_doc(doc, schema, registry, allow, use_jsonschema=True)
    record("reject_svg_data_uri", "pass" if err else "fail",
           "Rejected" if err else "SVG data URI accepted although only raster images are allowed")

    # IMPORTANT: use wholly invented metadata; no owner PDF or screenshot.
    # Every reviewer-only original must remain inaccessible to candidates.
    item = {
        "question_key": "qSynthetic001",
        "question_version_key": "qSynthetic001-v1",
        "question_type": "hotspot_single",
        "prompt_text": "Select the indicated interface location.",
        "answer_key_status": "owner_key",
        "answer_key": {"region_ids": ["region1"]},
        "response_schema": {"type": "hotspot_single", "content": {
            "regions": [{"id": "region1", "shape": "rect",
                         "normalized_coordinates": [0.1, 0.1, 0.5, 0.5],
                         "label": "Example button"}]
        }}
    }
    for filename in ("qSynthetic001-answer-area.png",
                     "qSynthetic001-answer-review.png",
                     "qSynthetic001-answer_review.png"):
        rows = [{
            "path": "media/" + filename,
            "kind": "answer_area",
            "visibility": "reviewer_only",
            "alt_text": "Marked correct selection (synthetic)",
            "sha256": "a" * 64
        }]
        try:
            result, issues = mv.migrate_item(
                item, exam_key="SYNTHETIC", media_rows=rows,
                media_dir=None, src_root=None, draft=None, trans=None,
                excluded=set()
            )
            exposed = [
                media.get("href") for media in result["learner"].get("media", [])
                if filename in (media.get("href") or "")
            ]
            record("reviewer_only_" + filename,
                   "fail" if exposed else "pass",
                   "Reviewer-only asset exposed in learner media: %s" % exposed
                   if exposed else "Reviewer-only asset not sent to learner")
        except Exception as exc:
            record("reviewer_only_" + filename, "fail", repr(exc))

    record("website_rendering_accessibility_scoring", "unverified",
           "A Python converter branch cannot prove browser rendering, keyboard/touch, responsive layout, or server scoring.")
    record("live_site_reveal_security", "unverified",
           "Site V2 docs list three existing answer-reveal issues; current website fixes require independent verification.")
    record("real_pdf_cross_vendor_fidelity", "unverified",
           "No private owner PDFs, answer keys, or real exam screenshots are used in public tests.")
    return {"source_sha": sha, "checks": checks}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--upstream", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--ci-security-mode", action="store_true",
                    help="Exit successfully when there are zero technical failures, but preserve unverified release blockers")
    args = ap.parse_args(argv)
    report = run_audit(args.upstream.resolve())
    report.update({
        "report_schema": "certpassly-v2-contract-audit.v1",
        "source_repository": UPSTREAM_REPO,
        "expected_source_sha": PIN,
        "counts": summarize_checks(report["checks"]),
        "gate": gate_decision(report["checks"]),
        "notes": "Technical and synthetic audit only; not independent answer review or site acceptance."
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": report["gate"], "counts": report["counts"]}, indent=2))
    for c in report["checks"]:
        if c["status"] != "pass":
            print("%s %s: %s" % (c["status"].upper(), c["id"], c["detail"]))
    if report["gate"] == "BLOCKED_FAIL":
        return 1
    if report["gate"] == "BLOCKED_UNVERIFIED" and not args.ci_security_mode:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
