#!/usr/bin/env python3
"""Phase 1 extraction: validation and completeness contract for structured/v1 (public toolkit).

Usage: python -m certpassly.phase1.validate_structured_v1 <config.json> [--no-report]

Every expected count, hash and narrative note comes from the config
(config.expected, config.source, config.report_notes); nothing exam-specific
is hardcoded. Exit code 0 only if every check passes. Writes/merges
extraction-report.json unless --no-report.
"""
from __future__ import annotations
import json, os, re, sys
from collections import Counter

from . import p1common as P

# NOTE: jsonschema is imported lazily inside main(); the public CI runner has a
# stdlib-only environment.

SCHEMA_DEF_Q = {"$ref": "#/definitions/question_record"}
SCHEMA_DEF_P = {"$ref": "#/definitions/page_record"}


def main(cfg_path, write_report=True):
    from jsonschema import Draft7Validator
    cfg = P.load_config(cfg_path)
    paths = cfg["paths"]
    v1_dir = paths["out_dir"]
    pdf = paths["pdf"]
    exp = cfg.get("expected", {})
    exam = cfg["exam_code"]
    R = P.Result()

    # ---------- structure ----------
    for d in ["questions", "pages", "assets", "export/upstream-extract-compatible",
              "export/site-format-v1-draft"]:
        R.check(f"dir_exists:{d}", os.path.isdir(f"{v1_dir}/{d}"))
    for f in ["README.md", "source-manifest.json", "extraction-schema.json",
              "question-index.json", "asset-usage.json", "source-answer-index.json",
              "unresolved.json", "visual-transcription-drafts.json"]:
        R.check(f"file_exists:{f}", os.path.isfile(f"{v1_dir}/{f}"))

    n_q = exp.get("questions")
    n_p = exp.get("pages")
    n_a = exp.get("assets")
    qfiles = sorted(f for f in os.listdir(f"{v1_dir}/questions") if f.endswith(".json"))
    R.check(f"questions_count_{n_q}", len(qfiles) == n_q, f"{len(qfiles)} files (expected {n_q})")
    R.check("questions_names_sequential",
            [f[:-5] for f in qfiles] == [f"q{i:03d}" for i in range(1, n_q + 1)])

    pfiles = sorted(f for f in os.listdir(f"{v1_dir}/pages") if f.endswith(".json"))
    R.check(f"pages_count_{n_p}", len(pfiles) == n_p, f"{len(pfiles)} files (expected {n_p})")
    R.check("pages_names_sequential",
            [f[:-5] for f in pfiles] == [f"page-{i:04d}" for i in range(1, n_p + 1)])

    afiles = sorted(os.listdir(f"{v1_dir}/assets"))
    R.check(f"assets_count_{n_a}", len(afiles) == n_a, f"{len(afiles)} files (expected {n_a})")

    # ---------- schema ----------
    schema = P.jload(f"{v1_dir}/extraction-schema.json")
    vq = Draft7Validator({**schema, **SCHEMA_DEF_Q})
    vp = Draft7Validator({**schema, **SCHEMA_DEF_P})
    qerr, perr = 0, 0
    for f in qfiles:
        for e in vq.iter_errors(P.jload(f"{v1_dir}/questions/{f}")):
            qerr += 1
            if qerr <= 3:
                print(f"  schema error {f}: {e.message[:160]}")
    for f in pfiles:
        for e in vp.iter_errors(P.jload(f"{v1_dir}/pages/{f}")):
            perr += 1
            if perr <= 3:
                print(f"  schema error {f}: {e.message[:160]}")
    R.check("schema_valid_questions", qerr == 0, f"{qerr} errors")
    R.check("schema_valid_pages", perr == 0, f"{perr} errors")

    # ---------- source integrity ----------
    man = P.jload(f"{v1_dir}/source-manifest.json")
    exp_sha = cfg.get("source", {}).get("expected_pdf_sha256")
    R.check("manifest_pdf_sha_known", exp_sha and man["source_pdf"]["sha256"] == exp_sha)
    # P0-C (director audit 2026-11-13): a missing configured PDF is a FAILED
    # check, never a silently skipped one - the validator must not report a
    # source-integrity pass on stale cached files without the actual source.
    if pdf and os.path.isfile(pdf):
        R.check("pdf_sha256_readback", P.sha256_file(pdf) == man["source_pdf"]["sha256"])
        R.check("pdf_bytes_readback", os.path.getsize(pdf) == man["source_pdf"]["bytes"])
    else:
        R.check("pdf_present_for_readback", False,
                f"configured source PDF is missing: {pdf!r}; cannot validate source integrity")

    # ---------- question records ----------
    qs = {f[:-5]: P.jload(f"{v1_dir}/questions/{f}") for f in qfiles}
    R.check("q_source_numbers_sequential",
            [qs[f"q{i:03d}"]["source_number"] for i in range(1, n_q + 1)] == list(range(1, n_q + 1)))
    R.check("q_ids_unique", len(set(q["question_id"] for q in qs.values())) == n_q)
    R.check("q_stems_nonempty", all(q["stem"]["raw"].strip() for q in qs.values()))
    R.check("q_review_fail_closed",
            all(q["review"]["human_approved"] is False and q["review"]["status"] == "machine_extracted"
                for q in qs.values()))
    R.check("q_provenance_pdf_sha",
            all(q["provenance"]["pdf_sha256"] == man["source_pdf"]["sha256"] for q in qs.values()))
    R.check("q_pages_reference_real_pages",
            all(1 <= p <= n_p for q in qs.values() for p in q["pages"]))
    kinds = Counter(q["answer"]["source_kind"] for q in qs.values())
    _t, _i = kinds.get("owner_typed_text", 0), kinds.get("answer_reference_image", 0)
    _b = kinds.get("typed_text_with_answer_image", 0)
    _ak_name = (f"answer_kinds_{_t}_typed_{_i}_image" if not _b else
                f"answer_kinds_{_t}_typed_{_i}_image_{_b}_both")
    R.check(_ak_name,
            all(kinds.get(k) == v for k, v in exp.get("answer_kinds", {}).items())
            and sum(kinds.values()) == n_q, dict(kinds))
    types = Counter(q["question_type"]["site_format_type"] for q in qs.values())
    _u = types.get("unknown", 0)
    R.check(f"types_sum_{n_q}_no_unknown" if not _u else f"types_sum_{n_q}_unknown_{_u}",
            sum(types.values()) == n_q and _u == exp.get("unknown_types", 0),
            dict(types))
    overlay = Counter(q["editorial_overlay_status"] for q in qs.values())
    _oa = overlay.get("active_in_current_site_draft", 0)
    _os = overlay.get("superseded_by_editorial_replacement", 0)
    R.check(f"overlay_{_oa}_active_{_os}_superseded",
            all(overlay.get(k) == v for k, v in exp.get("overlay", {}).items())
            and sum(overlay.values()) == n_q, dict(overlay))

    # P1-5 (director audit 2026-11-13): editorial overlay candidates must stay
    # OUT of the PDF answer-transcription candidates, carry the explicit
    # editorial provenance, and never be approved. Crossed provenance (the
    # same value appearing in both fields) is a validation FAILURE - this is
    # the regression for the AB-900 q002 defect the director identified.
    EDITORIAL_PROVENANCE = "original_certpassly_team_editorial_not_owner_pdf"
    ed_crossed, ed_bad_prov = [], []
    for q, qr_ in qs.items():
        ans = qr_["answer"]
        cand_vals = {json.dumps(c.get("value"), sort_keys=True)
                     for c in ans.get("selection_candidates_unapproved", [])}
        for e in ans.get("editorial_overlay_candidates", []):
            if json.dumps(e.get("value"), sort_keys=True) in cand_vals:
                ed_crossed.append(q)
            if (e.get("provenance") != EDITORIAL_PROVENANCE or e.get("approved") is not False):
                ed_bad_prov.append(q)
    R.check("editorial_overlay_never_a_transcription_candidate",
            not ed_crossed, f"crossed provenance at {ed_crossed[:5]}")
    R.check("editorial_overlay_provenance_explicit_and_unapproved",
            not ed_bad_prov, f"bad provenance/approval at {ed_bad_prov[:5]}")

    bad_assets = []
    for q, qr_ in qs.items():
        for u in qr_["media_usages"]:
            ap = f"{v1_dir}/assets/{u['asset']}"
            if not os.path.isfile(ap) or P.sha256_file(ap) != u["asset_sha256"]:
                bad_assets.append((q, u["asset"]))
    R.check("usage_assets_exist_and_hash_match", not bad_assets, bad_assets[:3])

    leak = [q for q, qr_ in qs.items()
            if qr_["answer"]["source_kind"] in ("answer_reference_image", "typed_text_with_answer_image")
            and any(u["privacy"] != "private_reviewer_only" for u in qr_["media_usages"]
                    if u["role"] == "answer_reference")]
    R.check("answer_images_private_reviewer_only", not leak, leak[:5])

    # ---------- page records ----------
    pages = {f[:-5]: P.jload(f"{v1_dir}/pages/{f}") for f in pfiles}
    unassigned = []
    cover_runs = 0
    q_runs = 0
    for pk, p in pages.items():
        for r in p["text_runs"]:
            if r["classification"] == "unassigned":
                unassigned.append((pk, r["run_id"], r["text"][:40]))
            elif r["classification"] == "cover_or_marketing_before_first_question":
                cover_runs += 1
            elif r["classification"] == "question_content":
                q_runs += 1
    R.check("text_coverage_no_unassigned", not unassigned, unassigned[:5])
    R.check("text_coverage_counts",
            cover_runs == exp.get("cover_marketing_runs") and q_runs == exp.get("question_content_runs"),
            f"cover={cover_runs} question={q_runs}")

    badimg = []
    for pk, p in pages.items():
        for im in p["images"]:
            if im["role"] in (None, "unknown_requires_review"):
                badimg.append((pk, im["xref"]))
            if not os.path.isfile(f"{v1_dir}/assets/{im['asset']}"):
                badimg.append((pk, im["xref"], "asset missing"))
    R.check("page_images_role_and_asset_ok", not badimg, badimg[:5])

    page_xrefs = {}
    for pk, p in pages.items():
        page_xrefs[p["page"]] = {im["xref"] for im in p["images"]}
    usage_xrefs = {}
    au = P.jload(f"{v1_dir}/asset-usage.json")
    for u in au["usages"]:
        usage_xrefs.setdefault(u["page"], set()).add(u["xref"])
    all_pgs = set(page_xrefs) | set(usage_xrefs)
    R.check("page_xrefs_equal_usage_xrefs",
            all(page_xrefs.get(pg, set()) == usage_xrefs.get(pg, set()) for pg in all_pgs))

    # ---------- asset usage ----------
    roles = Counter(u["role"] for u in au["usages"])
    R.check(f"roles_{exp.get('usages')}_total", sum(roles.values()) == exp.get("usages"), dict(roles))
    R.check("roles_breakdown",
            all(roles.get(k, 0) == v for k, v in exp.get("roles", {}).items()), dict(roles))
    R.check("usage_ids_unique", len({u["usage_id"] for u in au["usages"]}) == exp.get("usages"))
    R.check(f"unique_binaries_{n_a}", len({u["asset"] for u in au["usages"]}) == n_a)
    R.check("asset_files_equal_usage_assets",
            {u["asset"] for u in au["usages"]} == set(afiles))
    sup = Counter(u.get("active_packaged_media_status") for u in au["usages"])
    _sa, _ss = sup.get("active", 0), sup.get("superseded_by_editorial_replacement", 0)
    R.check(f"superseded_{_ss}_active_{_sa}",
            all(sup.get(k) == v for k, v in exp.get("packaged_status", {}).items()), dict(sup))
    arch = sum(1 for u in au["usages"] if u.get("archived_media_match"))
    R.check(f"archived_media_matches_{exp.get('archived_matches', 0)}", arch == exp.get("archived_matches", 0), f"{arch}")

    # ---------- answer index / drafts / unresolved ----------
    sai = P.jload(f"{v1_dir}/source-answer-index.json")
    R.check(f"answer_index_{n_q}", len(sai["questions"]) == n_q)
    R.check("answer_index_kinds", sai["answer_count"] == exp.get("answer_kinds"))
    R.check("answer_index_never_verified",
            all(v["owner_key_verified"] is False for v in sai["questions"].values()))
    vtd = P.jload(f"{v1_dir}/visual-transcription-drafts.json")
    R.check("visual_drafts_marked_unapproved", vtd["status"] == "PRIVATE_DRAFT_UNAPPROVED")

    def _no_approved_true(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "approved" and v is True:
                    return False
                if not _no_approved_true(v):
                    return False
        elif isinstance(o, list):
            return all(_no_approved_true(x) for x in o)
        return True
    R.check("visual_drafts_no_approved_true", _no_approved_true(vtd))
    unres = P.jload(f"{v1_dir}/unresolved.json")
    R.check("unresolved_listed_not_empty",
            unres["count"] == len(unres["items"])
            and unres["count"] >= exp.get("unresolved_min", 1),
            f"count={unres['count']}")

    # ---------- exports fail-closed ----------
    ex_q = f"{v1_dir}/export/site-format-v1-draft/question-type-draft.json"
    ex_b = f"{v1_dir}/export/site-format-v1-draft/export-blockers.json"
    R.check("site_export_exists", os.path.isfile(ex_q) and os.path.isfile(ex_b))
    if os.path.isfile(ex_q):
        site = P.jload(ex_q)
        R.check("site_export_no_stems", all("stem" not in v for v in site["question_types"].values()))
        R.check("site_export_no_answers", all("answer" not in v and "key" not in v
                                              for v in site["question_types"].values()))
        blockers = P.jload(ex_b)
        R.check("site_export_all_gated", blockers["blocked_questions"] == n_q)
        # P0-B/P0-D (director audit 2026-11-13): honest blocker counters and a
        # real cross-gate - every unknown-type, low-confidence or
        # unverified-typed-key question MUST carry an explicit export blocker;
        # every blocker row MUST have at least one reason. The gate RECOMPUTES
        # the rows-with-reasons from the items themselves; stored counters are
        # cross-checked, never trusted alone.
        items = blockers.get("items", [])
        recomputed_rows = sum(1 for b in items if b.get("cannot_export_without_review"))
        R.check("site_export_all_rows_have_reasons",
                recomputed_rows == blockers["blocked_questions"] == n_q
                and blockers.get("blocked_questions_with_reasons", recomputed_rows) == recomputed_rows
                and blockers.get("all_rows_have_reasons") is True)
        by_q = {b["question"]: b["cannot_export_without_review"] for b in items}
        must_block = [q for q, r in qs.items()
                      if r["question_type"]["site_format_type"] == "unknown"
                      or r["question_type"]["confidence"] == "low"
                      or r["answer"].get("typed_key_status")]
        unblocked = [q for q in must_block if not by_q.get(q)]
        R.check(f"unverified_types_and_keys_export_blocked_{len(must_block)}",
                not unblocked, unblocked[:5])
    answer_assets = {u["asset"] for u in au["usages"] if u["role"] == "answer_reference"}
    leaked = []
    for root, _, files in os.walk(f"{v1_dir}/export/site-format-v1-draft"):
        for f in files:
            if f in answer_assets:
                leaked.append(os.path.join(root, f))
    R.check("no_answer_asset_bytes_in_site_export", not leaked, leaked[:3])
    leak_text = []
    for root, _, files in os.walk(f"{v1_dir}/export/site-format-v1-draft"):
        for f in files:
            if not f.endswith(".json"):
                continue
            txt = open(os.path.join(root, f), encoding='utf-8').read()
            if re.search(r'"(answer_raw|answer_text|selected)"\s*:\s*"[^"\s]', txt):
                leak_text.append(f)
    R.check("no_answer_text_payload_in_site_export", not leak_text, leak_text[:3])

    rt = P.jload(f"{v1_dir}/export/upstream-extract-compatible/roundtrip-check.json")
    R.check("roundtrip_identical", rt["result"] == "IDENTICAL" and rt["field_mismatches"] == 0)

    # ---------- final verdict ----------
    failed = R.failed
    passed = len(R.checks) - len(failed)
    print(f"\n===== VALIDATION ({exam}): {passed}/{len(R.checks)} checks passed =====")
    for c in failed:
        print(f"  FAIL: {c['check']} -> {c['detail']}")

    if write_report:
        report_path = f"{v1_dir}/extraction-report.json"
        report = {}
        try:
            if os.path.isfile(report_path):
                report = P.jload(report_path)
        except Exception:
            report = {}
        rn = cfg.get("report_notes", {})
        gb = cfg.get("generated_by", {})
        report.update(dict(
            schema_version="structured-v1",
            exam_code=exam,
            generated_by={"worker": gb.get("worker", "Z.ai"), "date": gb.get("date", "")},
            validation=dict(total_checks=len(R.checks), passed=passed, failed=len(failed),
                            checks=R.checks),
            counts=dict(
                pdf_pages=n_p, questions=n_q,
                assets=n_a, image_usages=exp.get("usages"),
                roles=dict(roles), answer_kinds=dict(kinds), question_types=dict(types),
                editorial_overlay=dict(overlay),
                text_runs=dict(cover_or_marketing=cover_runs, question_content=q_runs,
                               unassigned=len(unassigned)),
                superseded_vs_active=dict(sup),
            ),
            known_limitations=rn.get("known_limitations", []),
            no_false_completion_statement=rn.get(
                "no_false_completion_statement",
                "Success for Phase 1 is a complete, truthful source-capture layer. It is NOT "
                "verified answers: 0 keys are independently verified or human-approved, and no "
                "publication gate is satisfied or waived."),
        ))
        P.jdump(report, report_path)
        print("wrote extraction-report.json (validation section refreshed; other sections preserved)")

    return 0 if not failed else 1


if __name__ == "__main__":
    cfgp = sys.argv[1]
    wr = "--no-report" not in sys.argv
    sys.exit(main(cfgp, wr))
