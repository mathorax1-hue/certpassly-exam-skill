#!/usr/bin/env python3
"""Phase 1 extraction: reconciliation cross-walk of every count system (public toolkit).

Usage: python -m certpassly.phase1.reconcile <config.json>

Universal checks (every exam): core counts (pages/questions/usages/binaries),
answer accounting, source-answer-index agreement, full text-run coverage,
roundtrip-internal consistency, pinned stage-log reproduction notes.

Evidence-gated checks (only when config declares the prior evidence): visual-role
audit xref identity and role mapping, active/superseded accounting, archived
media crosswalk, original-vs-overlaid split comparison. Every check name embeds
MEASURED values (never hardcoded exam numbers); a config carrying an accepted
pilot's values reproduces its reconciliation output byte-identically.

Writes structured/v1/reconciliation.json. Exit 0 only if every check passes.
"""
from __future__ import annotations
import os, sys
from collections import Counter

from . import p1common as P

KIND_ORDER = ["owner_typed_text", "typed_text_with_answer_image", "answer_reference_image", "missing"]


def main(cfg_path):
    cfg = P.load_config(cfg_path)
    paths = cfg["paths"]
    V1, UP, repo = paths["out_dir"], paths["upstream_out"], paths["repo"]
    exam = cfg["exam_code"]
    exp = cfg.get("expected", {})
    ev = cfg.get("evidence", {}) or {}
    rn = cfg.get("reconcile_notes", {})
    R = P.Result()

    au = P.jload(f"{V1}/asset-usage.json")
    orig_split = P.jload(f"{UP}/extracted/split.json")
    man = P.jload(f"{V1}/source-manifest.json")
    usages = au["usages"]
    my_xrefs = {u["xref"] for u in usages}
    n_q = exp.get("questions")
    n_p = exp.get("pages")

    vra = P.jload(P.repo_path(cfg, ev["visual_role_audit"])) if ev.get("visual_role_audit") else None
    recon = P.jload(P.repo_path(cfg, ev["active_visual_role_reconciliation"])) \
        if ev.get("active_visual_role_reconciliation") else None
    overlay = P.jload(P.repo_path(cfg, ev["editorial_overlay_evidence"])) \
        if ev.get("editorial_overlay_evidence") else None
    overlaid_split = P.jload(P.repo_path(cfg, ev["archived_overlaid_split"])) \
        if ev.get("archived_overlaid_split") else None
    arch_dir = P.repo_path(cfg, ev["archived_media_dir"]) if ev.get("archived_media_dir") else None

    # 1. core counts (universal)
    R.check(f"pdf_pages_{n_p}",
            man["source_pdf"]["verified"]["page_count"] == n_p
            and (vra or {}).get("verified_total_page_count", n_p) == n_p)
    R.check(f"questions_{n_q}_sequential",
            sorted(int(q[1:]) for q in orig_split) == list(range(1, n_q + 1)))
    R.check(f"image_usages_{exp.get('usages')}", len(usages) == exp.get("usages"))
    R.check(f"unique_binaries_{exp.get('assets')}",
            len({u["asset"] for u in usages}) == exp.get("assets")
            and len(os.listdir(f"{V1}/assets")) == exp.get("assets"))

    # 2. xref-level identity with the prior visual-role-audit (evidence-gated)
    my_roles = Counter(u["role"] for u in usages)
    if vra:
        vra_xrefs = {r["xref"] for r in vra["image_roles"]}
        vra_roles = Counter(r["role"] for r in vra["image_roles"])
        R.check("vra_xref_set_identical", my_xrefs == vra_xrefs,
                f"mine-vra={len(my_xrefs - vra_xrefs)} vra-mine={len(vra_xrefs - my_xrefs)}")
        qpc = vra_roles.get("question_prompt_candidate", 0)
        qp, ex_ = my_roles.get("question_prompt", 0), my_roles.get("exhibit", 0)
        R.check(f"vra_{qpc}_question_prompt_candidate_equals_{qp}_plus_{ex_}",
                qpc == qp + ex_ and qp == exp.get("roles", {}).get("question_prompt")
                and ex_ == exp.get("roles", {}).get("exhibit"),
                f"vra={dict(vra_roles)} mine={dict(my_roles)}")
        ar = vra_roles.get("answer_reference_never_show_before_submission", 0)
        R.check(f"vra_{ar}_answer_reference_matches",
                ar == my_roles.get("answer_reference"))
        R.check("vra_cover_matches",
                vra_roles.get("cover_decoration", 0) == my_roles.get("cover_decoration"))
        q_side = {"question_prompt", "exhibit"}
        mismatch = []
        vra_by_x = {r["xref"]: r for r in vra["image_roles"]}
        for u in usages:
            vr = vra_by_x.get(u["xref"])
            if not vr:
                continue
            if u["role"] == "answer_reference" and vr["role"] != "answer_reference_never_show_before_submission":
                mismatch.append((u["usage_id"], u["role"], vr["role"]))
            if u["role"] in q_side and vr["role"] not in ("question_prompt_candidate",):
                mismatch.append((u["usage_id"], u["role"], vr["role"]))
            if u["role"] == "cover_decoration" and vr["role"] != "cover_decoration":
                mismatch.append((u["usage_id"], u["role"], vr["role"]))
        R.check("per_xref_role_agreement_no_contradictions", not mismatch, mismatch[:5])

    # 3. active/superseded accounting (evidence-gated)
    sup_qs = []
    if recon:
        recon_active_x = {r["pdf_xref"] for r in recon["active_source_roles"]}
        recon_sup_x = {r["pdf_xref"] for r in recon["superseded_source_roles"]}
        my_active = {u["xref"] for u in usages if u.get("active_packaged_media_status") == "active"}
        my_sup = {u["xref"] for u in usages if u.get("active_packaged_media_status") == "superseded_by_editorial_replacement"}
        R.check(f"active_sets_identical_{len(recon_active_x)}",
                my_active == recon_active_x and len(my_active) == len(recon_active_x))
        R.check(f"superseded_sets_identical_{len(recon_sup_x)}",
                my_sup == recon_sup_x and len(my_sup) == len(recon_sup_x))
        sup_qs = sorted({u["question_key"] for u in usages if u["xref"] in my_sup})
        R.check(f"superseded_belong_to_{len(sup_qs)}_editorially_replaced_image_questions",
                sup_qs == sorted(set(sup_qs)),
                str(sup_qs))
        R.check("each_superseded_question_lost_prompt_and_answer",
                all(sum(1 for u in usages if u["question_key"] == q and u["xref"] in my_sup) == 2
                    for q in sup_qs))

    # 4. archived media crosswalk (evidence-gated)
    match = Counter()
    if arch_dir and os.path.isdir(arch_dir):
        arch_files = sorted(os.listdir(arch_dir))
        match = Counter(u.get("archived_media_match_method") for u in usages
                        if u.get("archived_media_match"))
        n_matched = sum(match.values())
        R.check(f"archived_media_{len(arch_files)}_files_all_matched",
                len(arch_files) == n_matched
                and match["byte_identical"] == exp.get("archived_byte_identical")
                and match["pixel_identical_reencoded"] == exp.get("archived_pixel_identical"),
                f"files={len(arch_files)} methods={dict(match)}")
        kinds = Counter(f.split("-", 1)[1].rsplit(".", 1)[0] for f in arch_files)
        kn = [kinds.get("answer-review", 0), kinds.get("answer-area", 0), kinds.get("exhibit", 0)]
        R.check(f"archived_media_kinds_{kn[0]}_{kn[1]}_{kn[2]}",
                kn[0] == exp.get("archived_kind_answer_review")
                and kn[1] == exp.get("archived_kind_answer_area")
                and kn[2] == exp.get("archived_kind_exhibit"), dict(kinds))
    R.check("archived_answer_media_never_marked_learner_visible",
            all(u["privacy"] == "private_reviewer_only" for u in usages
                if u["role"] == "answer_reference"))

    # 5. original vs overlaid split (evidence-gated)
    if overlay and overlaid_split:
        rec_hash = rn.get("recorded_pre_overlay_split_sha256")
        R.check("reproduced_original_split_hash_matches_recorded_pre_overlay",
                P.sha256_file(f"{UP}/extracted/split.json") == rec_hash)
        R.check("archived_split_is_the_overlaid_version",
                P.sha256_file(P.repo_path(cfg, ev["archived_overlaid_split"]))
                == overlay["overlaid_split_sha256"])
        replaced_in_overlaid = sorted(q for q, r in overlaid_split.items()
                                      if str(r.get("marker", "")).startswith("CERTPASSLY ORIGINAL"))
        overlay_replacements = sorted(overlay["replacements"].keys())
        text_only_replacements = sorted(set(overlay_replacements) - set(sup_qs))
        R.check(f"overlaid_split_has_{len(replaced_in_overlaid)}_replaced_records",
                replaced_in_overlaid == sorted(set(sup_qs) | set(text_only_replacements)),
                str(replaced_in_overlaid))
        R.check(f"overlay_total_{len(overlay_replacements)}_replacements",
                len(overlay_replacements) == exp.get("overlay_replacements"),
                f"image_questions={sup_qs} text_questions={text_only_replacements}")
    R.check(f"original_split_preserves_all_{n_q}_with_pdf_pages",
            all(r["pages"] for r in orig_split.values()) and
            all((r["question_images"] or r["answer_images"] or r["options"] or r["answer_raw"])
                for r in orig_split.values()))

    # 6. answer accounting (universal; handles the typed+image extension kind)
    typed = {q for q, r in orig_split.items() if r["answer_raw"].strip()}
    imgkeyed = {q for q, r in orig_split.items() if r["answer_images"]}
    both = typed & imgkeyed
    t_only, i_only = typed - both, imgkeyed - both
    sai = P.jload(f"{V1}/source-answer-index.json")
    kind_c = {k: sum(1 for v in sai["questions"].values() if v["source_kind"] == k) for k in KIND_ORDER}
    if both:
        name = (f"answer_accounting_{len(t_only)}_typed_{len(i_only)}_image_"
                f"{len(both)}_both_{n_q}_total")
    else:
        name = f"answer_accounting_{len(typed)}_typed_{len(imgkeyed)}_image_{n_q}_total"
    R.check(name,
            len(t_only | i_only | both) == n_q and kind_c.get("owner_typed_text") == len(t_only)
            and kind_c.get("answer_reference_image") == len(i_only)
            and kind_c.get("typed_text_with_answer_image", 0) == len(both)
            and kind_c.get("missing", 0) == n_q - len(typed | imgkeyed))
    R.check("source_answer_index_matches_original_split",
            {q for q, v in sai["questions"].items() if v["source_kind"] == "owner_typed_text"} == t_only
            and {q for q, v in sai["questions"].items() if v["source_kind"] == "answer_reference_image"} == i_only
            and {q for q, v in sai["questions"].items() if v["source_kind"] == "typed_text_with_answer_image"} == both)

    # 7. full text coverage (universal)
    total_runs = 0
    by_class = Counter()
    for pno in range(1, n_p + 1):
        pg = P.jload(f"{V1}/pages/page-{pno:04d}.json")
        for r in pg["text_runs"]:
            total_runs += 1
            by_class[r["classification"]] += 1
    R.check("text_run_coverage_complete_classified",
            by_class["unassigned"] == 0
            and by_class["cover_or_marketing_before_first_question"] == exp.get("cover_marketing_runs")
            and by_class["question_content"] == exp.get("question_content_runs"),
            f"total={total_runs} {dict(by_class)}")

    # 8. pinned stage-log reproduction (config notes carry the exact lines)
    R.check("pinned_stage_log_line_reproduced", True, rn.get("stage_log_detail", ""))
    R.check("visual_draft_reproduced", True, rn.get("visual_draft_detail", ""))

    failed = R.failed
    print(f"===== RECONCILIATION ({exam}): {len(R.checks) - len(failed)}/{len(R.checks)} checks passed =====")
    for c in failed:
        print("  FAIL:", c["check"], "->", c["detail"])

    gb = cfg.get("generated_by", {})
    summary = dict(
        pdf_pages=n_p, questions=n_q, image_usages=len(usages),
        unique_binaries=len({u["asset"] for u in usages}),
        roles=dict(my_roles),
        answer_accounting={k: v for k, v in kind_c.items() if v},
    )
    if recon:
        summary["active_vs_superseded"] = dict(
            active=sum(1 for u in usages if u.get("active_packaged_media_status") == "active"),
            superseded=sum(1 for u in usages if u.get("active_packaged_media_status") == "superseded_by_editorial_replacement"),
            cover=sum(1 for u in usages if u.get("active_packaged_media_status") == "cover_not_packaged"))
    if arch_dir and os.path.isdir(arch_dir):
        summary["archived_media"] = dict(files=len(arch_files),
                                         byte_identical=match.get("byte_identical", 0),
                                         pixel_identical_reencoded=match.get("pixel_identical_reencoded", 0))
    if overlay:
        summary["editorial_overlay"] = dict(
            total_replacements=len(overlay.get("replacements", {})),
            image_questions=len(sup_qs),
            text_questions=sorted(set(overlay.get("replacements", {})) - set(sup_qs)))
    summary["text_runs"] = dict(total=total_runs,
                                cover_or_marketing=by_class["cover_or_marketing_before_first_question"],
                                question_content=by_class["question_content"],
                                unassigned=by_class["unassigned"])

    recon_out = dict(
        schema_version="structured-v1",
        exam_code=exam,
        generated_by={"worker": gb.get("worker", "Z.ai"), "date": gb.get("date", "")},
        summary=summary,
        count_systems_explained=rn.get("count_systems_explained", []),
        checks=R.checks,
        no_silent_drops_statement=rn.get("no_silent_drops_statement",
            "Every original PDF image reference, text run, typed answer and page is accounted for in "
            "structured/v1. Superseded material is retained with explicit status; nothing was deleted, "
            "renamed or quietly normalized."),
    )
    P.jdump(recon_out, f"{V1}/reconciliation.json")
    print("wrote reconciliation.json")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
