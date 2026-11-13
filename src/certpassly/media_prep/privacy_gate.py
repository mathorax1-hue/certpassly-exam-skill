"""HARD privacy gate: allowlist-based learner package verification (exit 3 on refusal).

Architecture (per the operator order):
  - learner archives are built from an EXPLICIT ALLOWLIST of verified
    ``question_clean_candidate`` (question_id -> written file SHA) taken from
    the tamper-evident manifest. Anything not on the list is refused, not
    filtered-after-copying;
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

The gate is deliberately paranoid: it FAILS CLOSED (exit 3) and never
"repairs" a bad package. It cannot prove the live site's server behavior; if
the package ships pre-submit scoring keys (correct_option_ids etc.) it flags
SITE_SCORING_ARCHITECTURE_REVIEW_REQUIRED and refuses to certify.
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


def load_manifest(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise PrivacyViolationError(f"cannot read manifest {path}: {exc}")
    if m.get("schema_version") != "image-manifest-v1":
        raise PrivacyViolationError(f"manifest {path} is not image-manifest-v1")
    # integrity: entries hash must match the questions array
    from .manifest import entries_hash
    claimed = (m.get("integrity") or {}).get("entries_sha256")
    actual = entries_hash(m.get("questions") or [])
    if not claimed or claimed != actual:
        raise PrivacyViolationError(
            "manifest integrity check FAILED: entries_sha256 does not match the "
            "questions array (tampered manifest?)")
    return m


def build_allowlist(manifest: dict) -> dict:
    """{member basename: {"sha256":..., "question_id":..., "method":...}} from
    verified learner-eligible manifest entries ONLY."""
    allow = {}
    for entry in manifest.get("questions") or []:
        cand = entry.get("clean_candidate") or {}
        if not entry.get("is_learner_eligible") or not cand.get("file"):
            continue
        allow[cand["file"].rsplit("/", 1)[-1]] = {
            "sha256": cand["sha256"],
            "question_id": entry["question_id"],
            "method": cand.get("method"),
        }
    return allow


def reviewer_only_shas(manifest: dict) -> set[str]:
    return {r["sha256"] for r in manifest.get("reviewer_only_assets") or []}


def verify_package(manifest_path: str, package_path: str, *, allow_external_urls=False,
                   allowed_hosts=()) -> dict:
    """Verify one learner draft ZIP against the manifest allowlist.

    Returns a full report dict; callers enforce (exit 3) on any hard problem.
    All findings are collected so one run reports EVERY leak.
    """
    manifest = load_manifest(manifest_path)
    allow = build_allowlist(manifest)
    known_reviewer = reviewer_only_shas(manifest)

    if not os.path.isfile(package_path):
        from .errors import OperationalError
        raise OperationalError(f"package not found: {package_path}")
    try:
        zf = zipfile.ZipFile(package_path)
    except zipfile.BadZipFile as exc:
        from .errors import OperationalError
        raise OperationalError(f"package is not a valid ZIP: {exc}") from exc

    problems = []
    flags = []
    seen_basenames = {}
    image_members = 0
    text_members = 0

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

    return {
        "package": package_path,
        "manifest": manifest_path,
        "allowlisted_images": len(allow),
        "image_members": image_members,
        "text_members": text_members,
        "problems": problems,
        "flags": flags,
        "passed": not problems,
    }


def enforce(report: dict) -> None:
    """Raise the typed privacy refusal when the report has hard problems."""
    if report.get("problems"):
        lines = "\n".join(
            f"  - {p['member']}: {p['reason']}"
            + (f" ({p['detail'][:100]})" if p.get("detail") else "")
            for p in report["problems"])
        raise PrivacyViolationError(
            f"PRIVACY GATE REFUSED the learner package "
            f"({len(report['problems'])} hard problem(s)):\n{lines}")
