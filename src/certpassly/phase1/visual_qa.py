#!/usr/bin/env python3
"""Phase 1 extraction: visual QA - render pages, contact sheets, image visibility (public toolkit).

Usage: python -m certpassly.phase1.visual_qa <config.json>

Exit codes (P0-1, director audit 2026-11-13): 0 = all machine visibility
checks passed; 2 = MACHINE VISIBILITY FAILURE (an image placement that is
not visible / unreadable / degenerate, or an image-bearing page that renders
blank). Human semantic review of answer-reference images is a separate,
pending HUMAN task - it is reported as such and never impersonated, and it
never changes the exit code.

Machine visual checks only; does NOT impersonate human review. Produces:
  - qa/page-renders/page-NNNN.jpg (private workspace; NOT committed - derivable)
  - qa/contact-sheet-*.jpg (committed small evidence)
  - qa/visual-qa-report.json (committed; contact-sheet references are
    repository-root-relative via config.paths.repo_relative_out_dir)

Page count, DPI, sheet grid and every path come from config/measurement; no
exam-specific values are hardcoded.
"""
from __future__ import annotations
import os, sys

from . import p1common as P

# NOTE: PyMuPDF/numpy/Pillow are imported lazily inside main() so this module's
# config handling stays importable on stdlib-only environments (public CI).


