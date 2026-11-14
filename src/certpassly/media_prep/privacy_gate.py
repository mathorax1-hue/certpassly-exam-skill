"""HARD privacy gate: allowlist-based learner package verification (exit 3 on refusal).

Architecture (per the operator order):
  - learner archives are built from an EXPLICIT ALLOWLIST of verified
    ``question_clean_candidate`` (question_id -> written file SHA) taken from
    the tamper-evident manifest. Anything not on the list is refused, not
    "filtered-after-copying";
  - marked / reviewer-only binaries stay in an isolated private directory
    OUTSIDE any import/package/web root; the gate additionally rejects ANY
    package member whose bytes SHA-match a known reviewer-only asset (catches
    renamed .png, re-embedded copies, nested archives);
  - re-encoded/edited marked images (changed bytes) are caught by
    PROVENANCE: the allowlist is only ever issued from a manifest entry that
    itself records the verified source SHA + method. A perceptual hash can
    raise alerts but never mints eligibility;
  - every image REFERENCE in learner-visible text (questions.json, import
    CSVs incl. question_media_assets.csv / media_assets.csv, simulator
    settings, HTML/CSS/JS, response_schema payloads) must resolve to an
    allowlisted member; external URLs are refused unless explicitly allowed;
  - path traversal, absolute paths, symlink members, case-variant duplicates,
    extension rewrites, nested ZIPs, duplicate asset ids and unknown SHAs are
    all hard failures with exact reasons. No leak = pass.

2026-11-14 P0 CORRECTION (director audit - real AB-730 q074 leaked
``Correct Answer:`` lines through an approved whole-page render):

  1. SCORING FLAGS FAIL THE GATE. ``verify_package()`` now returns
     ``passed=False`` whenever scoring-key flags are present, and
     ``enforce()`` raises on them too - a DIRECT library caller checking
     ``report["passed"]`` can no longer accept a key-bearing payload that
     the CLI would have refused (exit 3).
  2. MANIFEST TRUST IS LAYERED, NOT SELF-SIGNED. ``load_manifest`` verifies
     ``integrity.package_integrity_sha256`` over ALL security-critical
     fields (questions, reviewer_only_assets, counts, exam identity, pins) -
     not just the recomputable legacy ``entries_sha256`` over questions.
     With ``privacy.require_receipt`` an HMAC-SHA256 receipt keyed by a
     secret OUTSIDE the package (env var, never in public code) must also
     validate. With ``privacy.source_receipt`` the manifest's source PDF
     identity must match the independently pinned exam manifest. The
     self-declared digests alone are never presented as adversarial
     tamper-evidence.
  3. ALLOWLISTED CONTENT IS RE-VERIFIED AGAINST THE PINNED SOURCE, not
     against the manifest text alone: every rendered member's recorded crop
     is re-checked on the original PDF for marker/answer/explanation text
     (whole-page renders are categorically refused), and every raster member
     is re-matched to an embedded PDF image and re-run through mark
     detection. A fully regenerated manifest wrapped around a leaky or
     marked image is therefore still refused.

The gate is deliberately paranoid: it FAILS CLOSED (exit 3) and never
"repairs" a bad package. It cannot prove the live site's server behavior; if
the package ships pre-submit scoring keys (correct_option_ids etc.) it flags
SITE_SCORING_ARCHITECTURE_REVIEW_REQUIRED, fails and refuses to certify.
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile

from . import imageio
from .errors import PrivacyViolationError

SCORING_KEY_FIELDS = (
    "correct_option_ids", "answer_key", "correct_answers", "correct_option_id",
    "answer_letters", "correct_rows",
)
SCORING_FLAG = "SITE_SCORING_ARCHITECTURE_REVIEW_REQUIRED"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".ico"}
IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"II*\x00", b"MM\x00*")
NESTED_ZIPS = (".zip",)

_URL_RX = re.compile(r"""(?:https?://|data:|//)[^\s"'<>)]+""", re.I)
# Image references in learner-visible text: quoted paths (JSON/HTML/JS) AND
# bare tokens (CSV fields like "qv-001,clean/q002.png,exhibit").
_LOCAL_REF_RX = re.compile(
    r"""["'(]([^"')]+\.(?:png|jpe?g|gif|webp|bmp|tiff?|ico))["')]"""
    r"""|(?:^|[\s,;:])([\w.\/ -]+?\.(?:png|jpe?g|gif|webp|bmp|tiff?|ico))(?=$|[\s,;"'])""",
    re.I | re.M)


def _is_image_name(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in IMAGE_EXTS


def _is_image_bytes(data: bytes) -> bool:
    return any(data.startswith(m) for m in IMAGE_MAGIC)


def load_manifest(path: str, *, require_package_integrity: bool = True) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise PrivacyViolationError(f"cannot read manifest {path}: {exc}")
    if m.get("schema_version") != "image-manifest-v1":
        raise PrivacyViolationError(f"manifest {path} is not image-manifest-v1")
    # integrity: legacy partial digest over the questions array
    from .manifest import entries_hash, package_integrity_hash, package_payload
    claimed = (m.get("integrity") or {}).get("entries_sha256")
    actual = entries_hash(m.get("questions") or [])
    if not claimed or claimed != actual:
        raise PrivacyViolationError(
            "manifest integrity check FAILED: entries_sha256 does not match the "
            "questions array (tampered manifest?)")
    # P0 correction: full package integrity over ALL security-critical fields
    integ = m.get("integrity") or {}
    claimed_pkg = integ.get("package_integrity_sha256")
    if require_package_integrity and not claimed_pkg:
        raise PrivacyViolationError(
            "manifest integrity check FAILED: package_integrity_sha256 is "
            "missing (legacy manifest; regenerate with the current toolkit)")
    if claimed_pkg:
        actual_pkg = package_integrity_hash(m)
        if claimed_pkg != actual_pkg:
            raise PrivacyViolationError(
                "manifest integrity check FAILED: package_integrity_sha256 "
                "does not match the security-critical manifest fields "
                "(questions, reviewer_only_assets, counts, exam identity or "
                "pins were edited?)")
    return m


def _check_receipt(manifest: dict, *, key_env: str) -> list:
    """HMAC receipt verification (key read from OUTSIDE the package)."""
    problems = []
    integ = manifest.get("integrity") or {}
    receipt = integ.get("receipt_sha256_hmac")
    key = os.environ.get(key_env, "")
    if not receipt:
        problems.append({"member": "manifest", "reason": "RECEIPT_MISSING",
                         "detail": f"require_receipt=true but integrity."
                                   f"receipt_sha256_hmac is absent (key env: {key_env})"})
        return problems
    if not key:
        problems.append({"member": "manifest", "reason": "RECEIPT_KEY_UNAVAILABLE",
                         "detail": f"environment variable {key_env} is not set; "
                                   f"the receipt cannot be verified"})
        return problems
    from .manifest import package_integrity_hash, receipt_hmac
    expected = receipt_hmac(key.encode("utf-8"),
                            package_integrity_hash(manifest))
    if expected != receipt:
        problems.append({"member": "manifest", "reason": "RECEIPT_HMAC_MISMATCH",
                         "detail": "HMAC receipt does not validate against the "
                                   "package integrity digest (tampered manifest?)"})
    return problems


def _check_source_receipt(manifest: dict, source_receipt_path: str) -> list:
    """Bind the manifest's source PDF identity to an independently pinned receipt."""
    problems = []
    try:
        with open(source_receipt_path, encoding="utf-8") as f:
            receipt = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return [{"member": "manifest", "reason": "SOURCE_RECEIPT_UNREADABLE",
                 "detail": f"cannot read pinned source receipt {source_receipt_path}: {exc}"}]
    entries = []
    for f in receipt.get("pdf_files") or []:
        if isinstance(f, dict):
            entries.append((f.get("sha256"), f.get("bytes"), f.get("name")))
    pinned = {(sha, size) for sha, size, _n in entries if sha}
    m_sha = manifest.get("source_pdf_sha256")
    m_bytes = manifest.get("source_pdf_bytes")
    if (m_sha, m_bytes) not in pinned:
        problems.append({
            "member": "manifest", "reason": "SOURCE_RECEIPT_MISMATCH",
            "detail": f"manifest source {m_sha} ({m_bytes} bytes) is not the "
                      f"independently pinned source in {source_receipt_path}"})
    return problems


def build_allowlist(manifest: dict) -> dict:
    """{member basename: {"sha256":..., "question_id":..., "method":...,
    "pixel_source":..., "render": {...}|None}} from verified learner-eligible
    manifest entries ONLY."""
    allow = {}
    for entry in manifest.get("questions") or []:
        cand = entry.get("clean_candidate") or {}
        if not entry.get("is_learner_eligible") or not cand.get("file"):
            continue
        allow[cand["file"].rsplit("/", 1)[-1]] = {
            "sha256": cand["sha256"],
            "question_id": entry["question_id"],
            "method": cand.get("method"),
            "pixel_source": cand.get("pixel_source"),
            "render": cand.get("render"),
        }
    return allow


def reviewer_only_shas(manifest: dict) -> set[str]:
    return {r["sha256"] for r in manifest.get("reviewer_only_assets") or []}


def _embedded_image_index(pdf_path: str) -> tuple:
    """({sha256: [xref, ...]}, {sha256: raw_bytes}) for every embedded raster."""
    try:
        import fitz
    except ImportError:  # pragma: no cover - gate degrades loudly, not silently
        return {}, {}
    doc = fitz.open(pdf_path)
    index, raw_by_sha = {}, {}
    for x in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(x, "Subtype")[1] != "/Image":
                continue
            raw = doc.extract_image(x)["image"]
            sha = imageio.sha256_bytes(raw)
            index.setdefault(sha, []).append(x)
            raw_by_sha.setdefault(sha, raw)
        except Exception:
            continue
    return index, raw_by_sha


def _pixels_equal(a_bytes: bytes, b_bytes: bytes) -> bool:
    """Exact-pixel comparison of two decodable images (re-encode safe)."""
    try:
        import numpy as np
        from PIL import Image
        ia = np.asarray(Image.open(io.BytesIO(a_bytes)).convert("RGB"))
        ib = np.asarray(Image.open(io.BytesIO(b_bytes)).convert("RGB"))
        return ia.shape == ib.shape and int(
            np.abs(ia.astype(int) - ib.astype(int)).max()) == 0
    except Exception:
        return False


def _reverify_member(member: str, data: bytes, rec: dict, pdf_path: str,
                     embedded_index: dict, embedded_bytes: dict) -> list:
    """Content re-verification of one allowlisted image against the pinned PDF.

    Render members: the recorded crop is re-checked for marker / answer /
    explanation text on the original page (whole-page renders categorically
    refused). Raster members: bytes (or exact pixels, for lossless re-encodes)
    must match an embedded PDF image AND machine mark detection must find no
    selection marks. This is what makes a REGENERATED manifest wrapped around
    a leaky or marked image a detected attack.
    """
    from . import exhibit_crop
    from . import marking as marking_mod
    problems = []
    if rec.get("pixel_source") == "pdf_region_render":
        r = rec.get("render") or {}
        if not r.get("page") or not r.get("clip"):
            return [{"member": member, "reason": "RENDER_GEOMETRY_MISSING",
                     "detail": "rendered member has no recorded page/clip for "
                               "content re-verification"}]
        verdict = exhibit_crop.verify_render_clip(
            pdf_path, r["page"], r["clip"], r.get("source_number") or -1)
        if verdict["status"] == exhibit_crop.CROP_ANSWER_TEXT:
            problems.append({"member": member, "reason": "ANSWER_TEXT_IN_RENDER",
                             "detail": f"crop re-verification: {verdict['detail']}"})
        elif verdict["status"] == exhibit_crop.CROP_UNVERIFIED:
            problems.append({"member": member, "reason": "QUESTION_CROP_UNVERIFIED",
                             "detail": f"crop re-verification: {verdict['detail']}"})
        # the rendered pixels must still be machine-unmarked
        try:
            img = imageio.SourceImage(member, data)
            mk = marking_mod.detect_marks(img.flattened_rgb())
            if marking_mod.looks_marked(mk):
                problems.append({"member": member,
                                 "reason": "MARKED_IMAGE_IN_ALLOWLIST",
                                 "detail": f"mark detection on the shipped pixels "
                                           f"found {mk['detected_mark_boxes']} "
                                           f"pen-like shape(s)"})
        except Exception as exc:
            problems.append({"member": member, "reason": "MEMBER_UNDECODABLE",
                             "detail": str(exc)[:120]})
        return problems

    # raster member: provenance re-match against the pinned PDF + mark check
    sha = imageio.sha256_bytes(data)
    provenance_ok = sha in embedded_index
    if not provenance_ok:
        # second chance: exact pixels against ANY embedded image (covers the
        # documented lossless JPEG->PNG re-encode path)
        for raw in embedded_bytes.values():
            if _pixels_equal(data, raw):
                provenance_ok = True
                break
    if not provenance_ok:
        problems.append({"member": member, "reason": "RASTER_PROVENANCE_MISMATCH",
                         "detail": "member pixels do not match any image embedded "
                                   "in the pinned source PDF"})
    try:
        img = imageio.SourceImage(member, data)
        mk = marking_mod.detect_marks(img.flattened_rgb())
        if marking_mod.looks_marked(mk):
            problems.append({"member": member, "reason": "MARKED_IMAGE_IN_ALLOWLIST",
                             "detail": f"mark detection found "
                                       f"{mk['detected_mark_boxes']} pen-like "
                                       f"shape(s) in an allowlisted member"})
    except Exception as exc:
        problems.append({"member": member, "reason": "MEMBER_UNDECODABLE",
                         "detail": str(exc)[:120]})
    return problems


def verify_package(manifest_path: str, package_path: str, *, allow_external_urls=False,
                   allowed_hosts=(), source_pdf: str = None,
                   require_package_integrity: bool = True,
                   require_receipt: bool = False,
                   manifest_key_env: str = "CERTPASSLY_MANIFEST_KEY",
                   source_receipt: str = None,
                   content_reverification: bool = True) -> dict:
    """Verify one learner draft ZIP against the manifest allowlist.

    Returns a full report dict; callers enforce (exit 3) on any hard problem.
    All findings are collected so one run reports EVERY leak. ``passed`` is
    False on hard problems AND on scoring-key flags (P0 correction).
    """
    manifest = load_manifest(
        manifest_path, require_package_integrity=require_package_integrity)
    allow = build_allowlist(manifest)
    known_reviewer = reviewer_only_shas(manifest)

    problems = []
    flags = []
    if require_receipt:
        problems.extend(_check_receipt(manifest, key_env=manifest_key_env))
    if source_receipt:
        problems.extend(_check_source_receipt(manifest, source_receipt))

    if not os.path.isfile(package_path):
        from .errors import OperationalError
        raise OperationalError(f"package not found: {package_path}")
    try:
        zf = zipfile.ZipFile(package_path)
    except zipfile.BadZipFile as exc:
        from .errors import OperationalError
        raise OperationalError(f"package is not a valid ZIP: {exc}") from exc

    # content re-verification runs against the PINNED source PDF supplied by
    # the caller (the CLI passes the config-verified PDF); a direct library
    # caller must pass source_pdf explicitly to get re-verification
    pdf_path = source_pdf
    if pdf_path is None:
        content_reverification = False

    seen_basenames = {}
    image_members = 0
    text_members = 0
    verified_members = {}

    def norm(name: str) -> str:
        return name.replace("\\", "/").lstrip("/").lower()

    def check_member(name: str, data: bytes, prefix: str):
        nonlocal image_members, text_members
        raw_name = prefix + name
        n = norm(name)
        # path traversal / absolute / drive letters
        if ".." in name.replace("\\", "/").split("/") or name.startswith(("/", "\\")) \
                or re.match(r"^[A-Za-z]:", name):
            problems.append({"member": raw_name, "reason": "PATH_TRAVERSAL_OR_ABSOLUTE"})
        base = n.rsplit("/", 1)[-1]
        if _is_image_name(n) or _is_image_bytes(data):
            image_members += 1
            sha = imageio.sha256_bytes(data)
            if sha in known_reviewer:
                problems.append({"member": raw_name, "reason":
                                 "REVIEWER_ONLY_BINARY_IN_PACKAGE",
                                 "detail": "bytes match a known marked/reviewer-only asset"})
            elif base in allow:
                if allow[base]["sha256"] != sha:
                    problems.append({"member": raw_name, "reason": "SHA_MISMATCH_VS_MANIFEST",
                                     "detail": f"expected {allow[base]['sha256']}, found {sha}"})
                if base in seen_basenames and seen_basenames[base] != raw_name:
                    problems.append({"member": raw_name, "reason": "DUPLICATE_ASSET_IDENTITY",
                                     "detail": f"also present as {seen_basenames[base]}"})
                verified_members[raw_name] = (base, data)
                # NOTE: the same bytes under two DIFFERENT allowlisted names is
                # legitimate asset deduplication (one exhibit reused by several
                # questions); only unallowlisted or reviewer-only duplicates are
                # refused (UNALLOWED_IMAGE_MEMBER / REVIEWER_ONLY_BINARY_IN_PACKAGE).
            else:
                problems.append({"member": raw_name, "reason": "UNALLOWED_IMAGE_MEMBER",
                                 "detail": "not on the verified clean-candidate allowlist"})
            seen_basenames.setdefault(base, raw_name)
            return
        # nested archives
        if n.endswith(NESTED_ZIPS):
            if zipfile.is_zipfile(io.BytesIO(data)):
                problems.append({"member": raw_name, "reason": "NESTED_ZIP_REJECTED",
                                 "detail": "nested archives are not allowed in learner packages"})
                return
        # text-ish member: scan references
        text_members += 1
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            return
        for m in _URL_RX.finditer(text):
            url = m.group(0)
            if not allow_external_urls:
                problems.append({"member": raw_name, "reason": "EXTERNAL_URL",
                                 "detail": url[:120]})
            else:
                host_ok = any(h in url for h in allowed_hosts)
                if not host_ok:
                    problems.append({"member": raw_name, "reason": "EXTERNAL_URL_NOT_ALLOWED_HOST",
                                     "detail": url[:120]})
        for m in _LOCAL_REF_RX.finditer(text):
            ref = (m.group(1) or m.group(2) or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
            if ref and ref not in allow:
                problems.append({"member": raw_name, "reason": "IMAGE_REF_NOT_ALLOWLISTED",
                                 "detail": (m.group(1) or m.group(2))[:160]})
        for kw in SCORING_KEY_FIELDS:
            if re.search(rf'["\']{re.escape(kw)}["\']\s*:', text):
                flags.append({"member": raw_name, "flag": SCORING_FLAG,
                              "detail": f"field '{kw}' present in a learner-visible file"})
        if re.search(r'["\']is_published["\']\s*:\s*true', text):
            problems.append({"member": raw_name, "reason": "PUBLISH_FLAG_IN_DRAFT",
                             "detail": "is_published=true rejected in draft packages"})

    for info in zf.infolist():
        if info.is_dir():
            continue
        # symlink members: unix mode with S_IFLNK
        mode = info.external_attr >> 16
        if mode and (mode & 0o170000) == 0o120000:
            problems.append({"member": info.filename, "reason": "SYMLINK_MEMBER"})
            continue
        data = zf.read(info)
        check_member(info.filename, data, "")

    # every allowlisted clean file must actually be present
    present = {norm(i.filename).rsplit("/", 1)[-1] for i in zf.infolist() if not i.is_dir()}
    for base, rec in allow.items():
        if base not in present:
            problems.append({"member": base, "reason": "MISSING_CLEAN_IMAGE",
                             "detail": f"allowlisted for {rec['question_id']} but absent"})

    # P0 correction: content re-verification of every allowlisted image that
    # is actually shipped, against the PINNED source PDF
    reverified = 0
    if content_reverification and pdf_path:
        try:
            embedded_index, embedded_bytes = _embedded_image_index(pdf_path)
            for raw_name, (base, data) in verified_members.items():
                problems.extend(_reverify_member(raw_name, data, allow[base],
                                                 pdf_path, embedded_index,
                                                 embedded_bytes))
                reverified += 1
        except ImportError:
            problems.append({"member": "manifest", "reason": "REVERIFICATION_UNAVAILABLE",
                             "detail": "content re-verification requires PyMuPDF; "
                                       "refusing rather than trusting the manifest alone"})

    return {
        "package": package_path,
        "manifest": manifest_path,
        "allowlisted_images": len(allow),
        "image_members": image_members,
        "text_members": text_members,
        "content_reverified_members": reverified,
        "problems": problems,
        "flags": flags,
        # P0 correction: scoring flags FAIL the gate for direct library
        # callers exactly as they already did for the CLI (exit 3)
        "passed": not problems and not flags,
    }


def enforce(report: dict) -> None:
    """Raise the typed privacy refusal when the report has hard problems OR
    scoring-key flags (P0 correction: direct library callers must not be able
    to accept a key-bearing payload via report['passed'])."""
    if report.get("problems") or report.get("flags"):
        lines = []
        for p in report.get("problems") or []:
            lines.append(f"  - {p['member']}: {p['reason']}"
                         + (f" ({p['detail'][:100]})" if p.get("detail") else ""))
        for f in report.get("flags") or []:
            lines.append(f"  - {f['member']}: {f['flag']} ({f.get('detail', '')})")
        raise PrivacyViolationError(
            f"PRIVACY GATE REFUSED the learner package "
            f"({len(report.get('problems') or [])} hard problem(s), "
            f"{len(report.get('flags') or [])} scoring flag(s)):\n{lines}")


def verify_release_candidate(manifest_path: str, package_path: str, *,
                             source_pdf: str, source_receipt: str,
                             manifest_key_env: str = "CERTPASSLY_MANIFEST_KEY") -> dict:
    """B5 mandatory strict technical preflight, never release authorization.

    The convenience verify_package API permits synthetic tests without an
    external receipt. THIS ENTRYPOINT DOES NOT: a genuine local PDF,
    independently pinned source receipt and out-of-package HMAC signing key
    are mandatory. The PDF file itself is rehashed before any image check.

    A passing report means only media/privacy technical preflight succeeded.
    Human answers, rights, import staging and live site UI remain UNTESTED.
    """
    import hashlib
    if not source_pdf or not os.path.isfile(source_pdf):
        raise PrivacyViolationError("trusted original source_pdf required")
    if not source_receipt or not os.path.isfile(source_receipt):
        raise PrivacyViolationError("independent source_receipt required")
    manifest = load_manifest(manifest_path, require_package_integrity=True)
    digest = hashlib.sha256()
    size = 0
    with open(source_pdf, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    if digest.hexdigest() != manifest.get("source_pdf_sha256") or (
        size != manifest.get("source_pdf_bytes")
    ):
        raise PrivacyViolationError("original PDF bytes/SHA do not match the "
                                    "immutable media manifest identity")
    report = verify_package(
        manifest_path, package_path, allow_external_urls=False,
        source_pdf=source_pdf, source_receipt=source_receipt,
        require_package_integrity=True, require_receipt=True,
        manifest_key_env=manifest_key_env, content_reverification=True)
    report["technical_privacy_preflight"] = "PASS" if report["passed"] else "BLOCKED"
    report["site_ui_status"] = "UNTESTED"
    report["human_approval_status"] = "NOT_APPROVED"
    return report
