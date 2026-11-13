#!/usr/bin/env python3
"""Phase 1 extraction: stage orchestrator with checkpoints (public toolkit).

Usage: python -m certpassly.phase1.run_all --config <config.json>
                  --upstream-scripts <dir>
                  [--adversarial-base <scratch>] [--skip-adversarial]
                  [--dry-run] [--resume] [--start-from <stage>]

Runs, in order: build_structured_v1, build_exports, make_source_manifest,
validate_structured_v1, reconcile, visual_qa, adversarial (optional).

Behavior:
  - deterministic: every stage is idempotent; re-running the whole sequence with
    the same config, pinned upstream checkout and source PDF reproduces the
    same outputs byte-identically (this is the canonical "resume" mode);
  - --resume: skip stages that already exited 0 in a previous checkpoint run
    with the SAME config file (recorded by path) and are followed by no failed
    stage; resume at the first incomplete/failed stage otherwise;
  - --start-from <stage>: begin at a named stage (stage names as listed above);
  - --dry-run: print the planned stage commands without executing anything;
  - stops at the first non-zero stage and records it in the checkpoint;
  - writes a per-stage checkpoint log next to the config (run-checkpoint.json).

Stages run via ``python -m certpassly.phase1.<stage>`` so the installed (or
PYTHONPATH-visible) public skill package is the engine; there is no private
duplicate of the generic code.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, datetime

STAGES = [
    "build_structured_v1",
    "build_exports",
    "make_source_manifest",
    "validate_structured_v1",
    "reconcile",
    "visual_qa",
]


def stage_commands(a, cfg):
    """Build the ordered (name, argv) plan for this run."""
    py = sys.executable
    plan = [(s, [py, "-m", f"certpassly.phase1.{s}", a.config]) for s in STAGES]
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
                         "the same config; continue from the first non-completed stage")
    ap.add_argument("--start-from", choices=STAGES + ["adversarial"],
                    help="begin at the named stage (earlier stages must already be complete)")
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

    if a.dry_run:
        print("=== run_all DRY RUN (no stages executed) ===")
        for name, args in plan:
            print(f"  [plan] {name}: {' '.join(args)}")
        if prior:
            print(f"  prior checkpoint: overall_exit={prior.get('overall_exit')} "
                  f"finished={prior.get('finished')}")
        print(f"checkpoint file (not written in dry-run): {ckpt_path}")
        return 0

    # --resume: stages with exit 0 in a prior run of the SAME config path are
    # skipped up to the first stage that did not pass.
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
        skip_until = a.start_from
        all_done = False
        if a.start_from not in [name for name, _ in plan]:
            print(f"ERROR: --start-from {a.start_from} is not in the planned stages "
                  f"(adversarial requires --adversarial-base)", file=sys.stderr)
            return 2

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
               engine="certpassly.phase1 (public certpassly-exam-skill)",
               resume=bool(a.resume), start_from=a.start_from or None)
    with open(ckpt_path, "w", encoding='utf-8') as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"=== run_all overall exit {rc} (checkpoint: {ckpt_path}) ===")
    return rc


if __name__ == "__main__":
    sys.exit(run_cli())
