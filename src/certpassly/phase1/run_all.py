#!/usr/bin/env python3
"""Phase 1 extraction: stage orchestrator with checkpoints (public toolkit).

Usage: python -m certpassly.phase1.run_all --config <config.json>
                  --upstream-scripts <dir>
                  [--adversarial-base <scratch>] [--skip-adversarial]
                  [--dry-run] [--resume] [--start-from <stage>]

Runs, in order: audit_source (stage 0, P0-C hard gate), build_structured_v1,
build_exports, make_source_manifest, validate_structured_v1, reconcile,
visual_qa, adversarial (optional).

Behavior:
  - deterministic: every stage is idempotent; re-running the whole sequence with
    the same config, pinned upstream checkout and source PDF reproduces the
    same outputs byte-identically (this is the canonical "resume" mode);
  - --resume / --start-from CANNOT bypass the source PDF SHA-256, identity or
    integrity checks (director final correction 1, 2026-11-13). Before any
    stage may be skipped a fail-closed SOURCE GUARD re-verifies, at resume time:
    (1) the source PDF exists right now and still hashes to the config-pinned
    expected_pdf_sha256 / expected_bytes; (2) the prior checkpoint belongs to
    this config, carries the SAME source_fingerprint (actual PDF sha256+bytes,
    config content sha256, pinned upstream scripts tree hash, engine label AND
    a content hash of the INSTALLED toolkit code tree) and an AUDIT_COMPLETE /
    non-identity-ambiguous audit summary; and (3) for
    --start-from, every earlier planned stage exited 0 in that verified
    checkpoint. A guard refusal exits 3 (GUARD_REFUSED) without running any
    stage and without overwriting the existing checkpoint; the operator must
    re-run from stage 0 so the full audit re-verifies the source. --resume with
    a missing or foreign checkpoint cannot authorize skipping anything and
    degrades to a FULL run from stage 0 (loud notice, audit re-runs);
  - --resume / --start-from also CANNOT produce a false successful no-op over
    deleted or modified GENERATED OUTPUTS (director final correction 2,
    2026-11-13). Every completed stage persists, in the checkpoint, a
    deterministic output inventory (exact generated file paths + per-file
    SHA-256, including question JSON records, image/asset binaries and QA /
    validation / reconciliation reports) plus an input baseline of the
    monitored pipeline inputs (pinned upstream split output, pmap, build-stats
    sidecar, stage-0 audit record) - all bound to the source and engine
    fingerprint recorded in the same checkpoint. Before --resume may no-op or
    any stage may be skipped, an OUTPUT-INVENTORY GUARD re-hashes every
    recorded file of the input baseline and of every skipped stage and
    compares: a deleted or edited question JSON, a swapped asset binary, a
    removed validation/reconciliation report or a tampered input is REFUSED
    with exit 3 naming the file and the stage that wrote it. A checkpoint that
    predates output inventories cannot authorize skipping anything: --resume
    degrades to an explicit FULL run from stage 0, --start-from refuses
    (exit 3);
  - the checkpoint is additionally an EXACT FILE-SET receipt (director final
    correction 3, 2026-11-13): before --resume may no-op or any stage may be
    skipped, every file present RIGHT NOW in the monitored output roots must
    be attributable to the verified input baseline, to a skipped stage's
    recorded outputs (SHA-verified), to a prior-run recorded stage not planned
    now, or to a planned stage this run will regenerate anyway (recorded
    later-stage paths, allowed by path only - their content is rewritten, so
    it is never trusted as verified state). An UNEXPECTED EXTRA file - an
    injected structured/v1/questions/q999.json, a stray answer asset, a rogue
    file in the pinned upstream output - is refused with exit 3 naming the
    path; unknown files can never authorize skipping nor silently feed
    downstream consumers. For a full --resume no-op this is strict set
    equality of the monitored file set against the checkpoint's final
    expected file set. A partial resume that fails mid-run after a stage
    wrote unrecordable partial output leaves those files untracked by design:
    the next --resume refuses and the operator re-runs from stage 0
    (fail-closed);
  - partial resumes preserve the COMPLETE checkpoint stage list (director
    final correction 3, P1): after --start-from or a partial --resume, the
    new checkpoint carries the verified skipped stages' receipts (exit
    status + output inventories, marked skipped_this_run) merged with the
    freshly executed stages - each stage exactly once, in plan order - so
    later resumes keep full traceability and partial resumes can chain
    (repeated --start-from / --resume) without rebuilding what was already
    verified; checkpoints written by older code that dropped skipped-stage
    receipts simply authorize less skipping and degrade safely to a full run;
  - --start-from <stage>: begin at a named stage (stage names as listed above)
    - only over a verified prior checkpoint with all earlier stages passed AND
    all their recorded outputs verified intact;
  - --dry-run: print the planned stage commands without executing anything
    (both guards still run and report their verdicts for --resume /
    --start-from so a would-be refusal is visible without side effects);
  - stops at the first non-zero stage and records it in the checkpoint
    (audit BLOCK exit 2, validation/reconciliation failures exit 1, and -
    since the P0-1 correction - visual_qa MACHINE VISIBILITY FAILURE exit 2);
  - writes a checkpoint next to the config (run-checkpoint.json) that includes
    the verified source_fingerprint, the audit summary read back from the
    stage-0 audit record, the input baseline and, per stage, its exit status
    and output inventory - after a partial resume the COMPLETE ordered stage
    list (verified skipped stages' receipts preserved, marked
    skipped_this_run, merged with the freshly executed stages, each stage
    exactly once).

Exit codes: 0 = all stages passed; 1/2 = a stage failed (propagated);
3 = source-guard or output-inventory-guard refusal, including unexpected
extra files in the monitored output roots (--resume / --start-from
integrity precondition).

Stages run via ``python -m certpassly.phase1.<stage>`` so the installed (or
PYTHONPATH-visible) public skill package is the engine; there is no private
duplicate of the generic code.
"""
from __future__ import annotations
import argparse, datetime, hashlib, json, os, subprocess, sys

