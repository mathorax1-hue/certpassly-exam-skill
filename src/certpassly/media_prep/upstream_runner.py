"""Run the PINNED external upstream extractor (subprocess; never reimplemented).

The 15-stage engine lives in msaqlainhaneef1/certpassly-exam-pipeline at the
pinned commit. This module only ever CALLS ``extract_owner_pdf.py`` from a
read-only checkout (config upstream.scripts_dir) and records the exact
command + exit code. If the upstream output already exists, nothing runs -
deterministic reuse, no unnecessary re-extraction.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

from .errors import ConfigError, OperationalError


def _tree_hash(scripts_dir: str) -> str:
    """Content hash of the pinned upstream scripts tree (drift detection)."""
    h = hashlib.sha256()
    for root, dirs, files in os.walk(scripts_dir):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, scripts_dir).replace(os.sep, "/")
            with open(p, "rb") as fh:
                h.update(rel.encode())
                h.update(b"\0")
                h.update(fh.read())
                h.update(b"\0")
    return h.hexdigest()


def _git_head(scripts_dir: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", scripts_dir, "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def upstream_status(cfg: dict) -> dict:
    """Read-only report about the configured pinned upstream checkout."""
    scripts_dir = cfg["upstream"]["scripts_dir"]
    if scripts_dir is None:
        return {"configured": False, "repo": cfg["upstream"]["repo"],
                "commit": cfg["upstream"]["commit"],
                "note": "upstream.scripts_dir not configured (scan can still "
                        "consume an existing extraction output)"}
    if not os.path.isdir(scripts_dir):
        return {"configured": True, "repo": cfg["upstream"]["repo"],
                "commit": cfg["upstream"]["commit"],
                "scripts_dir": scripts_dir, "exists": False}
    extract = os.path.join(scripts_dir, "extract_owner_pdf.py")
    return {
        "configured": True,
        "repo": cfg["upstream"]["repo"],
        "commit": cfg["upstream"]["commit"],
        "scripts_dir": scripts_dir,
        "exists": True,
        "extract_owner_pdf": os.path.isfile(extract),
        "scripts_tree_sha256": _tree_hash(scripts_dir),
        "git_head": _git_head(scripts_dir),
    }


def ensure_upstream_output(cfg: dict, force=None) -> dict:
    """Ensure <upstream.out_dir>/extracted/split.json exists.

    When config upstream.run_extract is true and the output is missing (or
    force=True), run the pinned upstream extract_owner_pdf.py via subprocess
    with the SAME interface it documents: extract_owner_pdf.py <pdf> <out>.
    Never reimplements, never patches, never writes inside the checkout.
    """
    out_dir = cfg["upstream"]["out_dir"]
    split_path = os.path.join(out_dir, "extracted", "split.json")
    if os.path.isfile(split_path) and not force:
        return {"ran": False, "reason": "existing upstream output reused",
                "split_path": split_path}
    run = cfg["upstream"]["run_extract"] if force is None else bool(force)
    if not run:
        if os.path.isfile(split_path):
            return {"ran": False, "reason": "existing upstream output reused",
                    "split_path": split_path}
        raise OperationalError(
            f"upstream extraction output missing ({split_path}) and "
            f"upstream.run_extract is false - either run the pinned upstream "
            f"extractor yourself or set upstream.run_extract=true with a "
            f"configured scripts_dir")
    scripts_dir = cfg["upstream"]["scripts_dir"]
    if scripts_dir is None:
        raise ConfigError("upstream.run_extract=true requires upstream.scripts_dir")
    script = os.path.join(scripts_dir, "extract_owner_pdf.py")
    if not os.path.isfile(script):
        raise OperationalError(f"pinned upstream extractor not found: {script}")
    cmd = [sys.executable, script, cfg["source"]["pdf"], out_dir]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(split_path):
        raise OperationalError(
            f"pinned upstream extractor failed (exit {r.returncode}): "
            f"{(r.stderr or r.stdout or '')[:500]}")
    return {"ran": True, "reason": "pinned upstream extract_owner_pdf.py executed",
            "command": " ".join([os.path.basename(script), "<pdf>", "<out_dir>"]),
            "exit_code": r.returncode, "stdout_tail": (r.stdout or "")[-300:],
            "split_path": split_path}
