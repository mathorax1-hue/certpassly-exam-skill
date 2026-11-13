"""Immutable source-image inventory over the PINNED upstream extraction output.

Consumes (never rewrites) the pinned external upstream extractor's output:

  <upstream.out_dir>/extracted/split.json     per-item records with
      question_images / answer_images file lists, pages, answer_raw,
      answer_image_inferred (the upstream heuristic that moved the LAST
      question image into answer_images when the "Correct Answer:" line was
      empty - treated here as UNVERIFIED provenance, never as ground truth)
  <upstream.out_dir>/media/src/<file>         image binaries pdftohtml wrote

and cross-links every image file to the actual PDF image xref (bytes match,
fallback pixel match - same contract as the phase1 pmap) plus its placement
page/rectangle via PyMuPDF. Each file gets one immutable record:

  {file, sha256, bytes, format, width, height, xref, xref_method,
   placements, usages, decode_error, name_safe}

Priority A safety rule (from the operator order): upstream's
answer_image_inferred role is itself heuristic; when it fired, the selection
engine must find independent proof before trusting either member of that
swap.
"""
from __future__ import annotations

import json
import os
import re

from . import imageio
from .errors import OperationalError

SAFE_NAME = re.compile(r"^[A-Za-z0-9._ ()-]+$")


def _require_dir(path: str, what: str) -> str:
    if not os.path.isdir(path):
        raise OperationalError(f"{what} not a directory: {path}")
    return path


def load_upstream_split(out_dir: str) -> dict:
    """Load the pinned upstream split.json (fail-closed if absent)."""
    p = os.path.join(out_dir, "extracted", "split.json")
    try:
        with open(p, encoding="utf-8") as f:
            split = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise OperationalError(
            f"cannot read upstream split output {p} (run the pinned upstream "
            f"extractor first, or set upstream.run_extract=true): {exc}") from exc
    if not isinstance(split, dict):
        raise OperationalError(f"upstream split.json must be an object: {p}")
    return split


def pdf_image_index(pdf_path: str) -> dict:
    """{xref: {"sha256":..., "bytes":..., "width":..., "height":..., "ext":...}} via PyMuPDF."""
    try:
        import fitz  # lazy optional dependency
    except ImportError as exc:  # pragma: no cover - environment guard
        raise OperationalError(
            "media-prep scan requires the pdf extra (PyMuPDF): "
            "python -m pip install -e '.[phase1,visual]'") from exc
    doc = fitz.open(pdf_path)
    index = {}
    for x in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(x, "Subtype")[1] != "/Image":
                continue
            info = doc.extract_image(x)
            data = info["image"]
            index[x] = {
                "sha256": imageio.sha256_bytes(data),
                "bytes": len(data),
                "width": info.get("width"),
                "height": info.get("height"),
                "ext": (info.get("ext") or "").lower(),
            }
        except Exception:
            continue  # non-image or unreadable xref
    return index


def pdf_page_placements(pdf_path: str) -> dict:
    """{xref: [{page (1-based), rect [x0,y0,x1,y1] in unrotated PDF points, page_rotation_deg}]}."""
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover
        raise OperationalError("media-prep scan requires PyMuPDF") from exc
    doc = fitz.open(pdf_path)
    placements = {}
    for pno in range(doc.page_count):
        page = doc[pno]
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            for r in rects:
                placements.setdefault(xref, []).append({
                    "page": pno + 1,
                    "rect": [round(v, 2) for v in (r.x0, r.y0, r.x1, r.y1)],
                    "page_rotation_deg": page.rotation,
                })
    return placements


def map_files_to_xrefs(pdf_path: str, media_src: str) -> dict:
    """{filename: {"xref": int|None, "method": "bytes"|"pixels"|"none"}}.

    Same contract as the phase1 pmap: exact bytes first, exact pixels second.
    A file with no xref match (e.g. a re-encoded or hand-copied media file)
    gets method "none" - the selection engine then treats its provenance as
    unverified (fail-closed), it is never silently accepted.
    """
    try:
        import fitz
        from PIL import Image
        import numpy as np
        import io as _io
    except ImportError as exc:  # pragma: no cover
        raise OperationalError("map_files_to_xrefs requires PyMuPDF+Pillow+numpy") from exc
    _require_dir(media_src, "media src dir")
    doc = fitz.open(pdf_path)
    xref_data = {}
    for x in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(x, "Subtype")[1] != "/Image":
                continue
            info = doc.extract_image(x)
            xref_data[x] = (info["image"], imageio.sha256_bytes(info["image"]))
        except Exception:
            continue
    by_sha = {}
    for x, (_, sha) in xref_data.items():
        by_sha.setdefault(sha, []).append(x)
    mapping = {}
    for fname in sorted(os.listdir(media_src)):
        p = os.path.join(media_src, fname)
        if not os.path.isfile(p):
            continue
        with open(p, "rb") as f:
            data = f.read()
        hit, method = None, None
        cands = by_sha.get(imageio.sha256_bytes(data))
        if cands:
            hit, method = sorted(cands)[0], "bytes"
        if hit is None:
            try:
                arr = np.asarray(Image.open(_io.BytesIO(data)).convert("RGB"))
                for x in sorted(xref_data):
                    raw, _ = xref_data[x]
                    try:
                        sarr = np.asarray(Image.open(_io.BytesIO(raw)).convert("RGB"))
                    except Exception:
                        continue
                    if sarr.shape == arr.shape and int(np.abs(arr.astype(int) - sarr.astype(int)).max()) == 0:
                        hit, method = x, "pixels"
                        break
            except Exception:
                pass
        mapping[fname] = {"xref": hit, "method": method or "none"}
    return mapping


