#!/usr/bin/env python3
"""Fail if a public log contains question text, PDF media names, or secret prefixes.

Never prints the matching text, file names, or secret values. Reports only counts.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SECRET_RX = re.compile(
    r"(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|gsk_[A-Za-z0-9]{20,}"
    r"|GROQ_API_KEY\s*=\s*\S+|CERTPASSLY_REPOS_PAT\s*=\s*\S+|Bearer\s+[A-Za-z0-9._\-]{20,})",
    re.I,
)
MIN_PHRASE = 16


def _plain(node) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float, bool)):
        return str(node)
    if isinstance(node, list):
        return " ".join(_plain(x) for x in node)
    if isinstance(node, dict):
        if "text" in node and isinstance(node["text"], str):
            parts = [node["text"]]
            for key in ("content", "children", "items"):
                if key in node:
                    parts.append(_plain(node[key]))
            return " ".join(parts)
        return " ".join(_plain(v) for k, v in node.items() if k not in {"url", "id", "type", "version"})
    return ""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _useful(text: str, minimum: int = MIN_PHRASE) -> bool:
    s = _norm(text)
    if len(s) < minimum:
        return False
    letters = sum(ch.isalpha() for ch in s)
    return letters >= min(8, minimum // 2)


def phrases_from_site(path: Path) -> list[str]:
    out: list[str] = []
    if not path or not path.is_file():
        return out
    data = json.loads(path.read_text(encoding="utf-8"))
    for q in data.get("questions") or []:
        if not isinstance(q, dict):
            continue
        learner = q.get("learner") or {}
        out.append(_plain(learner.get("stem")))
        for ch in learner.get("choices") or []:
            out.append(_plain(ch))
        for block in learner.get("content_blocks") or []:
            out.append(_plain(block))
        for media in learner.get("media") or []:
            if isinstance(media, dict):
                out.append(media.get("alt") or "")
                url = str(media.get("url") or "")
                if url:
                    out.append(Path(url).name)
    return out


def phrases_from_export(export_dir: Path) -> list[str]:
    out: list[str] = []
    if not export_dir or not export_dir.is_dir():
        return out
    items = export_dir.parent / "extracted" / "items"
    if not items.is_dir():
        items = export_dir / "extracted" / "items"
    if items.is_dir():
        for path in items.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            out.append(str(data.get("stem") or ""))
            opts = data.get("options") or {}
            if isinstance(opts, dict):
                out.extend(str(v) for v in opts.values())
            for key in ("question_images", "answer_images"):
                for fn in data.get(key) or []:
                    out.append(Path(str(fn)).name)
    return out


def phrases_from_source_names(raw_dir: Path) -> list[str]:
    out: list[str] = []
    if not raw_dir:
        return out
    source = raw_dir / "source" if (raw_dir / "source").is_dir() else raw_dir
    if source.is_dir():
        for path in source.iterdir():
            if path.is_file():
                out.append(path.name)
    return out


def collect_phrases(site_file: Path | None, export_dir: Path | None, raw_dir: Path | None) -> list[str]:
    raw: list[str] = []
    if site_file:
        raw.extend(phrases_from_site(site_file))
    if export_dir:
        raw.extend(phrases_from_export(export_dir))
    if raw_dir:
        raw.extend(phrases_from_source_names(raw_dir))
    seen: set[str] = set()
    phrases: list[str] = []
    for item in raw:
        text = _norm(item)
        if not _useful(text):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        phrases.append(text)
    return phrases


def scan_text(text: str, phrases: list[str]) -> dict:
    blob = text or ""
    secret_hits = len(SECRET_RX.findall(blob))
    lowered = blob.lower()
    phrase_hits = 0
    for phrase in phrases:
        if phrase.lower() in lowered:
            phrase_hits += 1
    return {
        "phrase_count": len(phrases),
        "phrase_hits": phrase_hits,
        "secret_hits": secret_hits,
        "leak": phrase_hits > 0 or secret_hits > 0,
    }


def iter_log_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    files: list[Path] = []
    if path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_file() and child.stat().st_size > 0:
                files.append(child)
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", required=True, type=Path, help="Log file or extracted log directory")
    ap.add_argument("--site-file", type=Path)
    ap.add_argument("--export-dir", type=Path)
    ap.add_argument("--raw-dir", type=Path)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args(argv)
    if not args.log.exists():
        print("leak_check=fail reason=log_missing")
        return 2
    phrases = collect_phrases(args.site_file, args.export_dir, args.raw_dir)
    phrase_hits = 0
    secret_hits = 0
    files = iter_log_files(args.log)
    if not files:
        print("leak_check=fail reason=log_empty")
        return 2
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = scan_text(text, phrases)
        phrase_hits += found["phrase_hits"]
        secret_hits += found["secret_hits"]
    leak = phrase_hits > 0 or secret_hits > 0
    report = {
        "status": "fail" if leak else "pass",
        "files_scanned": len(files),
        "phrase_count": len(phrases),
        "phrase_hits": phrase_hits,
        "secret_hits": secret_hits,
        "note": "Matching text is never written to this report or to stdout.",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "leak_check=%s files_scanned=%s phrase_count=%s phrase_hits=%s secret_hits=%s"
        % (report["status"], report["files_scanned"], report["phrase_count"],
           report["phrase_hits"], report["secret_hits"])
    )
    return 2 if leak else 0


if __name__ == "__main__":
    raise SystemExit(main())