STAGES = [
    "audit_source",
    "build_structured_v1",
    "build_exports",
    "make_source_manifest",
    "validate_structured_v1",
    "reconcile",
    "visual_qa",
]

ENGINE_LABEL = "certpassly.phase1 (public certpassly-exam-skill)"
GUARD_EXIT = 3  # distinct, documented refusal code for both guards
INVENTORY_VERSION = 1  # output-inventory checkpoint format (correction 2)

# fingerprint components compared between the prior checkpoint and the
# current run; every component must match exactly for skipping to be allowed.
# toolkit_root is recorded for transparency but intentionally NOT compared:
# what authorizes skipping is the CONTENT hash of the installed toolkit, not
# where it is installed (a relocated identical venv must not refuse).
_FINGERPRINT_KEYS = (
    "pdf_sha256", "pdf_bytes", "pdf_path",
    "config_sha256", "upstream_scripts", "upstream_tree_sha256",
    "engine", "toolkit_version", "toolkit_tree_sha256",
)


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_sha256(root, all_files=False):
    """Stable content hash of a scripts tree: sorted relative paths + bytes of
    every ``*.py`` file (the pinned upstream extractor is pure Python), or -
    with ``all_files=True`` - of every regular file (used for the INSTALLED
    toolkit tree, whose templates are data, not code). Used so that swapping
    the pinned upstream scripts, or silently updating the toolkit code under
    an unchanged version label, invalidates --resume/--start-from even when
    the PDF and config are untouched."""
    h = hashlib.sha256()
    if not os.path.isdir(root):
        return h.hexdigest()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in sorted(filenames):
            if not all_files and not fn.endswith(".py"):
                continue
            if fn.endswith((".pyc", ".pyo")) or fn == ".DS_Store":
                continue
            p = os.path.join(dirpath, fn)
            h.update(os.path.relpath(p, root).encode("utf-8"))
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()


def toolkit_fingerprint():
    """Fingerprint the INSTALLED toolkit code, not a fixed label: the content
    hash of the certpassly package tree this interpreter resolves (plus its
    declared __version__). Stages run via ``python -m certpassly.phase1.*``
    with this same interpreter, so the hashed tree is the code that runs."""
    import certpassly
    pkg_dir = os.path.dirname(os.path.abspath(certpassly.__file__))
    return dict(
        engine=ENGINE_LABEL,
        toolkit_version=str(getattr(certpassly, "__version__", "unknown")),
        toolkit_root=pkg_dir,
        toolkit_tree_sha256=_tree_sha256(pkg_dir, all_files=True),
    )


