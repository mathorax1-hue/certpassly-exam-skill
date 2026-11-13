"""The strict Priority A/B/C/D clean-image selection engine (non-AI, deterministic).

For every question in the upstream split, decide - from PROVENANCE, never
guessing - whether a provably-unmarked learner image exists:

  Priority A  direct clean source: an upstream question image whose (1) PDF
              xref provenance is verified (bytes/pixels), (2) assignment was
              NOT produced by the upstream answer_image_inferred heuristic
              swap (or the swap is independently confirmed by a verified
              pair), and (3) machine mark detection finds no pen-like
              selection marks. Native pixels are preserved (lossless copy;
              lossy JPEG pixels re-saved to PNG without re-compression).

  Priority B  annotation-free render, SELF-VERIFIED: only when the page
              carries real PDF annotations overlapping the marked image's
              placement AND the annotation-free render actually differs from
              the with-annotations render AND mark detection on the RENDER
              finds no marks. A second variant covers exhibits that are
              DRAWN as PDF vector content (no raster at all): the page is
              rendered at high DPI and must likewise be provably unmarked.
              When the marks are flattened INTO the raster, the render still
              shows them and Priority B is honestly not applicable.

  Priority C  paired clean member: the same exhibit appears twice (typically
              question + answer copy); conservative ORB registration proves
              the pair and exactly one member is unmarked -> the ALREADY
              CLEAN member becomes the learner candidate (with the role
              correction recorded). Advisory diff only; nothing is erased.

  Priority D  no provable clean source -> BLOCK with a stable reason code.
              No inpainting, no upscaling, no OCR redraw, no blind erasure -
              ever.

Quality runs on the chosen candidate (native source pixels; a resize can
never flip a FAIL to a PASS). Every decision is recorded in the manifest.
"""
from __future__ import annotations

import os
import re

from . import imageio
from .errors import OperationalError
from . import marking as marking_mod
from . import pair_and_align
from . import quality as quality_mod
from . import renderer as renderer_mod
from . import roles
from .roles import (METHOD_NONE, METHOD_PRIORITY_A, METHOD_PRIORITY_B,
                    METHOD_PRIORITY_C, R_CLEAN_ASSET_MISSING,
                    R_MARKED_ONLY_REVIEW_REQUIRED, R_SOURCE_IMAGE_AMBIGUOUS,
                    R_SOURCE_IMAGE_CORRUPT, R_SOURCE_IMAGE_LOW_RESOLUTION,
                    R_SOURCE_SHA_MISMATCH, REVIEW_BLOCKED,
                    REVIEW_CLEAN_LOW_RESOLUTION, REVIEW_CLEAN_READY)

EXHIBIT_REF_RX = re.compile(
    r"exhibit|graphic|diagram|following (image|figure|table)|shown below", re.I)


class _Ctx:
    """Loaded-once per-question image cache for the selection pass."""

    def __init__(self, cfg, inventory):
        self.cfg = cfg
        self.inventory = inventory
        self.media_src = os.path.join(cfg["upstream"]["out_dir"], "media", "src")
        self._cache = {}

    def img(self, fname):
        if fname not in self._cache:
            self._cache[fname] = imageio.load_image(os.path.join(self.media_src, fname), fname)
        return self._cache[fname]

    def file_record(self, fname):
        rec = self.inventory["files"].get(fname)
        if rec is None:
            raise OperationalError(f"file {fname} not in inventory")
        return rec


def _provenance_issues(rec) -> list[dict]:
    issues = []
    if rec.get("decode_error"):
        issues.append({"reason": R_SOURCE_IMAGE_CORRUPT, "detail": rec["decode_error"]})
    if rec.get("xref") is None:
        issues.append({"reason": R_SOURCE_IMAGE_AMBIGUOUS,
                       "detail": "no PDF xref provenance (bytes/pixels match failed)"})
    return issues


def _quality_gate(cfg, img, qrec) -> dict:
    profile_name = quality_mod.choose_profile(img, qrec)
    profile = cfg["quality_profiles"][profile_name]
    return quality_mod.assess(
        img, profile=profile,
        css_width=cfg["display"]["default_css_width"],
        density_goal=cfg["display"]["pixel_density_goal"])


