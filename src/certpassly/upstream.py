"""Invoke an independently checked-out, pinned upstream pipeline.

No upstream files are vendored into this repository. Runtime exam data stays
in the operator's private workspace.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from .pipeline import PlanError

STAGE_NAMES = (
    "catalog", "intake", "sources", "research", "extract", "textfix",
    "answer_research", "intent", "author", "pages", "writing",
    "import", "bank", "validate", "package",
)
CODE = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]{1,39}$")


def expected_pin(skill_root: Path) -> str:
    config = json.loads((skill_root / "config/repositories.json").read_text(encoding="utf-8"))
    pin = config["upstream"]["reviewed_commit"]
    if not re.fullmatch(r"[a-f0-9]{40}", pin):
        raise PlanError("upstream commit pin is not a full SHA")
    return pin


def upstream_command(skill_root: Path, checkout: Path, private_root: Path,
                     exam_code: str, stages: list[str], offline: bool = True) -> list[str]:
    if not CODE.fullmatch(exam_code):
        raise PlanError("invalid exam code")
    if any(x not in STAGE_NAMES for x in stages):
        raise PlanError("unknown upstream stage")
    script = checkout.resolve() / "scripts" / "run_pipeline.py"
    if not script.is_file() or not private_root.resolve().is_dir():
        raise PlanError("missing upstream script or private workspace")
    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=False)
    if head.returncode != 0 or head.stdout.strip() != expected_pin(skill_root):
        raise PlanError("upstream checkout is not at the approved commit SHA")
    command = [sys.executable, str(script), "--root", str(private_root.resolve()), "--exam", exam_code]
    for stage in stages:
        command.extend(["--stage", stage])
    if offline:
        command.append("--offline")
    return command


def run_upstream(skill_root: Path, checkout: Path, private_root: Path,
                 exam_code: str, stages: list[str], offline: bool, dry_run: bool) -> dict:
    command = upstream_command(skill_root, checkout, private_root, exam_code, stages, offline)
    if dry_run:
        return {"status": "dry_run", "stages": stages, "exam_code": exam_code,
                "upstream_sha": expected_pin(skill_root), "offline": offline}
    result = subprocess.run(command, cwd=private_root.resolve(), check=False)
    return {"status": "executed" if result.returncode == 0 else "failed",
            "exit_code": result.returncode, "exam_code": exam_code,
            "upstream_sha": expected_pin(skill_root), "stages": stages}