def audit_out_path(a):
    """Path of the stage-0 audit record written next to the config."""
    return os.path.join(os.path.dirname(os.path.abspath(a.config)), "source-audit.json")


def read_audit_summary(a):
    """Read back the verdict/source identity from the stage-0 audit record so
    the checkpoint embeds WHAT was audited, not just that a stage exited 0."""
    try:
        d = json.load(open(audit_out_path(a), encoding="utf-8"))
        pdf = d.get("pdf") or {}
        return dict(verdict=d.get("verdict"),
                    pdf_sha256=pdf.get("sha256"), pdf_bytes=pdf.get("bytes"),
                    identity_ambiguous=d.get("identity_ambiguous"))
    except (OSError, json.JSONDecodeError):
        return None


def source_fingerprint(a, cfg):
    """Recompute the CURRENT source fingerprint (measured from the actual
    files at run start - never from the checkpoint or any cached value). The
    engine component is the INSTALLED toolkit content hash, so a silent
    toolkit update under an unchanged version label cannot reuse a prior
    checkpoint."""
    pdf = cfg["paths"]["pdf"]
    fp = dict(
        config_sha256=_file_sha256(a.config),
        pdf_path=os.path.abspath(pdf),
        upstream_scripts=os.path.abspath(a.upstream_scripts),
        upstream_tree_sha256=_tree_sha256(a.upstream_scripts),
        **toolkit_fingerprint(),
    )
    if os.path.isfile(pdf):
        fp["pdf_sha256"] = _file_sha256(pdf)
        fp["pdf_bytes"] = os.path.getsize(pdf)
    return fp


# ---------------- output inventories (director final correction 2) --------

def monitored_paths(a, cfg):
    """(dir_roots, file_paths) monitored by the output inventory: the
    structured out_dir tree, the pinned upstream split output, the pmap and
    build-stats sidecars and the stage-0 audit record - i.e. every input the
    stages read and every output they write, except the PDF / config /
    upstream scripts, which the source fingerprint pins separately."""
    p = cfg.get("paths", {}) or {}
    dirs, files = [], []
    for key in ("out_dir", "upstream_out"):
        v = p.get(key)
        if v and os.path.isdir(v):
            dirs.append(os.path.abspath(v))
    for v in (audit_out_path(a), p.get("build_stats"), p.get("pmap")):
        if v and os.path.isfile(v):
            files.append(os.path.abspath(v))
    return dirs, files


def _untracked(a, cfg):
    """Absolute paths never included in an inventory: the config, the
    checkpoint itself and the source PDF (all fingerprinted or self)."""
    p = cfg.get("paths", {}) or {}
    out = {os.path.abspath(a.config), os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(a.config)), "run-checkpoint.json"))}
    if p.get("pdf"):
        out.add(os.path.abspath(p["pdf"]))
    return out


def snapshot_outputs(a, cfg):
    """Deterministic {abs_path: sha256} of every monitored file RIGHT NOW."""
    dirs, files = monitored_paths(a, cfg)
    skip = _untracked(a, cfg)
    snap = {}
    for root in dirs:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for fn in sorted(filenames):
                ap = os.path.abspath(os.path.join(dirpath, fn))
                if ap in skip:
                    continue
                try:
                    snap[ap] = _file_sha256(ap)
                except OSError:
                    continue  # unreadable right now: simply untracked
    for f in files:
        if f in skip:
            continue
        try:
            snap[f] = _file_sha256(f)
        except OSError:
            continue
    return snap


def _inv_entries(snap):
    """Sorted checkpoint-format inventory entries for a {path: sha} snapshot."""
    entries = []
    for p in sorted(snap):
        try:
            entries.append(dict(path=p, sha256=snap[p], bytes=os.path.getsize(p)))
        except OSError:
            continue
    return entries


def _stage_delta(before, after):
    """Inventory entries for the files a stage ADDED or MODIFIED
    (deterministic: sorted by path; later stages legitimately rewrite earlier
    files, and verification accumulates expectations in plan order)."""
    changed = {p for p in after if before.get(p) != after[p]}
    return _inv_entries({p: after[p] for p in changed})


