#!/usr/bin/env python3
"""Verify that all listed reusable skill tools and tests exist and are safe to index."""
from __future__ import annotations
import argparse
import json
from pathlib import Path, PurePosixPath
import sys


def validate(root: Path, data: dict) -> list[str]:
    problems: list[str] = []
    tools = data.get("tools")
    if data.get("schema_version") != 1 or not isinstance(tools, list) or not tools:
        return ["registry version or tools list invalid"]
    seen_ids, seen_paths = set(), set()
    if data.get("rules", {}).get("no_auto_promotion") is not True:
        problems.append("registry must explicitly forbid auto promotion")
    if data.get("rules", {}).get("independent_reviewer_required") is not True:
        problems.append("registry must preserve reviewer gate")
    for tool in tools:
        if not isinstance(tool, dict):
            problems.append("tool must be an object")
            continue
        identifier = tool.get("id")
        if not isinstance(identifier, str) or not identifier:
            problems.append("tool ID missing")
            continue
        if identifier in seen_ids:
            problems.append(f"duplicate tool ID: {identifier}")
        seen_ids.add(identifier)
        for key, seen in (("path", seen_paths), ("test", None)):
            value = tool.get(key)
            if not isinstance(value, str) or not value:
                problems.append(f"{identifier}: {key} path missing")
                continue
            p = PurePosixPath(value)
            if p.is_absolute() or ".." in p.parts or "\\" in value:
                problems.append(f"{identifier}: unsafe {key} path")
                continue
            if key == "test" and (not value.startswith("tests/") or not value.endswith(".py")):
                problems.append(f"{identifier}: test must be a Python regression test")
            if key == "path":
                if value in seen:
                    problems.append(f"duplicate tool path: {value}")
                seen.add(value)
            if not (root / value).is_file():
                problems.append(f"{identifier}: missing {key} at {value}")
        for key in ("command", "dependencies", "side_effects", "owner", "scope"):
            if not isinstance(tool.get(key), str) or not tool[key].strip():
                problems.append(f"{identifier}: missing {key} description")
        if tool.get("release_authority") is not False:
            problems.append(f"{identifier}: shared tool cannot grant release authority")
        if tool.get("scope") != "shared":
            problems.append(f"{identifier}: non-shared tool is wrongly in public registry")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--registry", default="config/tool-registry.json")
    args = ap.parse_args(argv)
    try:
        root = args.root.resolve()
        filename = (root / args.registry).resolve()
        if not filename.is_relative_to(root):
            raise ValueError("registry path escapes repository")
        errors = validate(root, json.loads(filename.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
    print(json.dumps({"status": "fail" if errors else "pass", "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