def _candidate_from_source(ctx, fname, img, method, extra_note=None) -> dict:
    """Build the candidate descriptor for an already-clean source image."""
    rec = ctx.file_record(fname)
    return {
        "source_file": fname,
        "source_sha256": img.sha256,
        "source_bytes": len(img.data),
        "xref": rec.get("xref"),
        "method": method,
        "pixel_source": "native_embedded_raster",
        "width": img.width,
        "height": img.height,
        "lossless_source": img.format in ("png", "gif", "bmp", "tiff"),
        "note": extra_note,
    }


def _try_priority_b_render(ctx, fname, rec, page_no, rect, issues) -> dict | None:
    """Priority B for a marked raster whose page carries real annotations.

    Self-verification (all must hold, else Priority B is honestly not
    applicable and None is returned):
      1. the annotation-free render DIFFERS from the with-annotations render
         (the annotations actually contributed visible pixels);
      2. mark detection on the annotation-free render finds NO pen marks
         (flattened raster marks would survive the render and B cannot help);
      3. the render is decodable and non-empty.
    """
    dpi = 300
    clean_out = renderer_mod.render_crop(ctx.cfg["source"]["pdf"], page_no, rect,
                                         dpi=dpi, annots=False)
    with_out = renderer_mod.render_crop(ctx.cfg["source"]["pdf"], page_no, rect,
                                        dpi=dpi, annots=True)
    png = clean_out.pop("png_bytes")
    with_png = with_out.pop("png_bytes")
    if png == with_png:
        issues.append({"reason": "PRIORITY_B_NOT_APPLICABLE",
                       "detail": f"page {page_no}: annotations did not change the render"})
        return None
    rendered = imageio.SourceImage(fname + ".render.png", png)
    mk = marking_mod.detect_marks(rendered.flattened_rgb())
    if marking_mod.looks_marked(mk):
        issues.append({"reason": "PRIORITY_B_NOT_APPLICABLE",
                       "detail": "annotation-free render still shows marks (flattened "
                                 "raster marks are NOT cleanable by rendering)"})
        return None
    facts = None
    if rec.get("xref") is not None:
        facts = renderer_mod.renderable_embedded_raster(ctx.cfg["source"]["pdf"], rec["xref"])
    cand_sha = imageio.sha256_bytes(png)
    issues.append({"reason": "PRIORITY_B_RENDER",
                   "detail": f"page {page_no}: real annotations excluded; render self-verified unmarked"})
    return {
        "source_file": fname,
        "source_sha256": ctx.img(fname).sha256,
        "source_bytes": len(ctx.img(fname).data),
        "xref": rec.get("xref"),
        "method": METHOD_PRIORITY_B,
        "pixel_source": "pdf_region_render",
        "width": clean_out["width"],
        "height": clean_out["height"],
        "lossless_source": True,
        "render": {**clean_out, "render_sha256": cand_sha, "render_bytes": len(png)},
        "embedded_raster_ceiling": facts,
        "note": "rendered from the original PDF page region with real annotations "
                "excluded; the annotation-free render was machine-verified unmarked",
    }