def verify_prior_outputs(a, cfg, prior, plan, skip_names):
    """Fail-closed verification of the artifacts of the stages that would be
    SKIPPED, now including the EXACT FILE-SET inventory (director final
    correction 3, 2026-11-13: no false successful no-op over deleted,
    modified OR UNEXPECTEDLY ADDED outputs). The prior checkpoint must carry
    - and the disk must still match - (1) the input baseline recorded at the
    start of the verified run and (2) every skipped stage's output inventory;
    and (3) every file present RIGHT NOW in the monitored output roots must
    be attributable to that verified state or to a stage this run will
    re-run anyway (its recorded later-stage paths). An untracked extra file
    - an injected questions/q999.json, a stray answer asset, a rogue file in
    the pinned upstream output - is refused: it can never authorize
    skipping, because the checkpoint is an exact file-set receipt, not a
    sample of paths that happen to still hash correctly.

    Returns ``(action, reason)``:
      ``("allow", "")``        every recorded artifact is intact AND the
                              monitored file set is exactly the verified one
                              (plus, for partial resumes, recorded paths of
                              stages that will be regenerated) - skipping safe;
      ``("cannot_verify", m)`` the checkpoint predates output inventories -
                              it cannot authorize skipping anything;
      ``("refuse", m)``       recorded artifacts are missing or modified, or
                              unexpected extra files exist - integrity
                              violation, exit GUARD_EXIT.
    """
    if not skip_names:
        return ("allow", "")
    base = prior.get("input_baseline")
    if not isinstance(base, list) or not base:
        return ("cannot_verify", "the checkpoint records no input baseline "
                "(it predates output-inventory verification)")
    entries = {}
    for s in prior.get("stages", []):
        if isinstance(s, dict) and s.get("stage"):
            entries[s["stage"]] = s  # last record of a stage wins
    no_inv = [n for n in skip_names
              if not isinstance(entries.get(n, {}).get("outputs"), list)]
    if no_inv:
        return ("cannot_verify", f"no output inventory recorded for passed "
                f"stage(s) {no_inv}; the checkpoint predates per-stage output "
                f"verification")
    current = snapshot_outputs(a, cfg)
    plan_names = [name for name, _ in plan]
    # expected state = the input baseline, OVERRIDDEN in plan order by every
    # skipped stage's recorded outputs (a later stage legitimately rewrites
    # files that existed when the run started)
    expected = {e.get("path"): e.get("sha256") for e in base
                if isinstance(e, dict) and e.get("path")}
    owners = {}
    for name in plan_names:
        if name in skip_names:
            for e in entries[name]["outputs"]:
                if isinstance(e, dict) and e.get("path"):
                    expected[e["path"]] = e.get("sha256")
                    owners[e["path"]] = name
    # ... plus recorded stages that are NOT in this run's plan (e.g. an
    # adversarial stage of a prior run planned with --adversarial-base):
    # final artifacts nothing in this run regenerates, so they are verified
    # too, after the planned stages (plan order stays canonical)
    for name, s in entries.items():
        if name not in plan_names and isinstance(s.get("outputs"), list):
            for e in s["outputs"]:
                if (isinstance(e, dict) and e.get("path")
                        and e["path"] not in owners):
                    expected[e["path"]] = e.get("sha256")
                    owners[e["path"]] = name
    # paths of planned stages this run will RE-RUN anyway: allowed to exist
    # in any content (or be absent) because the re-run regenerates them -
    # tolerated by path as the checkpoint's known later-stage artifacts,
    # never trusted as verified state
    regenerating = {}
    for name in plan_names:
        if (name not in skip_names
                and isinstance(entries.get(name, {}).get("outputs"), list)):
            for e in entries[name]["outputs"]:
                if isinstance(e, dict) and e.get("path"):
                    regenerating[e["path"]] = name
    # exact file-set inventory (director final correction 3): every
    # monitored file on disk RIGHT NOW must be either verified expected
    # state or a recorded later-stage path. set(current) - set(expected)
    # is the gap the old guard never looked at.
    extras = sorted(set(current) - set(expected) - set(regenerating))
    if extras:
        shown = "; ".join(f"{p} (untracked: no verified stage or input "
                         f"baseline recorded it)" for p in extras[:5])
        shown += " ..." if len(extras) > 5 else ""
        return ("refuse", f"unexpected_output_files: {len(extras)} file(s) "
                f"present in the monitored output roots that no verified "
                f"checkpoint stage or input baseline recorded: {shown}; "
                f"inspect and remove the untracked file(s), or re-run from "
                f"stage 0 - an unknown file set can never authorize "
                f"skipping (no answer image or stray content may silently "
                f"feed downstream consumers)")
    # recorded SHA verification (correction 2 semantics), excluding the
    # paths this run regenerates (their on-disk content is about to be
    # rewritten, so only their ATTRIBUTION - checked above - matters)
    bad = sorted(p for p, s in expected.items()
                 if p not in regenerating and current.get(p) != s)
    if bad:
        bad_outputs = [p for p in bad if p in owners]
        bad_inputs = [p for p in bad if p not in owners]
        if bad_outputs:
            shown = "; ".join(f"{p} (written by {owners[p]})" for p in bad_outputs[:5])
            shown += " ..." if len(bad_outputs) > 5 else ""
            return ("refuse", f"output_inventory_mismatch: {len(bad_outputs)} "
                    f"generated output file(s) missing or modified since the "
                    f"verified run: {shown}; re-run from stage 0 so every "
                    f"stage rebuilds and re-verifies its artifacts")
        shown = ", ".join(bad_inputs[:5]) + (" ..." if len(bad_inputs) > 5 else "")
        return ("refuse", f"input_baseline_mismatch: {len(bad_inputs)} recorded "
                f"input file(s) missing or modified since the verified run "
                f"({shown}); re-run from stage 0")
    return ("allow", "")


