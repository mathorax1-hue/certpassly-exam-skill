"""Resumable local executor for explicitly versioned, trusted stage configurations.

No shell expansion, remote execution, GitHub writes, or automatic releases.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .checkpoints import Checkpoints, digest_json, sha256_file


@dataclass(frozen=True)
class Stage:
    name: str
    command: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    needs: tuple[str, ...]
    timeout_seconds: int


class PlanError(ValueError):
    pass


def inside(root: Path, raw: str) -> Path:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise PlanError("invalid path")
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts or ".git" in rel.parts:
        raise PlanError(f"unsafe workspace path: {raw}")
    target = (root / rel).resolve()
    if not target.is_relative_to(root.resolve()):
        raise PlanError(f"path leaves workspace: {raw}")
    return target


def load_plan(root: Path, plan_path: Path) -> list[Stage]:
    if not plan_path.resolve().is_relative_to(root.resolve()):
        raise PlanError("plan must be inside workspace")
    doc = json.loads(plan_path.read_text(encoding="utf-8"))
    if doc.get("schema_version") != 1 or not isinstance(doc.get("stages"), list):
        raise PlanError("unsupported plan schema")
    stages: list[Stage] = []
    known: set[str] = set()
    for item in doc["stages"]:
        if not isinstance(item, dict):
            raise PlanError("stage must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name or not all(x.isalnum() or x in "_-" for x in name):
            raise PlanError("invalid stage name")
        if name in known:
            raise PlanError(f"duplicate stage: {name}")
        command, inputs, outputs, needs = (item.get(k, []) for k in ("command", "inputs", "outputs", "needs"))
        if not isinstance(command, list) or not command or any(not isinstance(x, str) or not x for x in command):
            raise PlanError(f"invalid command for {name}")
        if not all(isinstance(xs, list) and all(isinstance(v, str) for v in xs)
                   for xs in (inputs, outputs, needs)):
            raise PlanError(f"invalid input, output, or dependency for {name}")
        if any(dep not in known for dep in needs):
            raise PlanError(f"{name} dependencies must be earlier stages")
        for p in (*inputs, *outputs):
            inside(root, p)
        timeout = item.get("timeout_seconds", 300)
        if not isinstance(timeout, int) or not 1 <= timeout <= 3600:
            raise PlanError("timeout must be an integer from 1 to 3600")
        stages.append(Stage(name, tuple(command), tuple(inputs), tuple(outputs), tuple(needs), timeout))
        known.add(name)
    if not stages:
        raise PlanError("plan has no stages")
    return stages


def _output_hashes(root: Path, stage: Stage) -> dict[str, str] | None:
    result = {}
    for raw in stage.outputs:
        file = inside(root, raw)
        if not file.is_file():
            return None
        result[raw] = sha256_file(file)
    return result


def _fingerprint(root: Path, stage: Stage, deps: dict[str, dict]) -> str:
    items = {}
    for raw in stage.inputs:
        p = inside(root, raw)
        if not p.is_file():
            raise PlanError(f"missing stage input {raw!r} for {stage.name}")
        items[raw] = sha256_file(p)
    return digest_json({"stage": stage.__dict__, "inputs": items, "dependencies": deps,
                        "runner_version": __version__})


def run_plan(root: Path, plan_path: Path, state_dir: Path, dry_run: bool = False,
             force: bool = False) -> list[dict]:
    root = root.resolve()
    stages = load_plan(root, plan_path)
    if not state_dir.resolve().is_relative_to(root):
        raise PlanError("state directory must be within workspace")
    report = []
    with Checkpoints(state_dir / "checkpoints.sqlite3") as db:
        for stage in stages:
            deps = {}
            for name in stage.needs:
                entry = db.get(name)
                if entry is None or entry["status"] != "passed":
                    if dry_run:
                        deps[name] = {"status": "unavailable"}
                        continue
                    raise PlanError(f"dependency {name} has not passed")
                deps[name] = {"fingerprint": entry["fingerprint"], "outputs": entry["output_hashes"]}
            try:
                fp = _fingerprint(root, stage, deps)
            except PlanError:
                if dry_run:
                    report.append({"stage": stage.name, "action": "blocked_missing_input"})
                    continue
                raise
            old = db.get(stage.name)
            current_outputs = _output_hashes(root, stage)
            cache_hit = (not force and old is not None and old["status"] == "passed"
                         and old["fingerprint"] == fp and current_outputs is not None
                         and old["output_hashes"] == current_outputs)
            if cache_hit:
                report.append({"stage": stage.name, "action": "cached"})
                continue
            if dry_run:
                report.append({"stage": stage.name, "action": "would_run"})
                continue
            for raw in stage.outputs:
                inside(root, raw).parent.mkdir(parents=True, exist_ok=True)
            command = [sys.executable if x == "{python}" else x for x in stage.command]
            log_dir = state_dir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            start = time.monotonic()
            env = os.environ.copy()
            env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            try:
                result = subprocess.run(command, cwd=root, env=env, text=True,
                                        capture_output=True, timeout=stage.timeout_seconds,
                                        check=False)
                elapsed = round(time.monotonic() - start, 3)
                # Logs may contain source material. Never add the state directory to git.
                (log_dir / (stage.name + ".log")).write_text(
                    result.stdout + "\n--- stderr ---\n" + result.stderr, encoding="utf-8")
                outputs = _output_hashes(root, stage)
                if result.returncode != 0 or outputs is None:
                    reason = f"exit={result.returncode}; outputs_present={outputs is not None}"
                    db.record(stage.name, fp, "failed", {}, elapsed, reason)
                    report.append({"stage": stage.name, "action": "failed", "reason": reason})
                    break
                db.record(stage.name, fp, "passed", outputs, elapsed)
                report.append({"stage": stage.name, "action": "executed", "duration_seconds": elapsed})
            except subprocess.TimeoutExpired:
                elapsed = round(time.monotonic() - start, 3)
                db.record(stage.name, fp, "failed", {}, elapsed, "timeout")
                report.append({"stage": stage.name, "action": "failed", "reason": "timeout"})
                break
    return report
