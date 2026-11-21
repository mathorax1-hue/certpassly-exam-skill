#!/usr/bin/env python3
"""Phase-3 content gate for authored text only.

Checks explanations and page prose for typographic dashes, emoji, seller or
competitor names, and review markup. Stem and option text from the owner PDF
is not rewritten here. Missing authored content blocks promotion.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DASH_RE = re.compile("[\u2013\u2014\u2015\u2212]")
# Emoji and dingbat ranges; no third-party dependency.
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF\U0000FE0F]"
)
REVIEW_RE = re.compile(
    r"(<!--\s*writing-review:|\[REVIEW\]|\[\[REVIEW\]\]|TODO REVIEW|FIXME REVIEW|<<review>>)",
    re.I,
)
BANNED = (
    "innovior ittech",
    "innoviorittech",
    "innovior",
    "examtopics",
    "examcollection",
    "pass4sure",
    "actualtests",
    "testking",
    "freecram",
)


def _walk_text(node: object, path: str, out: list[tuple[str, str]]) -> None:
    if isinstance(node, str):
        if node.strip():
            out.append((path, node))
        return
    if isinstance(node, list):
        for i, item in enumerate(node):
            _walk_text(item, f"{path}[{i}]", out)
        return
    if isinstance(node, dict):
        for k, v in node.items():
            _walk_text(v, f"{path}.{k}", out)


def _authored_texts(site: dict, extras: list[Path]) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for i, q in enumerate(site.get("questions") or []):
        if not isinstance(q, dict):
            continue
        key = str(q.get("question_key") or i)
        ans = q.get("answer") or {}
        # Authored fields only; never treat learner stem or choices as phase-3 writing.
        for field in ("explanation", "evidence"):
            if ans.get(field):
                _walk_text(ans.get(field), f"questions[{key}].answer.{field}", texts)
        for j, ref in enumerate(ans.get("references") or []):
            if isinstance(ref, dict):
                _walk_text(ref.get("title") or ref.get("note") or "", f"questions[{key}].answer.references[{j}]", texts)
    for path in extras:
        if not path.is_file():
            continue
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            _walk_text(data, path.name, texts)
        else:
            texts.append((path.name, path.read_text(encoding="utf-8")))
    return texts


def _flags_for(path: str, text: str) -> list[dict]:
    flags = []
    if DASH_RE.search(text):
        flags.append({"path": path, "code": "typographic_dash", "message": "authored text contains an en dash or em dash"})
    if EMOJI_RE.search(text):
        flags.append({"path": path, "code": "emoji", "message": "authored text contains an emoji or dingbat"})
    lowered = text.lower()
    for phrase in BANNED:
        if phrase in lowered:
            flags.append({"path": path, "code": "banned_name", "message": f"authored text contains banned name or seller phrase: {phrase}"})
            break
    if REVIEW_RE.search(text):
        flags.append({"path": path, "code": "review_markup", "message": "authored text contains review markup"})
    return flags


def check(site_path: Path, extras: list[Path] | None = None) -> dict:
    site = json.loads(site_path.read_text(encoding="utf-8"))
    if not isinstance(site, dict):
        raise ValueError("site file is not a JSON object")
    questions = site.get("questions") or []
    texts = _authored_texts(site, extras or [])
    flags: list[dict] = []
    for path, text in texts:
        flags.extend(_flags_for(path, text))
    authored = len(texts) > 0
    if not authored:
        status = "blocked_needs_content"
    elif flags:
        status = "blocked_violations"
    else:
        status = "passed"
    return {
        "schema_version": 1,
        "status": status,
        "authored_fields_present": authored,
        "question_count": len(questions) if isinstance(questions, list) else 0,
        "flag_count": len(flags),
        "flags": flags,
        "content_generation_hook": (
            "Phase 3 content generation is a documented hook. Write explanations and page prose in simple English, "
            "with no typographic dashes, no emoji, no Innovior or competitor names, and no review markup. "
            "Then rerun this gate. Do not change owner keys or option order."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site-file", required=True, type=Path)
    ap.add_argument("--extra", action="append", default=[], type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args(argv)
    if not args.site_file.is_file():
        print(f"ERROR: site file not found: {args.site_file}", file=sys.stderr)
        return 2
    report = check(args.site_file, args.extra)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "authored_fields_present": report["authored_fields_present"],
        "flag_count": report["flag_count"],
        "output": str(args.output),
    }))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
