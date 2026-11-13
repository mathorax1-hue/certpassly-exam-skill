"""Deterministic, tamper-evident manifest writing (image-manifest-v1).

Canonical form: JSON with sort_keys=True, separators=(",", ":") for hashing
and indent=1 for the written file, ensure_ascii=False. The manifest embeds
``integrity.entries_sha256`` - the SHA-256 of the canonical serialization of
the questions array - so verify-package can detect ANY post-hoc edit of
entries (role flips, SHA swaps, eligibility forgeries) with exit 3.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile

from . import imageio
from .errors import OperationalError


def canonical_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def entries_hash(questions: list) -> str:
    return hashlib.sha256(canonical_bytes(questions)).hexdigest()


def atomic_write(path: str, data: bytes) -> None:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".mp-manifest-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def dump_json(path: str, obj) -> None:
    atomic_write(path, json.dumps(obj, indent=1, sort_keys=False,
                                  ensure_ascii=False).encode("utf-8") + b"\n")


def write_clean_candidate(clean_dir: str, question_id: str, source_img, candidate: dict) -> dict:
    """Write ONE verified clean candidate into clean_dir (atomic).

    Priority A/C: preserve native pixels - byte-identical copy for lossless
    sources; decoded pixels re-saved as PNG for lossy JPEG sources (no
    additional JPEG generation, never "recompressed repeatedly"). Priority B:
    the rendered PNG bytes (passed via candidate["_render_bytes"], never
    serialized into the manifest).
    """
    os.makedirs(clean_dir, exist_ok=True)
    if candidate.get("pixel_source") == "pdf_region_render":
        data = candidate.get("_render_bytes")
        if data is None:
            raise OperationalError("priority-B candidate missing render bytes")
        name = f"{question_id}.png"
    elif candidate.get("lossless_source"):
        data = source_img.data
        ext = "png" if (source_img.format == "png") else source_img.format
        name = f"{question_id}.{ext}"
    else:
        # lossy source: re-encode decoded pixels to lossless PNG exactly once
        import io as _io
        buf = _io.BytesIO()
        source_img.flattened_rgb().save(buf, format="PNG", optimize=False)
        data = buf.getvalue()
        name = f"{question_id}.png"
    path = os.path.join(clean_dir, name)
    atomic_write(path, data)
    return {
        "path": name,
        "sha256": imageio.sha256_bytes(data),
        "bytes": len(data),
        "method": candidate["method"],
        "source_sha256": candidate["source_sha256"],
    }


def write_reviewer_only(private_dir: str, fname: str, data: bytes) -> dict:
    """Copy a marked/reviewer-only image into the ISOLATED private directory.

    This directory must live completely outside any import/package/web root;
    verify-package rejects any package that reaches into it and any learner
    archive whose member SHA equals one of these reviewer-only SHAs.
    """
    os.makedirs(private_dir, exist_ok=True)
    path = os.path.join(private_dir, os.path.basename(fname))
    atomic_write(path, data)
    return {"path": os.path.basename(fname), "sha256": imageio.sha256_bytes(data),
            "bytes": len(data)}


def build_manifest(cfg: dict, identity: dict, readiness: dict, *, upstream_facts: dict,
                   written: dict, reviewer_written: dict) -> dict:
    """Assemble the image-manifest-v1 document (deterministic, sorted qids)."""
    questions = []
    for qid in sorted(readiness):
        rec = readiness[qid]
        entry = {
            "schema_version": "image-readiness-v1",
            "source_pdf_sha256": identity["sha256"],
            "question_id": qid,
            "requires_image": rec["requires_image"],
            "role_decisions": rec["role_decisions"],
            "clean_candidate": None,
            "is_learner_eligible": rec["is_learner_eligible"],
            "review_status": rec["review_status"],
            "issues": rec["issues"],
            "blocked_reasons": rec["blocked_reasons"],
        }
        cand = rec.get("clean_candidate")
        if cand and qid in written:
            entry["clean_candidate"] = {
                "file": written[qid]["path"],
                "sha256": written[qid]["sha256"],
                "bytes": written[qid]["bytes"],
                "method": cand["method"],
                "pixel_source": cand.get("pixel_source"),
                "width": cand["width"],
                "height": cand["height"],
                "source_file": cand["source_file"],
                "source_sha256": cand["source_sha256"],
                "quality": cand.get("quality"),
            }
        elif cand:
            entry["clean_candidate"] = {
                "method": cand["method"],
                "note": "candidate identified but NOT written (blocked by quality gate)",
                "width": cand["width"],
                "height": cand["height"],
                "source_file": cand["source_file"],
                "source_sha256": cand["source_sha256"],
                "quality": cand.get("quality"),
            }
        questions.append(entry)

    eligible = [e for e in questions if e["is_learner_eligible"] and e["clean_candidate"]]
    blocked = [e for e in questions if not e["is_learner_eligible"] and e["requires_image"]]
    manifest = {
        "schema_version": "image-manifest-v1",
        "exam_code": cfg["exam_code"],
        "source_pdf_sha256": identity["sha256"],
        "source_pdf_bytes": identity["bytes"],
        "generated_by": {
            "toolkit": "certpassly-media-prep",
            "version": "1.0.0",
            "upstream_repo": cfg["upstream"]["repo"],
            "upstream_commit": cfg["upstream"]["commit"],
            "upstream_run": upstream_facts,
        },
        "questions": questions,
        "reviewer_only_assets": sorted(reviewer_written.values(), key=lambda r: r["sha256"]),
        "counts": {
            "questions_total": len(questions),
            "questions_requiring_image": sum(1 for e in questions if e["requires_image"]),
            "learner_eligible": len(eligible),
            "blocked": len(blocked),
            "blocked_question_ids": [e["question_id"] for e in blocked],
            "clean_files_written": len(written),
        },
        "integrity": {},
    }
    manifest["integrity"] = {
        "entries_sha256": entries_hash(questions),
        "algorithm": "sha256(canonical_json(sort_keys)(questions))",
    }
    return manifest
