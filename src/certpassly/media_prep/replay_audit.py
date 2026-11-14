"""B6 reproducible private source/image replay and contact-sheet evidence.

Only reads the owner's private pinned PDF, the real upstream extract and the
private media manifest. Writes a PRIVATE REVIEW-ONLY audit and one gallery
per image-bearing question. Never returns release authority, never uploads,
never starts research or changes a source, a clean candidate or a key.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath

from .config import load_config, verify_source_identity
from .source_inventory import build_inventory
from .manifest import atomic_write
from .privacy_gate import load_manifest
from .errors import OperationalError


def _sha_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()


def _private_target(cfg, folder: str) -> Path:
    root=Path(cfg["output"]["private_dir"]).resolve()
    if not root.is_absolute() or not folder or "/" in folder or "\\" in folder or folder in (".",".."):
        raise OperationalError("gallery folder must be one simple private name")
    out=(root/folder).resolve()
    if out.parent!=root:
        raise OperationalError("gallery destination escaped configured private directory")
    # No public-website or upstream tree may receive a private gallery.
    for forbidden in (cfg["output"]["clean_dir"],cfg["upstream"]["out_dir"]):
        candidate=Path(forbidden).resolve()
        if out==candidate or candidate in out.parents:
            raise OperationalError("private gallery overlaps clean/upstream directory")
    out.mkdir(parents=True,exist_ok=True)
    return out


def _safe_clean_file(root: Path, filename: str) -> Path:
    if (not isinstance(filename,str) or not filename or
        "\" in filename or "/" in filename or ":" in filename or
        filename.startswith(".") or PurePosixPath(filename).suffix.lower() not in
        (".png",".jpg",".jpeg",".webp")):
        raise OperationalError("clean candidate must be one safe local filename")
    path=(root/filename).resolve()
    if path.parent!=root.resolve():
        raise OperationalError("clean file path escape")
    return path


def _gallery(pdf_path, qid, pages, question_assets, answer_assets,
             clean_path, media_root, out_file):
    """Private contact sheet: PDF page + ALL original question/answer sources + clean."""
    import fitz
    from PIL import Image, ImageDraw, ImageOps
    previews=[]
    if pages:
        try:
            with fitz.open(pdf_path) as doc:
                page_no=pages[0]
                if isinstance(page_no,int) and 1<=page_no<=len(doc):
                    pix=doc[page_no-1].get_pixmap(matrix=fitz.Matrix(1,1),alpha=False)
                    im=Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                    previews.append((f"Original PDF page {page_no}",im))
        except Exception:
            pass
    for role, filenames in (("QUESTION SOURCE",question_assets),("ANSWER REFERENCE",answer_assets)):
        for filename in filenames:
            try:
                with Image.open(media_root/filename) as im:
                    previews.append((f"{role}: {filename}",im.convert("RGB").copy()))
            except Exception:
                previews.append((f"{role}: {filename} (unreadable)",None))
    if clean_path:
        try:
            with Image.open(clean_path) as im:
                previews.append(("LEARNER CANDIDATE - REVIEW, NOT APPROVED",im.convert("RGB").copy()))
        except Exception:
            previews.append(("LEARNER CANDIDATE (unreadable)",None))
    width=1100; panel_w=520; panel_h=360; header=58
    columns=2; rows=(len(previews)+1)//2
    out=Image.new("RGB",(width,header+max(1,rows)*panel_h),"#f5f5f5")
    draw=ImageDraw.Draw(out)
    draw.text((12,12),f"PRIVATE REVIEW ONLY | {qid} | NOT APPROVED | do not upload",fill="#901212")
    for i,(label,preview) in enumerate(previews):
        col=i%columns; row=i//columns
        x=12+col*546; y=header+row*panel_h
        draw.rectangle((x,y,x+panel_w,y+panel_h-5),outline="#555555",width=2)
        draw.text((x+8,y+8),label[:65],fill="#111111")
        if preview is not None:
            display=ImageOps.contain(preview,(panel_w-16,panel_h-44))
            out.paste(display,(x+(panel_w-display.width)//2,y+36))
    out.save(str(out_file),format="PNG",optimize=False)


def run_private_media_replay(config_path: str, *,
                             expected_source_assets: int,
                             expected_image_questions: int,
                             gallery_folder="builder-replay") -> dict:
    """Compute evidence against the exact current PRIVATE PDF/workspace.

    Expected counters must come from the owner's independent private handover,
    not the manifest being evaluated. The gallery and JSON report remain in
    output.private_dir; their existence never constitutes human approval.
    """
    if not (isinstance(expected_source_assets,int) and expected_source_assets>0 and
            isinstance(expected_image_questions,int) and expected_image_questions>0):
        raise OperationalError("independent expected asset/question counts required")
    cfg=load_config(config_path)
    identity=verify_source_identity(cfg)
    if not identity["identity_ok"]:
        raise OperationalError("original source PDF identity mismatch: "+", ".join(identity["problems"]))
    out=_private_target(cfg,gallery_folder)
    inventory=build_inventory(cfg,run_extract=False)
    stored_path=Path(cfg["output"]["inventory"])
    if not stored_path.is_file():
        raise OperationalError("persisted private image inventory required for independent comparison")
    stored=json.loads(stored_path.read_text(encoding="utf-8"))
    manifest=load_manifest(cfg["output"]["manifest"],require_package_integrity=True)
    if any(obj.get("source_pdf_sha256")!=identity["sha256"]
           for obj in (inventory,stored,manifest)):
        raise OperationalError("source identity differs between original PDF, inventory and manifest")
    files=inventory["files"]
    source_qids={qid for qid,q in inventory["questions"].items() if q["usage"]}
    manifest_q={q["question_id"]:q for q in manifest["questions"]}
    errors=[]; cases=[]
    def issue(qid,reason):
        errors.append({"question_id":qid,"reason":reason})
    if len(files)!=expected_source_assets:
        issue("*","SOURCE_ASSET_COUNT_MISMATCH")
    if len(source_qids)!=expected_image_questions:
        issue("*","IMAGE_QUESTION_COUNT_MISMATCH")
    if len(manifest_q)!=len(inventory["questions"]):
        issue("*","MANIFEST_QUESTION_COUNT_MISMATCH")
    if set(stored.get("files",{}))!=set(files):
        issue("*","ORIGINAL_ASSET_INVENTORY_SET_MISMATCH")
    media_root=Path(cfg["upstream"]["out_dir"])/"media"/"src"
    clean_root=Path(cfg["output"]["clean_dir"])
    all_image_qids=sorted(source_qids|{qid for q,qrec in manifest_q.items()
                                      if qrec.get("requires_image")})
    seen_original=set()
    for qid in all_image_qids:
        q=inventory["questions"].get(qid) or {}
        usage=q.get("usage") or []
        question_assets=[u["file"] for u in usage if u.get("role")=="question_image"]
        answer_assets=[u["file"] for u in usage if u.get("role")=="answer_image"]
        case_issues=[]
        for fn in question_assets+answer_assets:
            seen_original.add(fn)
            f=files.get(fn); prev=(stored.get("files") or {}).get(fn)
            if not f or not prev or not f.get("sha256") or f["sha256"]!=prev.get("sha256"):
                case_issues.append(f"ORIGINAL_SHA_OR_STORED_INVENTORY_MISMATCH:{fn}")
            if not f or f.get("xref") is None:
                case_issues.append(f"ORIGINAL_XREF_UNVERIFIED:{fn}")
        manifest_entry=manifest_q.get(qid)
        clean_path=None
        if not manifest_entry:
            case_issues.append("MANIFEST_ENTRY_MISSING")
        else:
            candidate=manifest_entry.get("clean_candidate")
            if manifest_entry.get("is_learner_eligible"):
                if not isinstance(candidate,dict) or not candidate.get("file"):
                    case_issues.append("ELIGIBLE_CLEAN_BINARY_MISSING")
                else:
                    try:
                        clean_path=_safe_clean_file(clean_root,candidate["file"])
                        if not clean_path.is_file():
                            case_issues.append("CLEAN_FILE_MISSING")
                        elif _sha_file(clean_path)!=candidate.get("sha256"):
                            case_issues.append("CLEAN_SHA_MISMATCH")
                        else:
                            from .imageio import load_image
                            from .marking import detect_marks,looks_marked
                            img=load_image(str(clean_path),clean_path.name)
                            if looks_marked(detect_marks(img.flattened_rgb())):
                                case_issues.append("CLEAN_CONTAINS_POSSIBLE_SELECTION_MARK")
                        if candidate.get("pixel_source")=="pdf_region_render":
                            from .exhibit_crop import verify_render_clip
                            r=candidate.get("render") or {}
                            if not all(k in r for k in ("page","clip","source_number")):
                                case_issues.append("CROP_SOURCE_GEOMETRY_MISSING")
                            else:
                                proof=verify_render_clip(cfg["source"]["pdf"],
                                                         r["page"],r["clip"],r["source_number"])
                                if proof.get("status")!="CROP_OK":
                                    case_issues.append("CROP_UNVERIFIED:"+str(proof.get("status")))
                        elif candidate.get("source_file") in files:
                            original=files[candidate["source_file"]]
                            if original.get("sha256")!=candidate.get("source_sha256"):
                                case_issues.append("CLEAN_SOURCE_SHA_MISMATCH")
                        else:
                            case_issues.append("CLEAN_SOURCE_FILE_NOT_IN_ORIGINAL_INVENTORY")
                    except Exception as exc:
                        case_issues.append("CANDIDATE_RECHECK_ERROR:"+type(exc).__name__)
            elif candidate and candidate.get("file"):
                case_issues.append("BLOCKED_QUESTION_HAS_SHIPPABLE_CLEAN_FILE")
        if manifest_entry and not manifest_entry.get("is_learner_eligible"):
            case_issues.append("QUESTION_REQUIRES_PRIVATE_VISUAL_REVIEW")
        pages=q.get("pages") or []
        gallery_file=out/f"{qid}.png"
        try:
            _gallery(cfg["source"]["pdf"],qid,pages,question_assets,answer_assets,
                     clean_path,media_root,gallery_file)
        except Exception as exc:
            case_issues.append("PRIVATE_GALLERY_RENDER_FAILED:"+type(exc).__name__)
        for reason in case_issues:
            issue(qid,reason)
        cases.append({"question_id":qid,
                      "source_pages":pages,
                      "question_source_assets":question_assets,
                      "answer_reference_assets":answer_assets,
                      "is_learner_eligible":bool(manifest_entry and manifest_entry.get("is_learner_eligible")),
                      "review_status":"PENDING_INDEPENDENT_ZAI_AND_HUMAN",
                      "gallery":gallery_file.name if gallery_file.is_file() else None,
                      "machine_issues":case_issues})
    for fname in sorted(set(files)-seen_original):
        issue("*","ORPHAN_OR_UNREFERENCED_SOURCE_ASSET:"+fname)
    report={"schema_version":"private-media-replay-v1",
            "exam_code":cfg["exam_code"],"original_pdf_sha256":identity["sha256"],
            "original_pdf_bytes":identity["bytes"],
            "upstream_commit":cfg["upstream"]["commit"],
            "expected_source_assets":expected_source_assets,
            "observed_source_assets":len(files),
            "expected_image_questions":expected_image_questions,
            "observed_image_questions":len(source_qids),
            "gallery_count":sum(bool(x["gallery"]) for x in cases),
            "cases":cases,"issues":errors,
            "status":"BLOCKED" if errors else "MACHINE_REPLAY_COMPLETE_HUMAN_PENDING",
            "independent_verifier_status":"PENDING_ZAI_REVIEW",
            "site_ui_status":"UNTESTED",
            "human_approval_status":"NOT_APPROVED",
            "ready_exams_promotion_allowed":False,
            "publication_allowed":False}
    atomic_write(str(out/"private-replay-report.json"),
                 (json.dumps(report,indent=2,sort_keys=True)+"\n").encode("utf-8"))
    return report