def _try_priority_b_vector_page(ctx, qid, page_no, issues) -> dict | None:
    """Priority B (vector variant): the exhibit is DRAWN in the PDF, not raster.

    A page whose vector drawings cover a substantial area (>=20%) is rendered
    whole at high DPI (annots=False). Verification is annotation-diff based:
    when real annotations exist on the page, the annotation-free render must
    actually DIFFER from the with-annotations render (the marks were real
    annotations and excluding them changed pixels). Vector page content is
    original exam content by the pinned upstream contract; vector-DRAWN pen
    marks cannot be distinguished from table borders and are recorded as a
    documented limitation (VECTOR_PEN_MARK_UNDETECTABLE), never as clean.
    """
    try:
        import fitz
    except ImportError:  # pragma: no cover
        return None
    doc = fitz.open(ctx.cfg["source"]["pdf"])
    if not (1 <= page_no <= doc.page_count):
        return None
    page = doc[page_no - 1]
    try:
        drawings = page.get_drawings()
    except Exception:
        return None
    try:
        page_area = abs(page.rect)
    except Exception:
        return None
    drawn_area = 0.0
    for d in drawings:
        try:
            r = d.get("rect")
            if r is None:
                continue
            drawn_area += abs(fitz.Rect(r))
        except Exception:
            continue
    if page_area <= 0 or drawn_area < 0.20 * page_area:
        return None
    clip = tuple(page.rect)
    clean_out = renderer_mod.render_crop(ctx.cfg["source"]["pdf"], page_no, clip,
                                         dpi=300, annots=False)
    png = clean_out.pop("png_bytes")
    # The render must be provably unmarked: run the same mark detector on the
    # rendered pixels. Legitimate LIGHT-gray vector chrome (row lines, table
    # borders) does not trip it; dark or colored pen-like shapes in vector
    # content (owner-drawn circles, dark-bordered boxes) DO - and because a
    # vector-drawn mark cannot be distinguished from vector content, the
    # question is conservatively BLOCKED for human review instead of shipped.
    rendered = imageio.SourceImage(f"{qid}.vector-page.png", png)
    mk = marking_mod.detect_marks(rendered.flattened_rgb())
    if marking_mod.looks_marked(mk):
        issues.append({"reason": "PRIORITY_B_NOT_APPLICABLE",
                       "detail": f"page {page_no}: vector render shows {mk['detected_mark_boxes']} "
                                 f"pen-like shape(s); vector-drawn marks cannot be proved absent "
                                 f"(VECTOR_PEN_MARK_UNDETECTABLE) - blocked for review"})
        return None
    if clean_out["annotations_present"]:
        with_out = renderer_mod.render_crop(ctx.cfg["source"]["pdf"], page_no, clip,
                                            dpi=300, annots=True)
        with_png = with_out.pop("png_bytes")
        if png == with_png:
            issues.append({"reason": "PRIORITY_B_NOT_APPLICABLE",
                           "detail": f"page {page_no}: annotations did not change the render"})
            return None
        issues.append({"reason": "PRIORITY_B_VECTOR_RENDER",
                       "detail": f"page {page_no}: vector exhibit rendered at 300 DPI "
                                 f"(drawings cover {drawn_area / page_area:.0%} of the page); "
                                 f"{len(clean_out['annotations_in_clip'])} real annotations "
                                 f"excluded (render differs from with-annotations render); "
                                 f"render mark-check clean ({mk['detected_mark_boxes']} shapes)"})
    else:
        issues.append({"reason": "PRIORITY_B_VECTOR_RENDER",
                       "detail": f"page {page_no}: vector exhibit rendered at 300 DPI "
                                 f"(drawings cover {drawn_area / page_area:.0%} of the page); "
                                 f"page has no annotations; render mark-check clean "
                                 f"({mk['detected_mark_boxes']} shapes)"})
    return {
        "source_file": f"(pdf-page-{page_no}-vector)",
        "source_sha256": imageio.sha256_bytes(png),
        "source_bytes": len(png),
        "xref": None,
        "method": METHOD_PRIORITY_B,
        "pixel_source": "pdf_region_render",
        "width": clean_out["width"],
        "height": clean_out["height"],
        "lossless_source": True,
        "render": {**clean_out, "render_sha256": imageio.sha256_bytes(png),
                   "render_bytes": len(png),
                   "vector_pen_mark_undetectable": True},
        "embedded_raster_ceiling": None,
        "note": "question exhibit is drawn as PDF vector content; rendered from the "
                "original page at high DPI (true added pixels, not upscaling); "
                "vector-drawn pen marks are a documented out-of-scope limitation",
    }


def _load_render_bytes(ctx, candidate) -> bytes:
    cache = getattr(ctx, "_render_cache", None)
    if cache is None:
        cache = ctx._render_cache = {}
    key = (candidate["source_file"], candidate["method"], candidate.get("render", {}).get("dpi"))
    if key not in cache:
        out = renderer_mod.render_crop(
            ctx.cfg["source"]["pdf"], candidate["render"]["page"],
            candidate["render"]["clip"], dpi=candidate["render"]["dpi"], annots=False)
        cache[key] = out["png_bytes"]
    return cache[key]