def enforce_source_guard(a, cfg, prior, fp):
    """Fail-closed precondition for --resume / --start-from.

    Neither flag may bypass the source PDF SHA-256 / identity / integrity
    checks, so before any stage may be skipped this guard re-verifies the
    source RIGHT NOW and the checkpoint's right to represent it (including
    that the installed toolkit code still hashes to the fingerprint the
    checkpoint recorded).

    Returns ``(action, reason)``:
      ``("allow", "")``    skipping is safe (all checks passed);
      ``("full_run", msg)`` the checkpoint cannot authorize skipping anything
                           (missing / foreign): --resume degrades to a full
                           run from stage 0, --start-from must refuse;
      ``("refuse", msg)``  integrity violation: exit GUARD_EXIT, run nothing.
    """
    # (1) the source PDF must exist and still match the config-pinned values
    if "pdf_sha256" not in fp:
        return ("refuse", "source_pdf_missing: the configured source PDF "
                f"{cfg['paths']['pdf']!r} does not exist; --resume/--start-from "
                "may not skip the stage-0 audit on a missing source")
    src = cfg.get("source", {})
    exp_sha = src.get("expected_pdf_sha256")
    if not exp_sha:
        return ("refuse", "config_must_pin_source_pdf_sha256: this config has no "
                "source.expected_pdf_sha256, so source integrity cannot be "
                "verified on resume; pin the source or re-run from stage 0")
    if fp["pdf_sha256"] != str(exp_sha).lower():
        return ("refuse", "source_pdf_changed: actual PDF SHA-256 "
                f"{fp['pdf_sha256']} != config-pinned {exp_sha}")
    exp_bytes = src.get("expected_bytes")
    if exp_bytes and fp["pdf_bytes"] != exp_bytes:
        return ("refuse", f"source_pdf_changed: actual PDF bytes {fp['pdf_bytes']} "
                f"!= config-pinned {exp_bytes}")
    # (2) a prior checkpoint must exist and belong to THIS config
    if prior is None:
        return ("full_run", "no prior checkpoint found")
    if prior.get("config") != os.path.abspath(a.config):
        return ("full_run", "the prior checkpoint belongs to a different config")
    # (3) fingerprint continuity: the checkpoint must have been produced from
    # the SAME source PDF, config content, pinned upstream tree and engine
    pf = prior.get("source_fingerprint")
    if not isinstance(pf, dict):
        return ("refuse", "stale_checkpoint: the checkpoint predates source-"
                "fingerprint verification (no source_fingerprint recorded); "
                "re-run from stage 0 to re-establish a verified checkpoint")
    for k in _FINGERPRINT_KEYS:
        if pf.get(k) != fp.get(k):
            return ("refuse", f"stale_checkpoint: {k} differs between the "
                    f"checkpoint and the current run (checkpoint={pf.get(k)!r}, "
                    f"current={fp.get(k)!r}); re-run from stage 0")
    # (4) audit identity continuity: the checkpoint must embed an audit summary
    # proving the stage-0 audit verified THIS source PDF and found the identity
    # unambiguous
    au = prior.get("audit")
    if (not isinstance(au, dict) or au.get("verdict") != "AUDIT_COMPLETE"
            or au.get("pdf_sha256") != fp["pdf_sha256"]
            or au.get("identity_ambiguous") is not False):
        return ("refuse", "audit_record_invalid: the checkpoint has no valid "
                "AUDIT_COMPLETE audit summary for the current source PDF "
                f"(recorded: {au!r}); re-run from stage 0")
    # (5) belt-and-braces: when the on-disk audit record exists it must not
    # describe a different source than the one being resumed against
    if os.path.exists(audit_out_path(a)):
        try:
            disk = json.load(open(audit_out_path(a), encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ("refuse", "audit_record_invalid: source-audit.json next to "
                    "the config is unreadable")
        if ((disk.get("pdf") or {}).get("sha256") != fp["pdf_sha256"]
                or disk.get("verdict") != "AUDIT_COMPLETE"):
            return ("refuse", "audit_record_conflicts: source-audit.json was "
                    "produced against a different source PDF or is not "
                    "AUDIT_COMPLETE; re-run from stage 0")
    return ("allow", "")


def stage_commands(a, cfg):
    """Build the ordered (name, argv) plan for this run."""
    py = sys.executable
    # P0-C: the read-only source audit is stage 0 and is enforced BEFORE any
    # build stage: the PDF must exist and match the config's expected
    # SHA-256/bytes (config.source), and must pass the hard BLOCK criteria
    # (encryption, identity ambiguity, marker continuity, unextractable
    # images). A failed audit stops the pipeline with a non-zero exit.
    src = cfg.get("source", {})
    audit_argv = [py, "-m", "certpassly.phase1.audit_source",
                  "--pdf", cfg["paths"]["pdf"]]
    if src.get("expected_pdf_sha256"):
        audit_argv += ["--expected-sha256", src["expected_pdf_sha256"]]
    if src.get("expected_bytes"):
        audit_argv += ["--expected-bytes", str(src["expected_bytes"])]
    audit_argv += ["--out", audit_out_path(a)]
    plan = [("audit_source", audit_argv)]
    plan += [(s, [py, "-m", f"certpassly.phase1.{s}", a.config])
             for s in STAGES if s != "audit_source"]
    if not a.skip_adversarial and a.adversarial_base:
        report_out = os.path.join(cfg["paths"]["out_dir"], "qa", "adversarial-tests.json")
        plan.append((
            "adversarial",
            [py, "-m", "certpassly.phase1.adversarial",
             "--base", a.adversarial_base,
             "--upstream", a.upstream_scripts,
             "--report-out", report_out,
             "--date", datetime.date.today().isoformat()],
        ))
    return plan


def run_stage(name, args, log):
    print(f"--- stage: {name} ---")
    r = subprocess.run(args, capture_output=True, text=True)
    log.append(dict(stage=name, command=" ".join(args), exit_code=r.returncode,
                    tail=(r.stdout + r.stderr)[-600:]))
    print(f"    exit {r.returncode}")
    if r.returncode != 0:
        print((r.stdout + r.stderr)[-1500:])
    return r.returncode


def run_cli(argv=None):
    """CLI entry used by both ``python -m certpassly.phase1.run_all`` and the
    ``certpassly phase1-extract`` subcommand."""
    ap = argparse.ArgumentParser(prog="certpassly.phase1.run_all")
    ap.add_argument("--config", required=True)
    ap.add_argument("--upstream-scripts", required=True)
    ap.add_argument("--adversarial-base")
    ap.add_argument("--skip-adversarial", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the planned stage commands and exit 0 without running")
    ap.add_argument("--resume", action="store_true",
                    help="skip stages that already exited 0 in a prior checkpoint with "
                         "the same config, the same verified source fingerprint, "
                         "all their recorded outputs still intact on disk AND no "
                         "unexpected extra files in the monitored output roots "
                         "(exact file-set inventory); otherwise run everything from "
                         "stage 0 (never skips the source checks or the output-"
                         "inventory verification)")
    ap.add_argument("--start-from", choices=STAGES + ["adversarial"],
                    help="begin at the named stage; requires a verified prior "
                         "checkpoint of this config whose earlier stages all exited 0 "
                         "and whose recorded outputs verify, with no unexpected "
                         "extra files beyond recorded later-stage artifacts that "
                         "will be regenerated (both guards still run; the new "
                         "checkpoint preserves the skipped stages' receipts)")
    a = ap.parse_args(argv)

    cfg = json.load(open(a.config, encoding='utf-8'))
    ckpt_path = os.path.join(os.path.dirname(os.path.abspath(a.config)),
                             "run-checkpoint.json")
    prior = None
    if os.path.exists(ckpt_path):
        try:
            prior = json.load(open(ckpt_path, encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            prior = None

    plan = stage_commands(a, cfg)
    # measured at run START (never mid-run) so the checkpoint records the
    # source that the stage-0 audit of THIS run verified
    fp = source_fingerprint(a, cfg)

    # --start-from must name a planned stage (syntactic check first)
    if a.start_from and a.start_from not in [name for name, _ in plan]:
        print(f"ERROR: --start-from {a.start_from} is not in the planned stages "
              f"(adversarial requires --adversarial-base)", file=sys.stderr)
        return 2

    # ---- source guard: --resume / --start-from cannot bypass the source
    # PDF SHA-256 / identity / integrity checks (director final correction 1) ----
    guard_ok = True
    if a.resume or a.start_from:
        action, reason = enforce_source_guard(a, cfg, prior, fp)
        if a.dry_run:
            print(f"  source guard (dry-run): {action}"
                  + (f" - {reason}" if reason else ""))
        if action == "refuse":
            print(f"ERROR: source guard refused --resume/--start-from: {reason}",
                  file=sys.stderr)
            print("       Nothing was run and the existing checkpoint was left "
                  "untouched. Re-run WITHOUT --resume/--start-from so stage 0 "
                  "re-audits the source.", file=sys.stderr)
            return GUARD_EXIT
        if action == "full_run":
            if a.start_from:
                print(f"ERROR: --start-from {a.start_from} requires a verified prior "
                      f"checkpoint of this config ({reason}); refusing to skip the "
                      f"stage-0 source audit.", file=sys.stderr)
                return GUARD_EXIT
            # --resume with a checkpoint that cannot authorize skipping: run
            # EVERYTHING from stage 0 - the audit re-verifies the source.
            guard_ok = False
            print(f"NOTICE: --resume cannot use this checkpoint ({reason}); "
                  f"running ALL stages from stage 0 - nothing is skipped.")

    # ---- plan which stages --resume / --start-from would SKIP -------------
    # (a stage may only be skipped if it exited 0 in the prior checkpoint of
    # THIS config; the maximal passed prefix of the plan is skippable)
    skip_names = []
    all_done = False
    if a.resume and prior and prior.get("config") == os.path.abspath(a.config):
        passed = {s["stage"] for s in prior.get("stages", [])
                  if isinstance(s, dict) and s.get("exit_code") == 0}
        for name, _ in plan:
            if name in passed:
                skip_names.append(name)
            else:
                break
        all_done = (len(skip_names) == len(plan))
    if a.start_from:
        # prerequisites: every planned stage BEFORE the start stage must have
        # exited 0 in the guard-verified checkpoint
        names = [name for name, _ in plan]
        passed = {s["stage"] for s in prior.get("stages", [])
                  if isinstance(s, dict) and s.get("exit_code") == 0}
        missing = [n for n in names[:names.index(a.start_from)] if n not in passed]
        if missing:
            print(f"ERROR: --start-from {a.start_from}: earlier stage(s) {missing} "
                  f"did not exit 0 in the verified checkpoint; refusing to skip "
                  f"them.", file=sys.stderr)
            return GUARD_EXIT
        skip_names = names[:names.index(a.start_from)]

    # ---- output-inventory guard: before --resume may no-op or any stage may
    # be skipped, every skipped stage's recorded outputs (and the input
    # baseline) are re-hashed and compared, and the monitored output roots
    # are checked as an EXACT file set - a deleted, modified OR UNEXPECTEDLY
    # ADDED question JSON / asset binary / QA report / stray file can never
    # yield a false successful no-op (director final corrections 2 and 3) ----
    if (a.resume or a.start_from) and skip_names and guard_ok:
        vaction, vreason = verify_prior_outputs(a, cfg, prior, plan, skip_names)
        if a.dry_run:
            print(f"  output-inventory guard (dry-run): {vaction}"
                  + (f" - {vreason}" if vreason else ""))
        if vaction == "refuse":
            print(f"ERROR: output-inventory guard refused --resume/--start-from: "
                  f"{vreason}", file=sys.stderr)
            print("       Nothing was run and the existing checkpoint was left "
                  "untouched. Re-run WITHOUT --resume/--start-from so every "
                  "stage rebuilds and re-verifies its artifacts.", file=sys.stderr)
            return GUARD_EXIT
        if vaction == "cannot_verify":
            if a.start_from:
                print(f"ERROR: --start-from {a.start_from}: {vreason}; refusing "
                      f"to skip stages whose artifacts cannot be verified.",
                      file=sys.stderr)
                return GUARD_EXIT
            # --resume cannot verify the recorded artifacts: an explicit FULL
            # rebuild from stage 0 - never a green no-op.
            print(f"NOTICE: --resume cannot verify this checkpoint's artifacts "
                  f"({vreason}); running ALL stages from stage 0 - nothing is "
                  f"skipped.")
            skip_names, all_done = [], False

    if a.dry_run:
        print("=== run_all DRY RUN (no stages executed) ===")
        for name, args in plan:
            note = "  [verified: would skip]" if name in skip_names else ""
            print(f"  [plan] {name}: {' '.join(args)}{note}")
        if prior:
            print(f"  prior checkpoint: overall_exit={prior.get('overall_exit')} "
                  f"finished={prior.get('finished')}")
        print(f"checkpoint file (not written in dry-run): {ckpt_path}")
        return 0

    if all_done:
        print("=== run_all resume: every stage already complete and every recorded "
              f"output verified against the checkpoint ({ckpt_path}); nothing to "
              f"do ===")
        return 0

    # ---- run the planned stages, skipping only the VERIFIED ones ----------
    base_snap = snapshot_outputs(a, cfg)  # input baseline at run START
    snap = dict(base_snap)
    skip = set(skip_names)
    # director final correction 3 (P1): the new checkpoint must carry the
    # COMPLETE ordered stage list. The verified skipped stages' receipts
    # (exit status + output inventories, both re-verified by the guards
    # above this run) are carried into the new checkpoint and merged with
    # the freshly executed stages - each stage exactly once, in plan order,
    # no double-counting - so later resumes keep full traceability and
    # partial resumes can chain instead of silently losing the right to
    # skip the stages that were already verified.
    prior_entries = {}
    if prior:
        for s in prior.get("stages", []):
            if isinstance(s, dict) and s.get("stage"):
                prior_entries[s["stage"]] = s  # last record of a stage wins
    log, rc = [], 0
    for name, args in plan:
        if name in skip:
            carried = dict(prior_entries.get(name) or {})
            carried["stage"] = name
            carried["skipped_this_run"] = True  # receipt preserved, not re-run
            log.append(carried)
            print(f"--- stage: {name} --- skipped (--start-from/--resume; "
                  "recorded outputs verified; receipt preserved in the "
                  "new checkpoint)")
            continue
        if rc == 0:
            rc |= run_stage(name, args, log)
            if (log and isinstance(log[-1], dict) and log[-1].get("stage") == name
                    and log[-1].get("exit_code") == 0):
                # persist what this stage actually wrote (deterministic
                # inventory: exact generated file paths + SHA-256)
                after = snapshot_outputs(a, cfg)
                log[-1]["outputs"] = _stage_delta(snap, after)
                snap = after
        else:
            log.append(dict(stage=name, command=" ".join(args), exit_code=None,
                            tail="not run: an earlier stage failed"))

    out = dict(config=os.path.abspath(a.config), finished=datetime.datetime.now().isoformat(timespec="seconds"),
               overall_exit=rc, stages=log,
               engine=ENGINE_LABEL,
               source_fingerprint=fp,
               audit=read_audit_summary(a),
               resume=bool(a.resume), start_from=a.start_from or None,
               inventory_version=INVENTORY_VERSION,
               input_baseline=_inv_entries(base_snap))
    with open(ckpt_path, "w", encoding='utf-8') as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"=== run_all overall exit {rc} (checkpoint: {ckpt_path}) ===")
    return rc


if __name__ == "__main__":
    sys.exit(run_cli())
