"""Deterministic, tamper-evident manifest writing (image-manifest-v1).

Canonical form: JSON with sort_keys=True, separators=(",", ":") for hashing
and indent=1 for the written file, ensure_ascii=False.

Integrity model (2026-11-14 P0 correction - honest trust boundaries):

  ``integrity.entries_sha256``       LEGACY partial digest over the questions
                                     array only. Kept for continuity; it is
                                     recomputable by anyone and is NOT the
                                     trust anchor.
  ``integrity.package_integrity_sha256``  Digest over ALL security-critical
                                     fields (exam identity, pinned source,
                                     generated_by, questions, reviewer_only_
                                     assets, counts) - detects partial edits
                                     AND edits outside the questions array.
                                     Still self-declared: an attacker who
                                     regenerates the whole manifest can
                                     recompute it.
  ``integrity.receipt_sha256_hmac``  OPTIONAL HMAC-SHA256 receipt over the
                                     package digest, keyed by a secret held
                                     OUTSIDE the package (environment variable
                                     named by privacy.manifest_key_env; never
                                     a key in public code). When
                                     privacy.require_receipt is true,
                                     verify-package refuses any manifest
                                     without a valid receipt - this is the
                                     independent tamper-evidence layer.
  ``privacy.source_receipt``         Optional independent binding: the exam's
                                     pinned source manifest (e.g. the private
                                     repository's exams/<code>/manifest.json)
                                     must contain the manifest's source PDF
                                     sha256/bytes, tying the package to a
                                     file the operator pinned separately.

  On top of the hashes, verify-package CONTENT-RE-VERIFIES every allowlisted
  member against the pinned source PDF (render clips re-checked for answer/
  marker text; raster members re-matched to embedded PDF images and re-run
  through mark detection), so a fully regenerated manifest wrapped around a
  leaky or marked image is still refused. No self-signed checksum is ever
  presented as adversarial tamper-evidence.
"""
from __future__ import annotations

import hashlib
import hmac
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


# Security-critical manifest payload: everything the privacy gate relies on.
# The integrity block itself is deliberately excluded (it covers the payload).
PACKAGE_PAYLOAD_KEYS = ("schema_version", "exam_code", "source_pdf_sha256",
                        "source_pdf_bytes", "generated_by", "questions",
                        "reviewer_only_assets", "counts")


def package_payload(manifest: dict) -> dict:
    return {k: manifest.get(k) for k in PACKAGE_PAYLOAD_KEYS}


def package_integrity_hash(manifest: dict) -> str:
    """SHA-256 of the canonical serialization of ALL security-critical fields."""
    return hashlib.sha256(canonical_bytes(package_payload(manifest))).hexdigest()


def receipt_hmac(key: bytes, package_digest: str) -> str:
    """HMAC-SHA256 receipt over the package digest (key stays outside the package)."""
    return hmac.new(key, package_digest.encode("utf-8"),
                    hashlib.sha256).hexdigest()


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
                   written: dict, reviewer_written: dict, receipt_key: bytes = None,
                   receipt_key_id: str = None) -> dict:
    """Assemble the image-manifest-v1 document (deterministic, sorted qids).

    ``receipt_key``: optional HMAC secret from OUTSIDE the package (the CLI
    reads it from the environment variable named by privacy.manifest_key_env).
    When provided, an HMAC receipt over the package digest is embedded so
    verify-package can enforce independent (non-self-declared) integrity.
    """
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
            # P0 correction: record the exact render geometry so the privacy
            # gate can RE-VERIFY the crop against the pinned source PDF
            # (no marker / answer text may intersect it) instead of trusting
            # the manifest SHA alone
            r = cand.get("render") or {}
            if cand.get("pixel_source") == "pdf_region_render" and r.get("page") is not None:
                entry["clean_candidate"]["render"] = {
                    "page": r.get("page"),
                    "clip": r.get("clip"),
                    "clip_unrotated": r.get("clip_unrotated"),
                    "dpi": r.get("dpi"),
                    "page_rotation_deg": r.get("page_rotation_deg"),
                    "source_number": r.get("source_number"),
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
    package_digest = package_integrity_hash(manifest)
    integrity = {
        "entries_sha256": entries_hash(questions),
        "algorithm_entries": "sha256(canonical_json(sort_keys)(questions)) - legacy partial digest",
        "package_integrity_sha256": package_digest,
        "algorithm": ("sha256(canonical_json(sort_keys)("
                      + ",".join(PACKAGE_PAYLOAD_KEYS) + "))"),
    }
    if receipt_key:
        integrity["receipt_sha256_hmac"] = receipt_hmac(receipt_key, package_digest)
        integrity["receipt_key_id"] = receipt_key_id or "external-env"
        integrity["receipt_algorithm"] = "hmac-sha256(package_integrity_sha256)"
    manifest["integrity"] = integrity
    return manifest