def _quality_gate_rendered(ctx, candidate) -> dict:
    """Quality of a Priority-B rendered PNG (measured on the rendered pixels)."""
    png = _load_render_bytes(ctx, candidate)
    img = imageio.SourceImage(candidate["source_file"] + ".render.png", png)
    return _quality_gate(ctx.cfg, img, {"profile_hint": "screenshot"})


def _finalize_roles(decisions, marks_by_file, candidate, inferred_swap, pair_clean_members):
    """Assign the final verified_role per the documented precedence.

    1. decode/xref failure                          -> unknown_unverified
    2. the chosen learner candidate's source        -> question_clean_candidate
    3. unmarked verified question image (no swap)   -> question_clean_candidate
    4. clean member of a verified pair              -> question_clean_candidate
    5. detected marks                               -> answer_marked_reviewer_only
    6. assigned answer_image without pair override  -> answer_marked_reviewer_only
    7. anything else                                -> unknown_unverified
    """
    cand_file = candidate.get("source_file") if candidate else None
    for d in decisions:
        rec_issues = d.get("issues") or []
        broken = any(i["reason"] in (R_SOURCE_IMAGE_CORRUPT, R_SOURCE_IMAGE_AMBIGUOUS)
                     for i in rec_issues)
        fname = d["source_file"]
        mk = marks_by_file.get(fname) or {}
        marked = marking_mod.looks_marked(mk)
        if broken:
            d["verified_role"] = roles.UNKNOWN_UNVERIFIED
        elif cand_file == fname:
            d["verified_role"] = roles.QUESTION_CLEAN_CANDIDATE
        elif not marked and d["assigned_role"] == "question_image" and not inferred_swap:
            d["verified_role"] = roles.QUESTION_CLEAN_CANDIDATE
        elif fname in pair_clean_members:
            d["verified_role"] = roles.QUESTION_CLEAN_CANDIDATE
        elif marked:
            d["verified_role"] = roles.ANSWER_MARKED_REVIEWER_ONLY
        elif d["assigned_role"] == "answer_image":
            d["verified_role"] = roles.ANSWER_MARKED_REVIEWER_ONLY
        else:
            d["verified_role"] = roles.UNKNOWN_UNVERIFIED


