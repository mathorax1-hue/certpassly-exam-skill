#!/usr/bin/env python3
"""Phase 1 extraction shared helpers (public CertPassly toolkit, config-driven).

No exam-specific values live in this module: every count, path, regex and note
comes from the per-exam config JSON passed to each tool. See
docs/PHASE1-EXTRACTION.md in the skill repository.

Optional config["provenance"] block (all keys optional; defaults keep the
historical private-toolkit labels so previously accepted extractions reproduce
byte-identically with their original configs):
  toolkit_label              label of the engine recorded in emitted READMEs
  commands_reference         where the emitted README points for exact commands
  builder_script             engine script label recorded in source-manifest.json
  audit_tool                 tool label recorded in audit JSON output
  exports_regeneration_command  default regeneration command label in exports
"""
from __future__ import annotations
import hashlib, json, os, re, subprocess, sys
from collections import Counter

# Legacy default provenance labels (kept verbatim for byte-identical replay of
# previously accepted extractions; new runs should override via config
# "provenance" to record the public skill module and its pinned commit).
LEGACY_TOOLKIT_LABEL = "the config-driven phase1-extraction toolkit (`tools/phase1-extraction/`, ZAI-EXTRACT-002)"
LEGACY_COMMANDS_REFERENCE = "`tools/phase1-extraction/README.md`"
LEGACY_BUILDER_SCRIPT = "tools/phase1-extraction/build_structured_v1.py"
LEGACY_AUDIT_TOOL = "tools/phase1-extraction/audit_source.py"
LEGACY_EXPORTS_REGENERATION = (
    "python -m certpassly.phase1.build_exports <config.json> "
    "(certpassly-exam-skill src/certpassly/phase1/)"
)


class ConfigError(Exception):
    pass


def load_config(path):
    with open(path, encoding='utf-8') as f:
        cfg = json.load(f)
    for key in ("exam_code", "paths"):
        if key not in cfg:
            raise ConfigError(f"config missing required key: {key}")
    for key in ("pdf", "repo", "out_dir", "upstream_out", "pmap"):
        if key not in cfg["paths"]:
            raise ConfigError(f"config.paths missing required key: {key}")
    return cfg


def provenance(cfg, key, legacy):
    """Resolve a provenance label: section value > provenance block > legacy default.

    ``key`` is one of the provenance keys documented in the module docstring;
    ``legacy`` is the byte-compat default from the historical private toolkit.
    """
    prov = cfg.get("provenance") or {}
    return prov.get(key, legacy)


def jload(p, default=None):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        if default is not None:
            return default
        raise


def jdump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def repo_path(cfg, rel):
    """Resolve a repo-relative reference declared in config against the repo worktree."""
    return os.path.join(cfg["paths"]["repo"], rel)


class Result:
    """Check accumulator used by validate/reconcile; fail-closed semantics."""

    def __init__(self):
        self.checks = []
        # P0-2 (director audit 2026-11-13): informational notes are recorded
        # separately and are NEVER part of the passed-check denominator; a
        # note is explicitly "not tested", not a synthetic-true check.
        self.notes = []

    def check(self, name, ok, detail=""):
        self.checks.append(dict(check=name, passed=bool(ok), detail=str(detail)[:300]))
        return bool(ok)

    def note(self, name, detail=""):
        """Record an informational item OUTSIDE the passed-check denominator.

        Use for context that cannot be machine-verified against reproducible
        evidence (e.g. a prose recollection of a pinned stage log). Notes have
        no pass/fail semantics and must never be cited as passed checks.
        """
        self.notes.append(dict(note=name, detail=str(detail)[:300]))

    @property
    def failed(self):
        return [c for c in self.checks if not c["passed"]]

    def summary(self):
        return f"{len(self.checks) - len(self.failed)}/{len(self.checks)} passed"


def git_head(repo):
    r = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def git_blob_sha(repo, path):
    r = subprocess.run(["git", "-C", repo, "rev-parse", f"HEAD:{path}"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def compile_layout(cfg):
    """Compile the config-driven layout rules once. Returns a namespace."""
    lay = cfg.get("layout", {})
    ns = dict(
        MARKER=re.compile(lay.get("marker_regex", r"^QUESTION\s+(\d+)\s*$")),
        ANSWER=re.compile(lay.get("answer_regex", r"^Correct Answers?:\s*(.*)$"), re.I),
        OPTION=re.compile(lay.get("option_regex", r"^([A-F])\.(?:\s+(.*))?$")),
        STRUCTURAL_EXACT=set(lay.get("structural_exact",
                                     ["Section: (none)", "Explanation", "Explanation/Reference:"])),
        cover_pages=set(lay.get("cover_pages", [1])),
        marketing_pages=set(lay.get("marketing_pages", [])),
        visual_placeholders=set(t.strip().lower() for t in
                                lay.get("visual_option_placeholder_texts", [])),
    )
    return ns


def is_visual_question(rec, ns):
    """True when the real choices live inside the question image.

    Generic rule: no text options, OR every option text is one of the configured
    VCE-template placeholder strings (e.g. 'See Explanation section for answer.').
    """
    opts = rec.get("options") or {}
    if not opts:
        return True
    texts = [(v or "").strip().lower() for v in opts.values()]
    return bool(texts) and all(t in ns["visual_placeholders"] for t in texts)


def page_coordinate_note(page0_rotation, page0_display, lay):
    """Deterministic geometry note; matches the AB-900 pilot string for /Rotate 90
    792x612 landscape pages, generic text otherwise."""
    rot = page0_rotation
    w, h = round(page0_display[2] - page0_display[0]), round(page0_display[3] - page0_display[1])
    if rot in (90, 270) and w > h:
        return (f"bbox_display uses the page coordinate space AFTER applying /Rotate {rot} "
                f"(origin top-left, {w}x{h} pt landscape); raw PDF space is {h}x{w} portrait.")
    return (f"bbox_display uses the page coordinate space as-is (no /Rotate applied; "
            f"origin top-left, {w}x{h} pt).")
