#!/usr/bin/env python3
"""Phase 1 extraction: generate structured/v1/source-manifest.json (public toolkit).

Usage: python -m certpassly.phase1.make_source_manifest <config.json>

Everything measurable is measured at run time (PDF bytes/SHA/pages/metadata/
fonts/images, reproduced upstream split hash); only genuinely historical or
declarative strings (readback method, log lines, inventory classifications,
immutability scope) come from config. Config declares the reference artifact
inventory list; no exam-specific file list is hardcoded here.
"""
from __future__ import annotations
import os, sys
from collections import Counter

from . import p1common as P

# NOTE: PyMuPDF (fitz) is imported lazily inside main().


def main(cfg_path):
    import fitz  # lazy: only needed for a real run
    cfg = P.load_config(cfg_path)
    paths = cfg["paths"]
    repo = paths["repo"]
    exam = cfg["exam_code"]
    mc = cfg.get("manifest", {})

    pdf_repo_rel = mc["pdf_repo_path"]
    pdf_local = paths["pdf"]

    doc = fitz.open(pdf_local)
    fonts = set()
    for pno in range(doc.page_count):
        for f in doc.get_page_fonts(pno):
            try:
                fonts.add(f[3])
            except Exception:
                pass
    image_xrefs = 0
    for x in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(x, "Subtype")[1] == "/Image":
                image_xrefs += 1
        except Exception:
            pass
    rotations = {doc[p].rotation for p in range(doc.page_count)}
    annots = sum(len(list(doc[p].annots() or [])) for p in range(doc.page_count))
    links = sum(len(doc[p].get_links()) for p in range(doc.page_count))
    meta = doc.metadata
    m = doc[0].mediabox
    d = doc[0].rect

    # reproduced upstream outputs (measured)
    split_sha = P.sha256_file(f"{paths['upstream_out']}/extracted/split.json")
    vd = P.jload(f"{paths['upstream_out']}/extracted/visual_draft.json", {})
    kinds = Counter(v.get("kind") for v in vd.values() if v.get("kind"))
    n_notes = sum(1 for v in vd.values() if v.get("notes"))
    vd_summary = f"Counter({dict(kinds)}) {n_notes} with notes" if vd else "not run"

    inv = []
    for item in mc.get("inventory", []):
        p = item["path"]
        b = P.git_blob_sha(repo, p)
        if b is None:
            raise SystemExit(f"missing inventory path {p}")
        inv.append(dict(path=p, blob_sha=b, sha256=P.sha256_file(os.path.join(repo, p)),
                        classification=item["classification"], note=item.get("note", "")))

    media_block = None
    if mc.get("archived_media_dir"):
        md = os.path.join(repo, mc["archived_media_dir"])
        media = sorted(os.listdir(md))
        media_block = dict(path=mc["archived_media_dir"], files=len(media),
                           note=mc.get("archived_media_note", ""))

    up = cfg.get("upstream", {})
    gb = cfg.get("generated_by", {})

    def _num(v):
        fv = float(v)
        return int(fv) if fv.is_integer() else round(fv, 2)

    manifest = {
        "schema_version": "structured-v1",
        "exam_code": exam,
        "generated_by": {"worker": gb.get("worker", "Z.ai"),
                         "date": gb.get("date", ""), "environment": gb.get("environment", "")},
        "source_pdf": {
            "repo_path": pdf_repo_rel,
            "storage": "Git LFS (repository .gitattributes routes *.pdf to LFS)",
            "git_blob_sha_of_lfs_pointer": P.git_blob_sha(repo, pdf_repo_rel),
            "bytes": os.path.getsize(pdf_local),
            "sha256": P.sha256_file(pdf_local),
            "verified": {
                "readback_method": mc.get("readback_method",
                                          "local Git LFS pull with authorized private access; SHA-256 "
                                          "recomputed on the actual object bytes, never on the pointer"),
                "page_count": doc.page_count,
                "pdf_version": (meta.get("format") or "").replace("PDF ", "") or None,
                "metadata": {k: meta.get(k) for k in ("title", "author", "creator", "producer",
                                                      "creationDate") if meta.get(k)},
                "encrypted": bool(doc.is_encrypted),
                "annotations": annots, "links": links,
                "image_xobjects": image_xrefs,
                "all_pages_rotate_90": rotations == {90},
                "raw_mediabox": [_num(v) for v in m], "display_box": [_num(v) for v in d],
                "text_ttf_fonts": sorted(fonts),
            }
        },
        "extraction_tools": [
            {"role": "item split, layout detection, marker segmentation",
             "script": "scripts/extract_owner_pdf.py",
             "repo": up.get("repo", "msaqlainhaneef1/certpassly-exam-pipeline"),
             "commit": up.get("commit"),
             "engine": "Poppler pdftohtml -xml",
             "reproduced": {"output": "extracted/split.json",
                            "sha256": split_sha,
                            "identical_to_recorded_pre_overlay_original": bool(mc.get("split_matches_recorded_pre_overlay_original")),
                            "log_line": mc.get("extract_log_line", ""),
                            "matches_historical_stage_log": bool(mc.get("matches_historical_stage_log"))}},
            {"role": "visual draft OCR (kind + candidate keys)",
             "script": "scripts/analyze_visual.py",
             "repo": up.get("repo", "msaqlainhaneef1/certpassly-exam-pipeline"),
             "commit": up.get("commit"),
             "engine": "OpenCV + Tesseract",
             "reproduced": {"output": "extracted/visual_draft.json",
                            "summary": vd_summary,
                            "matches_historical_stage_log": bool(mc.get("matches_historical_stage_log"))}},
            {"role": "structured layer geometry/text/assets builder (this layer)",
             "script": mc.get("builder_script",
                              P.provenance(cfg, "builder_script", P.LEGACY_BUILDER_SCRIPT)),
             "engine": mc.get("engine", "PyMuPDF (pinned local environment)"),
             "upstream_code_modified": False,
             "note": "Independent geometry/text pass cross-checked against the pinned extractor; pinned scripts untouched."}
        ],
        "reference_artifact_inventory": {
            "read_only": True,
            "repo_head_at_inventory": P.git_head(repo),
            "classification_legend": {
                "source-ground-truth": "owner-provided original source or manifest",
                "machine-extracted": "deterministic script output from the source PDF",
                "AI-draft": "AI-assisted draft content; never approved",
                "human-process-record": "process documentation; not approval"
            },
            "artifacts": inv,
            **({"archived_media_dir": media_block} if media_block else {})
        },
        "immutability": {
            "untouched": mc.get("immutability_untouched", []),
            "added": mc.get("immutability_added", [])
        }
    }
    out = mc.get("out") or os.path.join(paths["out_dir"], "source-manifest.json")
    P.jdump(manifest, out)
    print("wrote", out)
    print("inventory entries:", len(inv), "| repo head:", manifest["reference_artifact_inventory"]["repo_head_at_inventory"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
