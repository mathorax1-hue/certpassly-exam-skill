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
    except (ValueError, OSError, json.JSONDecodeError, PlanError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
