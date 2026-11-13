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
    integrity checks (director final correction, 2026-11-13). Before any stage
    may be skipped a fail-closed SOURCE GUARD re-verifies, at resume time:
    (1) the source PDF exists right now and still hashes to the config-pinned
    expected_pdf_sha256 / expected_bytes; (2) the prior checkpoint belongs to
    this config, carries the SAME source_fingerprint (actual PDF sha256+bytes,
    config content sha256, pinned upstream scripts tree hash, engine label)
    and an AUDIT_COMPLETE / non-identity-ambiguous audit summary; and (3) for
    --start-from, every earlier planned stage exited 0 in that verified
    checkpoint. A guard refusal exits 3 (GUARD_REFUSED) without running any
    stage and without overwriting the existing checkpoint; the operator must
    re-run from stage 0 so the full audit re-verifies the source. --resume with
    a missing or foreign checkpoint cannot authorize skipping anything and
    degrades to a FULL run from stage 0 (loud notice, audit re-runs);
  - --start-from <stage>: begin at a named stage (stage names as listed above)
    - only over a verified prior checkpoint with all earlier stages passed;
  - --dry-run: print the planned stage commands without executing anything
    (the source guard still runs and reports its verdict for --resume /
    --start-from so a would-be refusal is visible without side effects);
  - stops at the first non-zero stage and records it in the checkpoint
    (audit BLOCK exit 2, validation/reconciliation failures exit 1, and -
    since the P0-1 correction - visual_qa MACHINE VISIBILITY FAILURE exit 2);
  - writes a per-stage checkpoint log next to the config (run-checkpoint.json)
    that includes the verified source_fingerprint and the audit summary read
    back from the stage-0 audit record.

Exit codes: 0 = all stages passed; 1/2 = a stage failed (propagated);
3 = source-guard refusal (--resume / --start-from integrity precondition).

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
GUARD_EXIT = 3  # distinct, documented refusal code for the source guard

# fingerprint components compared between the prior checkpoint and the
# current run; every component must match exactly for skipping to be allowed.
_FINGERPRINT_KEYS = (
    "pdf_sha256", "pdf_bytes", "pdf_path",
    "config_sha256", "upstream_scripts", "upstream_tree_sha256",
    "engine",
)


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_sha256(root):
    """Stable content hash of a scripts tree: sorted relative paths + bytes of
    every ``*.py`` file (the pinned upstream extractor is pure Python). Used so
    that swapping the pinned upstream scripts invalidates --resume/--start-from
    even when the PDF and config are untouched."""
    h = hashlib.sha256()
    if not os.path.isdir(root):
        return h.hexdigest()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            h.update(os.path.relpath(p, root).encode("utf-8"))
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()


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
    files at run start - never from the checkpoint or any cached value)."""
    pdf = cfg["paths"]["pdf"]
    fp = dict(
        config_sha256=_file_sha256(a.config),
        pdf_path=os.path.abspath(pdf),
        upstream_scripts=os.path.abspath(a.upstream_scripts),
        upstream_tree_sha256=_tree_sha256(a.upstream_scripts),
        engine=ENGINE_LABEL,
    )
    if os.path.isfile(pdf):
        fp["pdf_sha256"] = _file_sha256(pdf)
        fp["pdf_bytes"] = os.path.getsize(pdf)
    return fp


def enforce_source_guard(a, cfg, prior, fp):
    """Fail-closed precondition for --resume / --start-from.

    Neither flag may bypass the source PDF SHA-256 / identity / integrity
    checks, so before any stage may be skipped this guard re-verifies the
    source RIGHT NOW and the checkpoint's right to represent it.

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
                         "the same config AND the same verified source fingerprint; "
                         "otherwise run everything from stage 0 (never skips the "
                         "source checks)")
    ap.add_argument("--start-from", choices=STAGES + ["adversarial"],
                    help="begin at the named stage; requires a verified prior "
                         "checkpoint of this config whose earlier stages all "
                         "exited 0 (the source guard still re-verifies the PDF)")
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
    # PDF SHA-256 / identity / integrity checks (director final correction) ----
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
            print(f"NOTICE: --resume cannot use this checkpoint ({reason}); "
                  f"running ALL stages from stage 0 - nothing is skipped.")

    if a.dry_run:
        print("=== run_all DRY RUN (no stages executed) ===")
        for name, args in plan:
            print(f"  [plan] {name}: {' '.join(args)}")
        if prior:
            print(f"  prior checkpoint: overall_exit={prior.get('overall_exit')} "
                  f"finished={prior.get('finished')}")
        print(f"checkpoint file (not written in dry-run): {ckpt_path}")
        return 0

    # --resume: stages with exit 0 in a prior GUARD-VERIFIED run of the SAME
    # config are skipped up to the first stage that did not pass.
    skip_until = None
    all_done = False
    if a.resume and prior and prior.get("config") == os.path.abspath(a.config):
        passed = [s["stage"] for s in prior.get("stages", []) if s.get("exit_code") == 0]
        seen_failed = False
        for name, _ in plan:
            if name in passed and not seen_failed:
                continue
            if name not in passed:
                seen_failed = True
            skip_until = name
            break
        else:
            all_done = True
    if a.start_from:
        # prerequisites: every planned stage BEFORE the start stage must have
        # exited 0 in the guard-verified checkpoint
        names = [name for name, _ in plan]
        passed = {s["stage"] for s in prior.get("stages", [])
                  if s.get("exit_code") == 0}
        missing = [n for n in names[:names.index(a.start_from)] if n not in passed]
        if missing:
            print(f"ERROR: --start-from {a.start_from}: earlier stage(s) {missing} "
                  f"did not exit 0 in the verified checkpoint; refusing to skip "
                  f"them.", file=sys.stderr)
            return GUARD_EXIT
        skip_until = a.start_from
        all_done = False

    if all_done:
        print("=== run_all resume: every stage already complete (checkpoint "
              f"{ckpt_path}); nothing to do ===")
        return 0

    log, rc, started = [], 0, False
    for name, args in plan:
        if skip_until and not started:
            if name != skip_until:
                print(f"--- stage: {name} --- skipped (--start-from/--resume)")
                continue
            started = True
        if rc == 0:
            rc |= run_stage(name, args, log)
        else:
            log.append(dict(stage=name, command=" ".join(args), exit_code=None,
                            tail="not run: an earlier stage failed"))

    out = dict(config=os.path.abspath(a.config), finished=datetime.datetime.now().isoformat(timespec="seconds"),
               overall_exit=rc, stages=log,
               engine=ENGINE_LABEL,
               source_fingerprint=fp,
               audit=read_audit_summary(a),
               resume=bool(a.resume), start_from=a.start_from or None)
    with open(ckpt_path, "w", encoding='utf-8') as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"=== run_all overall exit {rc} (checkpoint: {ckpt_path}) ===")
    return rc


if __name__ == "__main__":
    sys.exit(run_cli())
