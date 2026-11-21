#!/usr/bin/env python3
"""Run the three-phase CertPassly path in a private workspace.

Phase 1: pinned upstream technical stages (no AI, no web).
Phase 2: research worklist, plus official-source capture only when a URL is already known and --capture-official is set.
Phase 3: domain mapping, content gate, required local site importer gate before promotion, optional promotion.

Prints a public-safe counts summary only. Held reasons and question text stay
in the raw-exam reports, not in the printed summary.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent

PRIVATE_LOG: Path | None = None


def run_cmd(cmd: list[str], cwd: Path | None = None, allowed: tuple[int, ...] = (0,)) -> int:
    if PRIVATE_LOG is not None:
        PRIVATE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with PRIVATE_LOG.open("a", encoding="utf-8") as fh:
            fh.write("$ %s\n" % " ".join(str(c) for c in cmd))
            result = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, check=False)
    else:
        result = subprocess.run(cmd, cwd=cwd, check=False)
    if result.returncode not in allowed:
        print("run_three_phase_failed exit=%s" % result.returncode)
        raise SystemExit(result.returncode)
    return result.returncode


def run(cmd: list[str], cwd: Path | None = None) -> None:
    run_cmd(cmd, cwd=cwd, allowed=(0,))


def site_file(workspace: Path, exam: str) -> Path:
    out = workspace / "out" / exam
    for cand in (out / f"{exam}.site-format.v2.json", out / "export" / f"{exam}.site-format.v2.json"):
        if cand.is_file():
            return cand
    raise SystemExit(f"ERROR: site v2 file not found under {out}")


def export_dir(workspace: Path, exam: str) -> Path:
    out = workspace / "out" / exam
    if (out / "export").is_dir():
        return out / "export"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exam", required=True)
    ap.add_argument("--workspace", required=True, type=Path)
    ap.add_argument("--upstream", required=True, type=Path)
    ap.add_argument("--raw-dir", type=Path)
    ap.add_argument("--exam-links", type=Path)
    ap.add_argument("--ready-root", type=Path)
    ap.add_argument("--raw-commit", default="")
    ap.add_argument("--sandbox", type=Path, help="Site import sandbox (copy of a3009daa5). Optional.")
    ap.add_argument("--capture-official", action="store_true")
    ap.add_argument("--promote", action="store_true")
    ap.add_argument(
        "--private-log",
        type=Path,
        help="Capture child command output here and print only counts. Used on the public runner.",
    )
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args(argv)
    global PRIVATE_LOG
    env_log = (os.environ.get("CERTPASSLY_PRIVATE_LOG") or "").strip()
    if args.private_log:
        PRIVATE_LOG = Path(args.private_log).resolve()
    elif env_log:
        PRIVATE_LOG = Path(env_log).resolve()
    else:
        PRIVATE_LOG = None
    ws = args.workspace.resolve()
    exam = args.exam
    if args.raw_dir:
        prep = [args.python, str(HERE / "prepare_exam_workspace.py"),
                "--raw-dir", str(args.raw_dir), "--workspace", str(ws),
                "--exam", exam]
        if args.exam_links:
            prep.extend(["--exam-links", str(args.exam_links)])
        example = args.upstream.resolve() / "config" / "pipeline.example.yaml"
        if example.is_file():
            prep.extend(["--pipeline-example", str(example)])
        run(prep)
    pipeline = args.upstream.resolve() / "scripts" / "run_pipeline.py"
    if not pipeline.is_file():
        print(f"ERROR: upstream runner missing: {pipeline}", file=sys.stderr)
        return 2
    run([args.python, str(pipeline), "--root", str(ws), "--exam", exam, "--offline"], cwd=ws)
    exp = export_dir(ws, exam)
    site = site_file(ws, exam)
    reports = ws / "out" / exam / "phase-reports"
    reports.mkdir(parents=True, exist_ok=True)
    worklist = reports / "research-worklist.json"
    run([args.python, str(HERE / "build_research_worklist.py"),
         "--exam", exam, "--export-dir", str(exp), "--output", str(worklist)])
    domain_report = reports / "domain-mapping.json"
    run_cmd([args.python, str(HERE / "map_exam_domains.py"),
             "--site-file", str(site), "--output", str(domain_report)]
            + (["--raw-dir", str(args.raw_dir)] if args.raw_dir else [])
            + (["--workspace", str(ws)] if ws else []), allowed=(0, 2))
    content = reports / "content-gate.json"
    # Content gate is allowed to exit 2; we still write promotion decision.
    run_cmd([args.python, str(HERE / "check_content_gate.py"),
             "--site-file", str(site), "--output", str(content)], allowed=(0, 2))
    import_report = reports / "import-gate.json"
    if args.sandbox:
        run_cmd([args.python, str(HERE / "run_site_import_gate.py"),
                 "--sandbox", str(args.sandbox), "--site-file", str(site),
                 "--output", str(import_report)], allowed=(0, 2))
    promote_out = reports / "promotion.json"
    promote_cmd = [args.python, str(HERE / "promote_ready_exam.py"),
                   "--exam", exam, "--site-file", str(site),
                   "--ready-root", str(args.ready_root or (ws / "ready-exams-dry")),
                   "--raw-commit", args.raw_commit or ("0" * 40),
                   "--worklist", str(worklist), "--content-gate", str(content),
                   "--domain-gate", str(domain_report),
                   "--output", str(promote_out)]
    if import_report.is_file():
        promote_cmd.extend(["--import-gate", str(import_report)])
    if args.promote:
        promote_cmd.append("--promote")
    run_cmd(promote_cmd, allowed=(0, 2))
    work = json.loads(worklist.read_text(encoding="utf-8"))
    content_data = json.loads(content.read_text(encoding="utf-8")) if content.is_file() else {}
    promo = json.loads(promote_out.read_text(encoding="utf-8")) if promote_out.is_file() else {}
    imported = json.loads(import_report.read_text(encoding="utf-8")) if import_report.is_file() else {}
    blockers = promo.get("blockers") or []
    summary = {
        "exam_code": exam,
        "exported_question_count": work.get("exported_question_count"),
        "held_count": len(work.get("held") or []),
        "answer_not_found_count": len(work.get("answer_not_found") or []),
        "missing_exam_facts_count": len(work.get("missing_exam_facts") or []),
        "content_gate": content_data.get("status"),
        "domain_mapping": (json.loads(domain_report.read_text(encoding="utf-8")) if domain_report.is_file() else {}).get("status"),
        "domain_unmapped_count": (json.loads(domain_report.read_text(encoding="utf-8")) if domain_report.is_file() else {}).get("unmapped_count"),
        "import_gate": imported.get("status"),
        "import_created": imported.get("created_count"),
        "import_rejected": imported.get("rejected_count"),
        "promotion": promo.get("status"),
        "promotion_blocker_count": len(blockers),
        "promotion_blockers": blockers,
    }
    (reports / "public-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    # Printed log: counts and pass/fail only. No held reasons, stems, or paths.
    printed = {k: v for k, v in summary.items() if k != "promotion_blockers"}
    print(json.dumps(printed, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
