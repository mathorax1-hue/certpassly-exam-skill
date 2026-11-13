"""Human- and MCP-friendly CLI for CertPassly Skill MVP."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .checkpoints import Checkpoints
from .doctor import inspect
from .evidence import audit_file
from .pipeline import PlanError, run_plan
from .upstream import STAGE_NAMES, run_upstream


def _phase1_info() -> int:
    """Print Phase 1 extraction toolkit version/compatibility metadata."""
    from . import phase1
    print(json.dumps({
        "toolkit": phase1.TOOLKIT_NAME,
        "toolkit_version": phase1.TOOLKIT_VERSION,
        "structured_schema_version": phase1.STRUCTURED_SCHEMA_VERSION,
        "schema_compatible_extensions": list(phase1.SCHEMA_COMPATIBLE_EXTENSIONS),
        "upstream_repo": phase1.UPSTREAM_REPO,
        "upstream_pin": phase1.UPSTREAM_PIN,
        "network_access": "none (strictly local; no upload/publication behavior)",
        "release_authority": False,
    }, indent=2))
    return 0


def _phase1_audit(argv: list[str]) -> int:
    """Read-only source PDF audit; requires the 'pdf' extra (PyMuPDF)."""
    try:
        from .phase1 import audit_source
    except ImportError as exc:
        print(f"ERROR: phase1-audit requires the pdf extra (PyMuPDF): {exc}", file=sys.stderr)
        return 3
    return audit_source.run_audit(argv)


def _phase1_extract(argv: list[str]) -> int:
    """Deterministic stage/resume orchestrator for one exam config."""
    from .phase1 import run_all
    return run_all.run_cli(argv)



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="certpassly", description="CertPassly Exam Skill orchestration")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    doctor = sub.add_parser("doctor", help="Check installation and optional tools")
    doctor.add_argument("--json", action="store_true")
    run = sub.add_parser("run", help="Run or resume trusted local workflow stages")
    run.add_argument("--root", default=".")
    run.add_argument("--plan", default="config/pipeline.example.json")
    run.add_argument("--state-dir", default=".certpassly")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--force", action="store_true")
    status = sub.add_parser("status", help="Show checkpoint state")
    status.add_argument("--state-dir", default=".certpassly")
    verify = sub.add_parser("verify-evidence", help="Audit structural evidence and visual safety")
    verify.add_argument("--input", required=True)
    verify.add_argument("--output")
    verify.add_argument("--strict", action="store_true", help="Exit nonzero if any blocker")
    upstream = sub.add_parser("upstream-run", help="Use an approved external upstream checkout in a private workspace")
    upstream.add_argument("--checkout", required=True, help="Path to pinned upstream checkout")
    upstream.add_argument("--private-root", required=True, help="Private owner-exam workspace")
    upstream.add_argument("--exam", required=True)
    upstream.add_argument("--stage", choices=STAGE_NAMES, action="append", required=True)
    upstream.add_argument("--online", action="store_true", help="Opt into network retrieval (offline by default)")
    upstream.add_argument("--dry-run", action="store_true")
    p1info = sub.add_parser("phase1-info", help="Phase 1 extraction toolkit version/compatibility metadata")
    p1audit = sub.add_parser("phase1-audit", help="Read-only source PDF audit (identity/integrity gate)")
    p1audit.add_argument("--pdf", required=True)
    p1audit.add_argument("--expected-sha256")
    p1audit.add_argument("--expected-bytes", type=int)
    p1audit.add_argument("--marker-regex")
    p1audit.add_argument("--answer-regex")
    p1audit.add_argument("--tool-label")
    p1audit.add_argument("--out")
    p1extract = sub.add_parser("phase1-extract", help="Run the Phase 1 stage pipeline for one exam config")
    p1extract.add_argument("--config", required=True)
    p1extract.add_argument("--upstream-scripts", required=True)
    p1extract.add_argument("--adversarial-base")
    p1extract.add_argument("--skip-adversarial", action="store_true")
    p1extract.add_argument("--dry-run", action="store_true")
    p1extract.add_argument("--resume", action="store_true")
    p1extract.add_argument("--start-from")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "doctor":
            report = inspect()
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                print(f"Python {report['python']['version']}: {'OK' if report['python']['ready'] else 'REQUIRES 3.11+'}")
                for name, entry in report["tools"].items():
                    print(f"{name}: {'installed' if entry['installed'] else 'missing (optional or stage-specific)'}")
            return 0 if report["python"]["ready"] else 2
        if args.cmd == "run":
            root = Path(args.root).resolve()
            plan = (root / args.plan).resolve()
            state = (root / args.state_dir).resolve()
            results = run_plan(root, plan, state, args.dry_run, args.force)
            print(json.dumps({"results": results}, indent=2))
            return 2 if any(x["action"].startswith(("failed", "blocked")) for x in results) else 0
        if args.cmd == "status":
            path = Path(args.state_dir).resolve() / "checkpoints.sqlite3"
            if not path.is_file():
                print(json.dumps({"stages": [], "message": "No stages run yet"}, indent=2))
                return 0
            with Checkpoints(path) as cp:
                print(json.dumps({"stages": cp.list()}, indent=2))
            return 0
        if args.cmd == "upstream-run":
            root = Path(__file__).resolve().parents[2]
            report = run_upstream(root, Path(args.checkout), Path(args.private_root),
                                  args.exam, args.stage, not args.online, args.dry_run)
            print(json.dumps(report, indent=2))
            return 0 if report["status"] != "failed" else 2
        if args.cmd == "verify-evidence":
            report = audit_file(Path(args.input))
            serial = json.dumps(report, indent=2) + "\n"
            if args.output:
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(serial, encoding="utf-8")
            print(serial.rstrip())
            return 2 if args.strict and report["status"] == "blocked" else 0
        if args.cmd == "phase1-info":
            return _phase1_info()
        if args.cmd == "phase1-audit":
            argv = ["--pdf", args.pdf]
            if args.expected_sha256:
                argv += ["--expected-sha256", args.expected_sha256]
            if args.expected_bytes is not None:
                argv += ["--expected-bytes", str(args.expected_bytes)]
            if args.marker_regex:
                argv += ["--marker-regex", args.marker_regex]
            if args.answer_regex:
                argv += ["--answer-regex", args.answer_regex]
            if args.tool_label:
                argv += ["--tool-label", args.tool_label]
            if args.out:
                argv += ["--out", args.out]
            return _phase1_audit(argv)
        if args.cmd == "phase1-extract":
            argv = ["--config", args.config, "--upstream-scripts", args.upstream_scripts]
            if args.adversarial_base:
                argv += ["--adversarial-base", args.adversarial_base]
            if args.skip_adversarial:
                argv += ["--skip-adversarial"]
            if args.dry_run:
                argv += ["--dry-run"]
            if args.resume:
                argv += ["--resume"]
            if args.start_from:
                argv += ["--start-from", args.start_from]
            return _phase1_extract(argv)
    except (ValueError, OSError, json.JSONDecodeError, PlanError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