def _decide_one_question(ctx, qid, qrec) -> dict:
    usages = qrec["usage"]
    decisions = []
    blocked_reasons = []
    issues = []

    q_files = [u for u in usages if u["role"] == "question_image"]
    inferred_swap = qrec.get("answer_image_inferred")

    # No images at all: nothing to prepare UNLESS the stem references an
    # exhibit and the page carries a substantial vector drawing (the exhibit
    # is DRAWN in the PDF, not embedded as a raster - the pinned upstream
    # extractor only records raster images, so a vector exhibit shows up as
    # "no images" here). Handled by the vector Priority-B variant below.
    exhibit_ref = bool(qrec.get("image_only")) or bool(EXHIBIT_REF_RX.search(
        qrec.get("stem_text") or ""))
    if not usages and not exhibit_ref:
        return {
            "question_id": qid,
            "requires_image": False,
            "role_decisions": decisions,
            "clean_candidate": None,
            "is_learner_eligible": True,
            "review_status": REVIEW_CLEAN_READY,
            "issues": [],
            "blocked_reasons": [],
            "note": "no images attached to this question in the upstream split",
        }

    requires_image = True  # any image usage (or exhibit reference) means visual content

    # --- mark detection on every member ------------------------------------
    marks_by_file = {}
    for u in usages:
        fname = u["file"]
        rec = ctx.file_record(fname)
        prov_issues = _provenance_issues(rec)
        if rec.get("decode_error"):
            decisions.append(roles.decision_record(
                source_file=fname, source_sha256=rec.get("sha256"),
                source_bytes=rec.get("bytes"),
                page=(rec.get("placements") or [{}])[0].get("page"),
                xref=rec.get("xref"), assigned_role=u["role"],
                verified_role=roles.UNKNOWN_UNVERIFIED, method=METHOD_NONE,
                marking={"detected_mark_boxes": 0, "error": "undecodable",
                         "note": "image could not be decoded; mark detection not run"},
                issues=prov_issues,
                answer_image_inferred=u["answer_image_inferred"]))
            continue
        img = ctx.img(fname)
        mk = marking_mod.detect_marks(img.flattened_rgb())
        marks_by_file[fname] = mk
        decisions.append(roles.decision_record(
            source_file=fname, source_sha256=img.sha256, source_bytes=len(img.data),
            page=(rec.get("placements") or [{}])[0].get("page"), xref=rec.get("xref"),
            assigned_role=u["role"],
            verified_role=roles.UNKNOWN_UNVERIFIED,  # finalized below
            method=METHOD_NONE, marking=mk, native_width=img.width,
            native_height=img.height, issues=prov_issues,
            answer_image_inferred=u["answer_image_inferred"]))

    # --- find the best learner candidate (strict priority order) ------------
    candidate = None
    pair_clean_members = set()

    def is_verified_clean(fname, u):
        rec = ctx.file_record(fname)
        if rec.get("decode_error") or rec.get("xref") is None:
            return False
        mk = marks_by_file.get(fname)
        if mk is None or marking_mod.looks_marked(mk):
            return False
        # upstream heuristic-swap roles are NOT trusted for direct use
        if inferred_swap:
            return False
        if u["role"] != "question_image":
            return False
        return True

    # Priority A
    for u in q_files:
        fname = u["file"]
        if fname in marks_by_file and is_verified_clean(fname, u):
            candidate = _candidate_from_source(ctx, fname, ctx.img(fname), METHOD_PRIORITY_A,
                                               extra_note="unmarked, xref-verified question image")
            break

    # Priority C (pair): needed when (a) every question image is marked or
    # provenance-broken, or (b) the upstream heuristic swapped roles.
    if candidate is None:
        pair_evidence = []
        members = [(u["file"], u["role"]) for u in usages
                   if not ctx.file_record(u["file"]).get("decode_error")]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                fa, _ra = members[i]
                fb, _rb = members[j]
                if fa == fb:
                    continue
                cmp = pair_and_align.compare_pair(
                    ctx.img(fa), ctx.img(fb), marks_by_file.get(fa, {}), marks_by_file.get(fb, {}))
                if cmp["registered"]:
                    pair_evidence.append({
                        "a": fa, "b": fb,
                        "verdict": cmp["verdict"], "clean_member": cmp["clean_member"],
                        "registration": {k: cmp["registration"].get(k) for k in
                                         ("inliers", "matches", "inlier_ratio", "scale", "reason")},
                    })
                    if cmp["clean_member"]:
                        clean_fname = fa if cmp["clean_member"] == "a" else fb
                        marked_fname = fb if cmp["clean_member"] == "a" else fa
                        crec = ctx.file_record(clean_fname)
                        if crec.get("xref") is not None:
                            candidate = _candidate_from_source(
                                ctx, clean_fname, ctx.img(clean_fname), METHOD_PRIORITY_C,
                                extra_note=f"verified clean member of registered pair "
                                           f"({marked_fname} is the marked copy); role correction recorded")
                            pair_clean_members.add(clean_fname)
                            issues.append({"reason": "PAIR_ROLE_CORRECTION",
                                           "detail": f"{marked_fname} reclassified to reviewer-only; "
                                                     f"{clean_fname} is the clean exhibit"})
        if pair_evidence:
            issues.append({"reason": "PAIR_EVIDENCE", "detail": pair_evidence})

    # Priority B (annotation variant): only when a real annotation overlaps
    # the marked image placement AND the render self-verifies unmarked.
    if candidate is None:
        for u in q_files:
            fname = u["file"]
            rec = ctx.file_record(fname)
            if rec.get("decode_error"):
                continue
            for pl in rec.get("placements") or []:
                page_no = pl["page"]
                try:
                    rep = renderer_mod.page_annotation_report(ctx.cfg["source"]["pdf"], page_no)
                except OperationalError:
                    continue
                if not rep["annotations_present"]:
                    continue
                overlap = [a for a in rep["annotations"]
                           if not (a["rect"][2] < pl["rect"][0] or a["rect"][0] > pl["rect"][2]
                                   or a["rect"][3] < pl["rect"][1] or a["rect"][1] > pl["rect"][3])]
                if not overlap:
                    continue
                if not marking_mod.looks_marked(marks_by_file.get(fname, {})):
                    continue  # nothing to separate
                candidate = _try_priority_b_render(ctx, fname, rec, page_no, pl["rect"], issues)
                if candidate:
                    break
            if candidate:
                break

    # Priority B (vector variant): the exhibit is DRAWN (vector) rather than
    # a raster; render the page at high DPI and self-verify.
    if candidate is None and exhibit_ref:
        for page_no in qrec.get("pages") or []:
            candidate = _try_priority_b_vector_page(ctx, qid, page_no, issues)
            if candidate:
                break

    # --- outcome ------------------------------------------------------------
    if candidate is None:
        q_decodable = [u["file"] for u in q_files if not ctx.file_record(u["file"]).get("decode_error")]
        q_clean_unverified = [f for f in q_decodable
                              if f in marks_by_file and not marking_mod.looks_marked(marks_by_file[f])]
        if q_clean_unverified and inferred_swap:
            reason = R_SOURCE_IMAGE_AMBIGUOUS
            detail = ("upstream answer_image_inferred heuristic reassigned roles and no "
                      "independent pair verification succeeded; manual review required")
        elif q_clean_unverified:
            bad = [f for f in q_clean_unverified if ctx.file_record(f).get("xref") is None]
            if bad:
                reason = R_SOURCE_SHA_MISMATCH
                detail = "clean-looking question image lacks PDF xref provenance (bytes/pixels)"
            else:
                reason = R_SOURCE_IMAGE_AMBIGUOUS
                detail = "no priority path could certify a learner image"
        elif q_decodable:
            reason = R_MARKED_ONLY_REVIEW_REQUIRED
            detail = "every question image carries detected selection marks; " \
                     "no verified clean pair member exists"
        elif q_files:
            reason = R_SOURCE_IMAGE_CORRUPT
            detail = "question image files are present but undecodable"
        else:
            reason = R_CLEAN_ASSET_MISSING
            detail = "question has only answer-area images (or only an unrenderable " \
                     "exhibit reference); no learner exhibit source"
        blocked_reasons.append({"reason": reason, "detail": detail})
        _finalize_roles(decisions, marks_by_file, None, inferred_swap, pair_clean_members)
        return {
            "question_id": qid,
            "requires_image": requires_image,
            "role_decisions": decisions,
            "clean_candidate": None,
            "is_learner_eligible": False,
            "review_status": REVIEW_BLOCKED,
            "issues": issues,
            "blocked_reasons": blocked_reasons,
        }

    # --- quality gate on the chosen candidate -------------------------------
    if candidate["method"] == METHOD_PRIORITY_B:
        qual = _quality_gate_rendered(ctx, candidate)
    else:
        img = ctx.img(candidate["source_file"])
        qual = _quality_gate(ctx.cfg, img, qrec)
    candidate["quality"] = qual

    hard_fail = qual["issues"]
    if hard_fail:
        blocked_reasons.extend(hard_fail)
        _finalize_roles(decisions, marks_by_file, candidate, inferred_swap, pair_clean_members)
        return {
            "question_id": qid,
            "requires_image": requires_image,
            "role_decisions": decisions,
            "clean_candidate": candidate,
            "is_learner_eligible": False,
            "review_status": REVIEW_CLEAN_LOW_RESOLUTION,
            "issues": issues + qual["advisory"],
            "blocked_reasons": blocked_reasons,
        }

    # eligible
    _finalize_roles(decisions, marks_by_file, candidate, inferred_swap, pair_clean_members)
    return {
        "question_id": qid,
        "requires_image": requires_image,
        "role_decisions": decisions,
        "clean_candidate": candidate,
        "is_learner_eligible": True,
        "review_status": REVIEW_CLEAN_READY,
        "issues": issues + qual["advisory"],
        "blocked_reasons": [],
    }


def run_selection(cfg: dict, inventory: dict) -> dict:
    """Run the engine over every question; returns readiness records keyed by qid."""
    ctx = _Ctx(cfg, inventory)
    ready = {}
    for qid in sorted(inventory["questions"]):
        qrec = inventory["questions"][qid]
        ready[qid] = _decide_one_question(ctx, qid, qrec)
    return ready