def main(cfg_path):
    import fitz
    import numpy as np
    from PIL import Image, ImageFilter
    cfg = P.load_config(cfg_path)
    paths = cfg["paths"]
    PDF, V1 = paths["pdf"], paths["out_dir"]
    QA = f"{V1}/qa"
    repo = paths["repo"]
    rel_out = paths.get("repo_relative_out_dir")
    vq = cfg.get("visual_qa", {})
    render_dpi = vq.get("render_dpi", 72)
    grid_cols, grid_rows = vq.get("grid_cols", 5), vq.get("grid_rows", 5)
    thumb_w = vq.get("thumb_width", 260)

    os.makedirs(f"{QA}/page-renders", exist_ok=True)
    doc = fitz.open(PDF)
    n_pages = doc.page_count

    def rel(p):
        if rel_out:
            return f"{rel_out}/qa/{os.path.basename(p)}"
        try:
            r = os.path.relpath(os.path.abspath(p), os.path.abspath(repo))
            return r if not r.startswith("..") else p
        except Exception:
            return p

    au = P.jload(f"{V1}/asset-usage.json")
    usage_by_page = {}
    for u in au["usages"]:
        usage_by_page.setdefault(u["page"], []).append(u)

    page_stats = []
    visibility = []

    runs_per_page = {}
    for pno_ in range(n_pages):
        d = P.jload(f"{V1}/pages/page-{pno_+1:04d}.json")
        runs_per_page[pno_ + 1] = len(d["text_runs"])

    for pno in range(n_pages):
        page = doc[pno]
        pix = page.get_pixmap(dpi=render_dpi)
        out = f"{QA}/page-renders/page-{pno+1:04d}.jpg"
        pix.save(out)
        img = np.asarray(Image.open(out).convert("L"))
        nonwhite = float((img < 245).mean())
        pixel_sparse = nonwhite < 0.005
        truly_blank = pixel_sparse and runs_per_page.get(pno + 1, 0) == 0 and not usage_by_page.get(pno + 1)
        st = dict(page=pno + 1, render=f"qa/page-renders/page-{pno+1:04d}.jpg",
                  pixels=f"{pix.width}x{pix.height}", nonwhite_ratio=round(nonwhite, 4),
                  text_runs=runs_per_page.get(pno + 1, 0),
                  blank=truly_blank,
                  note=("text-sparse page (option labels / short marketing lines); not blank"
                        if pixel_sparse and not truly_blank else ""))
        m = page.rotation_matrix
        scale = render_dpi / 72.0
        for u in usage_by_page.get(pno + 1, []):
            bbox = u.get("bbox_display")
            if not bbox:
                continue
            x0, y0, x1, y1 = [v * scale for v in bbox]
            x0c, y0c = max(0, int(round(x0))), max(0, int(round(y0)))
            x1c, y1c = min(pix.width, int(round(x1))), min(pix.height, int(round(y1)))
            if x1c <= x0c or y1c <= y0c:
                visibility.append(dict(usage_id=u["usage_id"], page=pno + 1, check="placement",
                                       result="degenerate_crop", visible=False))
                continue
            crop_pil = Image.fromarray(img[y0c:y1c, x0c:x1c])
            asset_img = Image.open(f"{V1}/assets/{u['asset']}").convert("L")
            try:
                W = 96
                ch = max(8, int(crop_pil.height * W / crop_pil.width))
                ah = max(8, int(asset_img.height * W / asset_img.width))
                c2 = np.asarray(crop_pil.resize((W, ch)).filter(ImageFilter.GaussianBlur(1.2))).astype(float)
                a2 = np.asarray(asset_img.resize((W, ah)).filter(ImageFilter.GaussianBlur(1.2))).astype(float)
                if c2.shape != a2.shape:
                    a2 = np.asarray(Image.fromarray(a2.astype(np.uint8)).resize((W, ch))).astype(float)
                c = float(np.corrcoef(c2.ravel(), a2.ravel())[0, 1]) if c2.std() > 1 and a2.std() > 1 else 0.0
            except Exception:
                visibility.append(dict(usage_id=u["usage_id"], page=pno + 1, check="placement",
                                       result="asset_unreadable", visible=False))
                continue
            clipped = bool(x0 < 0 or y0 < 0 or x1 > pix.width or y1 > pix.height)
            visibility.append(dict(usage_id=u["usage_id"], page=pno + 1, check="placement_correlation_blurred",
                                   correlation=round(c, 4), clipped_at_page_edge=clipped,
                                   visible=bool(c > 0.6)))
        page_stats.append(st)

    blank_pages = [s["page"] for s in page_stats if s["blank"]]
    text_sparse = [s["page"] for s in page_stats if s.get("note")]
    low_vis = [v for v in visibility if not v.get("visible")]
    corr = [v["correlation"] for v in visibility if "correlation" in v]
    clipped = [v["usage_id"] for v in visibility if v.get("clipped_at_page_edge")]

    thumbs = []
    TW = thumb_w
    for pno in range(n_pages):
        im = Image.open(f"{QA}/page-renders/page-{pno+1:04d}.jpg")
        r = TW / im.width
        thumbs.append(im.resize((TW, max(1, int(im.height * r)))))
    th = max(t.height for t in thumbs)
    cols, rows = grid_cols, grid_rows
    per_sheet = cols * rows
    n_sheets = (len(thumbs) + per_sheet - 1) // per_sheet
    sheets = []
    for s in range(n_sheets):
        sheet = Image.new("RGB", (cols * (TW + 6) + 6, rows * (th + 6) + 6), (40, 40, 40))
        for i, t in enumerate(thumbs[s * per_sheet:(s + 1) * per_sheet]):
            gx, gy = i % cols, i // cols
            sheet.paste(t, (6 + gx * (TW + 6), 6 + gy * (th + 6)))
        p = f"{QA}/contact-sheet-{s+1:02d}-pages-{s*per_sheet+1}-{min((s+1)*per_sheet, n_pages)}.jpg"
        sheet.save(p, quality=70)
        sheets.append(rel(p))
        print("wrote", p, sheet.size, os.path.getsize(p) // 1024, "KB")

    vd = P.jload(f"{paths['upstream_out']}/extracted/visual_draft.json", {})
    ocr_notes = {q: v.get("notes") for q, v in vd.items() if v.get("notes")}
    n_answer_refs = sum(1 for u in au["usages"] if u["role"] == "answer_reference")

    # P0-1 (director audit 2026-11-13): machine visibility failures are FATAL.
    # Failure classes (exit 2): an image placement that is not visible
    # (low/failed crop-vs-asset correlation, unreadable asset, degenerate
    # crop) and an image-bearing page that renders blank. Recorded warnings
    # (never fatal by themselves): clipped-at-page-edge placements (can be
    # source-genuine), text-sparse pages carrying only short text runs, and
    # truly blank pages with no assigned content. Human semantic review of
    # answer-reference images is reported separately and is NEVER a machine
    # pass/fail - it stays pending until a qualified human performs it.
    machine_vis_failures = []
    for v in low_vis:
        machine_vis_failures.append(dict(page=v.get("page"), usage_id=v.get("usage_id"),
                                         check=v.get("check"), result=v.get("result"),
                                         failure_class="image_placement_not_visible"))
    render_blank_with_images = [s["page"] for s in page_stats
                                if s["nonwhite_ratio"] < 0.005 and usage_by_page.get(s["page"])]
    for p in render_blank_with_images:
        machine_vis_failures.append(dict(page=p,
                                         failure_class="page_renders_blank_with_image_usages"))

    report = dict(
        schema_version="structured-v1",
        exam_code=cfg["exam_code"],
        method=(f"Machine visual QA in the private local workspace: every PDF page rendered at "
                f"{render_dpi} DPI; per-page blank detection; per-image-placement crop vs asset "
                f"correlation; contact sheets generated for human review. This is NOT human sign-off."),
        reviewer_type="machine (Z.ai local render + correlation); no human reviewer impersonated",
        page_renders=dict(count=len(page_stats), dpi=render_dpi, blank_pages=blank_pages,
                          text_sparse_pages=text_sparse,
                          min_nonwhite_ratio=min(s["nonwhite_ratio"] for s in page_stats)),
        image_visibility=dict(checks=len(visibility),
                              visible=sum(1 for v in visibility if v.get("visible")),
                              not_visible=[v["usage_id"] for v in low_vis],
                              clipped_at_page_edge=clipped,
                              min_correlation=min(corr) if corr else None,
                              median_correlation=round(float(np.median(corr)), 4) if corr else None),
        machine_visibility=dict(
            failed=bool(machine_vis_failures),
            failure_class="machine_visibility_failure",
            failures=machine_vis_failures,
            exit_code=2 if machine_vis_failures else 0,
            fatal_policy=("P0-1 (director audit 2026-11-13): not-visible image placements and "
                          "image-bearing pages that render blank are machine visibility "
                          "FAILURES (exit 2). Clipped-at-edge placements, text-sparse pages and "
                          "content-free blank pages are recorded warnings only. Human semantic "
                          "review of answer-reference images is a separate pending human task "
                          "and never impersonated by this tool.")),
        ocr_readability_flags=dict(pinned_analyze_visual_notes=ocr_notes,
                                   count_with_notes=len(ocr_notes)),
        contact_sheets=sheets,
        conclusion=(
            (f"MACHINE VISIBILITY FAILURE: {len(machine_vis_failures)} item(s) failed the required "
             f"visibility/placement checks (see machine_visibility.failures); extraction cannot be "
             f"accepted as visually intact until the failures are resolved. ")
            if machine_vis_failures else
            (f"All pages render non-blank and all placed images correlate with their source "
             f"binaries; ")
        ) + (f"machine extraction counts do not prove semantic readability of "
             f"diagrams/checkboxes/answer selections. Human visual review remains required "
             f"for the {n_answer_refs} answer-reference images and disputed items "
             f"(human_review_pending; never impersonated by this machine tool)."),
    )
    P.jdump(report, f"{QA}/visual-qa-report.json")
    print("\nblank pages:", blank_pages, "| text-sparse (not blank):", text_sparse)
    print("clipped at page edge:", clipped)
    print("visibility checks:", len(visibility), "visible:", report["image_visibility"]["visible"],
          "min corr:", report["image_visibility"]["min_correlation"],
          "median:", report["image_visibility"]["median_correlation"])
    print("not visible:", report["image_visibility"]["not_visible"][:10])
    if machine_vis_failures:
        print(f"MACHINE VISIBILITY FAILURE: {len(machine_vis_failures)} item(s) -> exit 2")
        return 2
    # P0-1 (director audit 2026-11-13): this tool used to return 0 even when
    # placements were not visible. Machine visibility failures now exit 2 so
    # run_all stops; pending HUMAN semantic review is reported as such and is
    # deliberately NOT an exit-code condition.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
