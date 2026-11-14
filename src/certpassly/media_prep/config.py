"""Media-prep config loading and validation (media-prep-v1).

The config is the single source of truth for paths, pins, quality thresholds
and privacy flags. All paths are resolved RELATIVE TO THE CONFIG FILE's
directory (never relative to the process CWD) so commands are reproducible
from any working directory on Linux and Windows. Absolute paths pass through.

Required structure (see schemas/media-prep-config-v1.schema.json):

  {
    "schema_version": "media-prep-v1",
    "exam_code": "SYNTHETIC-DEMO",
    "source":  {"pdf": "...", "expected_sha256": "<64hex>", "expected_bytes": N},
    "upstream": {"scripts_dir": "...", "out_dir": "...", "run_extract": false,
                 "repo": "...", "commit": "<40hex>"},
    "output": {"clean_dir": "...", "private_dir": "...",
               "manifest": "...", "inventory": "..."},
    "display": {"default_css_width": 640, "pixel_density_goal": 2.0},
    "quality_profiles": {"diagram": {...}, "screenshot": {...}},   # optional
    "privacy": {"allow_external_urls": false, "allowed_hosts": [],
                "require_package_integrity": true,     # refuse legacy manifests
                "require_receipt": false,               # require HMAC receipt
                "manifest_key_env": "CERTPASSLY_MANIFEST_KEY",
                "source_receipt": "../exams/AB-730/manifest.json"}  # optional
  }

The ``privacy`` keys after ``allowed_hosts`` are the 2026-11-14 P0 trust
hardening: ``require_package_integrity`` (default true) refuses manifests
without a valid package-integrity digest over ALL security-critical fields;
``require_receipt`` (default false) additionally demands a valid HMAC
receipt keyed by a secret read from the ``manifest_key_env`` environment
variable (the key NEVER lives in code or the package); ``source_receipt``
optionally binds the manifest's source PDF identity to an independently
pinned exam manifest file.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from .errors import ConfigError

HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")

# Quality-profile defaults. A "diagram" (vector shapes, text labels) and a
# "screenshot" (dense UI raster) tolerate different blur/contrast/density
# levels; there is deliberately NO single universal threshold.
DEFAULT_PROFILES = {
    "diagram": {
        "min_native_width": 240,
        "min_effective_density": 1.0,
        "max_blur_flag": 220.0,      # Laplacian variance below -> SOURCE_IMAGE_BLURRY
        "min_rms_contrast": 0.02,
        "max_dark_clip_fraction": 0.5,
        "min_text_edge_density": 0.0,  # advisory only (0 disables)
    },
    "screenshot": {
        "min_native_width": 320,
        "min_effective_density": 1.0,
        "max_blur_flag": 120.0,
        "min_rms_contrast": 0.035,
        "max_dark_clip_fraction": 0.5,
        "min_text_edge_density": 0.0,
    },
}
PROFILE_KEYS = ("min_native_width", "min_effective_density", "max_blur_flag",
                "min_rms_contrast", "max_dark_clip_fraction", "min_text_edge_density")


def _resolve(base_dir: str, value: str, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"config {what} must be a non-empty string")
    p = os.path.expanduser(value)
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(base_dir, p))


def _require(mapping: dict, key: str, where: str):
    if key not in mapping:
        raise ConfigError(f"config {where} missing required key: {key}")
    return mapping[key]


def _validate_profiles(raw: dict) -> dict:
    profiles = {k: dict(v) for k, v in DEFAULT_PROFILES.items()}
    for name, over in (raw or {}).items():
        if name not in profiles:
            raise ConfigError(f"unknown quality profile: {name} (expected one of {sorted(profiles)})")
        if not isinstance(over, dict):
            raise ConfigError(f"quality_profiles.{name} must be an object")
        for k, v in over.items():
            if k not in PROFILE_KEYS:
                raise ConfigError(f"quality_profiles.{name}.{k} is not a known key")
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
                raise ConfigError(f"quality_profiles.{name}.{k} must be a non-negative number")
        profiles[name].update(over)
    return profiles


def load_config(path: str) -> dict:
    """Load + validate a media-prep config; returns a normalized dict."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a JSON object")
    if raw.get("schema_version") != "media-prep-v1":
        raise ConfigError("config schema_version must be 'media-prep-v1'")
    base = os.path.dirname(os.path.abspath(path))
    exam = _require(raw, "exam_code", "root")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", str(exam)):
        raise ConfigError("config exam_code must be 1-64 chars of [A-Za-z0-9._-]")

    src = raw.get("source")
    if not isinstance(src, dict):
        raise ConfigError("config.source must be an object")
    pdf = _resolve(base, _require(src, "pdf", "source"), "source.pdf")
    if not os.path.isfile(pdf):
        raise ConfigError(f"source PDF not found: {pdf}")
    sha = _require(src, "expected_sha256", "source")
    if not HEX64.fullmatch(str(sha)):
        raise ConfigError("source.expected_sha256 must be 64 lowercase hex chars")
    nbytes = src.get("expected_bytes")
    if nbytes is not None and (not isinstance(nbytes, int) or nbytes < 0):
        raise ConfigError("source.expected_bytes must be a non-negative integer")

    up = raw.get("upstream")
    if not isinstance(up, dict):
        raise ConfigError("config.upstream must be an object")
    out_dir = _resolve(base, _require(up, "out_dir", "upstream"), "upstream.out_dir")
    scripts_dir = up.get("scripts_dir")
    if scripts_dir is not None:
        scripts_dir = _resolve(base, scripts_dir, "upstream.scripts_dir")
        if not os.path.isdir(scripts_dir):
            raise ConfigError(f"upstream.scripts_dir not a directory: {scripts_dir}")
    run_extract = up.get("run_extract", False)
    if not isinstance(run_extract, bool):
        raise ConfigError("upstream.run_extract must be a boolean")
    if run_extract and scripts_dir is None:
        raise ConfigError("upstream.run_extract=true requires upstream.scripts_dir")
    commit = up.get("commit")
    if commit is not None and not HEX40.fullmatch(str(commit)):
        raise ConfigError("upstream.commit must be 40 lowercase hex chars")

    out = raw.get("output")
    if not isinstance(out, dict):
        raise ConfigError("config.output must be an object")
    resolved_out = {
        "clean_dir": _resolve(base, _require(out, "clean_dir", "output"), "output.clean_dir"),
        "private_dir": _resolve(base, _require(out, "private_dir", "output"), "output.private_dir"),
        "manifest": _resolve(base, _require(out, "manifest", "output"), "output.manifest"),
        "inventory": _resolve(base, _require(out, "inventory", "output"), "output.inventory"),
    }

    disp = raw.get("display") or {}
    if not isinstance(disp, dict):
        raise ConfigError("config.display must be an object")
    css_w = disp.get("default_css_width", 640)
    goal = disp.get("pixel_density_goal", 2.0)
    if not isinstance(css_w, (int, float)) or css_w <= 0:
        raise ConfigError("display.default_css_width must be positive")
    if not isinstance(goal, (int, float)) or goal <= 0:
        raise ConfigError("display.pixel_density_goal must be positive")

    priv = raw.get("privacy") or {}
    if not isinstance(priv, dict):
        raise ConfigError("config.privacy must be an object")
    allow_ext = priv.get("allow_external_urls", False)
    if not isinstance(allow_ext, bool):
        raise ConfigError("privacy.allow_external_urls must be a boolean")
    hosts = priv.get("allowed_hosts", [])
    if not isinstance(hosts, list) or not all(isinstance(h, str) for h in hosts):
        raise ConfigError("privacy.allowed_hosts must be a list of strings")
    # --- 2026-11-14 P0 correction: manifest trust hardening -------------
    require_pkg_integrity = priv.get("require_package_integrity", True)
    if not isinstance(require_pkg_integrity, bool):
        raise ConfigError("privacy.require_package_integrity must be a boolean")
    require_receipt = priv.get("require_receipt", False)
    if not isinstance(require_receipt, bool):
        raise ConfigError("privacy.require_receipt must be a boolean")
    key_env = priv.get("manifest_key_env", "CERTPASSLY_MANIFEST_KEY")
    if not isinstance(key_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env):
        raise ConfigError("privacy.manifest_key_env must be an environment "
                          "variable name (letters, digits, underscores)")
    if require_receipt and not key_env:
        raise ConfigError("privacy.require_receipt=true needs privacy.manifest_key_env")
    source_receipt = priv.get("source_receipt")
    if source_receipt is not None:
        source_receipt = _resolve(base, source_receipt, "privacy.source_receipt")
        if not os.path.isfile(source_receipt):
            raise ConfigError(f"privacy.source_receipt not a file: {source_receipt}")

    return {
        "config_path": os.path.abspath(path),
        "schema_version": "media-prep-v1",
        "exam_code": exam,
        "source": {"pdf": pdf, "expected_sha256": sha, "expected_bytes": nbytes},
        "upstream": {
            "scripts_dir": scripts_dir, "out_dir": out_dir,
            "run_extract": run_extract,
            "repo": up.get("repo", "msaqlainhaneef1/certpassly-exam-pipeline"),
            "commit": commit,
        },
        "output": resolved_out,
        "display": {"default_css_width": float(css_w), "pixel_density_goal": float(goal)},
        "quality_profiles": _validate_profiles(raw.get("quality_profiles")),
        "privacy": {
            "allow_external_urls": allow_ext,
            "allowed_hosts": hosts,
            "require_package_integrity": require_pkg_integrity,
            "require_receipt": require_receipt,
            "manifest_key_env": key_env,
            "source_receipt": source_receipt,
        },
    }


def verify_source_identity(cfg: dict) -> dict:
    """Fail-closed source identity check (SHA-256 and bytes). Never modifies the PDF."""
    pdf = cfg["source"]["pdf"]
    h = hashlib.sha256()
    total = 0
    with open(pdf, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            total += len(chunk)
    digest = h.hexdigest()
    problems = []
    if digest != cfg["source"]["expected_sha256"]:
        problems.append(f"sha256 mismatch: expected {cfg['source']['expected_sha256']}, got {digest}")
    exp_bytes = cfg["source"]["expected_bytes"]
    if exp_bytes is not None and total != exp_bytes:
        problems.append(f"byte size mismatch: expected {exp_bytes}, got {total}")
    return {"pdf": pdf, "sha256": digest, "bytes": total,
            "identity_ok": not problems, "problems": problems}