def build_inventory(cfg: dict, *, run_extract=None) -> dict:
    """Build the immutable source-image inventory for one exam config.

    Steps (all read-only except the optional pinned extractor subprocess):
      1. optionally run the PINNED upstream extract_owner_pdf.py (never a
         reimplementation) when cfg.upstream.run_extract and run_extract is
         not overridden False;
      2. verify source PDF identity (fail-closed);
      3. load upstream split.json and media/src;
      4. cross-link every media file to PDF xref + page placements;
      5. emit per-file immutable records + per-question usage roles.
    """
    from .config import verify_source_identity
    from .upstream_runner import ensure_upstream_output

    identity = verify_source_identity(cfg)
    if not identity["identity_ok"]:
        raise OperationalError("source identity check failed: " + "; ".join(identity["problems"]))

    out_dir = cfg["upstream"]["out_dir"]
    ensure_upstream_output(cfg, force=run_extract)

    split = load_upstream_split(out_dir)
    media_src = _require_dir(os.path.join(out_dir, "media", "src"), "upstream media/src")

    file_map = map_files_to_xrefs(cfg["source"]["pdf"], media_src)
    placements = pdf_page_placements(cfg["source"]["pdf"])

    # per-file immutable records
    files = {}
    for fname, m in file_map.items():
        p = os.path.join(media_src, fname)
        xref = m["xref"]
        placements_for_file = placements.get(xref, []) if xref is not None else []
        try:
            img = imageio.load_image(p, fname)
        except OperationalError as exc:
            files[fname] = {
                "file": fname, "sha256": None, "bytes": None,
                "decode_error": str(exc), "xref": xref, "xref_method": m["method"],
                "placements": placements_for_file, "usages": [],
                "name_safe": bool(SAFE_NAME.fullmatch(fname)),
            }
            continue
        files[fname] = {
            "file": fname,
            "sha256": img.sha256,
            "bytes": len(img.data),
            "format": img.format,
            "width": img.width,
            "height": img.height,
            "xref": xref,
            "xref_method": m["method"],
            "placements": placements_for_file,
            "usages": [],
            "decode_error": None,
            "name_safe": bool(SAFE_NAME.fullmatch(fname)),
        }

    # per-question usage roles straight from the upstream split
    questions = {}
    for qid, rec in split.items():
        if not isinstance(rec, dict):
            continue
        usage = []
        for role_key, role in (("question_images", "question_image"),
                               ("answer_images", "answer_image")):
            for fname in rec.get(role_key) or []:
                entry = {
                    "file": fname,
                    "question_id": qid,
                    "role": role,
                    "answer_image_inferred": bool(role == "answer_image" and rec.get("answer_image_inferred")),
                }
                usage.append(entry)
                if fname in files:
                    files[fname]["usages"].append(entry)
        questions[qid] = {
            "question_id": qid,
            "source_number": rec.get("source_number"),
            "pages": rec.get("pages") or [],
            "stem_chars": len(rec.get("stem") or ""),
            "stem_text": rec.get("stem") or "",
            "has_options": bool(rec.get("options")),
            "answer_raw": rec.get("answer_raw") or "",
            "answer_image_inferred": bool(rec.get("answer_image_inferred")),
            "image_only": bool(rec.get("image_only")),
            "usage": usage,
        }

    return {
        "schema_version": "image-inventory-v1",
        "exam_code": cfg["exam_code"],
        "source_pdf_sha256": identity["sha256"],
        "source_pdf_bytes": identity["bytes"],
        "upstream": {"out_dir": out_dir, "repo": cfg["upstream"]["repo"],
                     "commit": cfg["upstream"]["commit"]},
        "files": files,
        "questions": questions,
        "counts": {
            "media_files": len(files),
            "with_xref": sum(1 for f in files.values() if f["xref"] is not None),
            "decode_errors": sum(1 for f in files.values() if f["decode_error"]),
            "questions": len(questions),
            "questions_with_images": sum(1 for q in questions.values() if q["usage"]),
        },
    }
