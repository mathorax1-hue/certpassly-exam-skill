#!/usr/bin/env python3
"""Apply narrow, reviewed security patches to a clean external V2 source checkout.

Source remains external at an immutable commit. No upstream source is
republished or copied into the public skill hub.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

PIN = "462fd237ae7f0c607bb00229e173b22d0f3298d2"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one reviewed patch anchor, got {count}")
    return text.replace(old, new, 1)


def patch_validator(src: str) -> str:
    lines = src.splitlines(keepends=True)
    positions = [i for i, line in enumerate(lines) if line.startswith("ATTR_RE = re.compile(")]
    if len(positions) != 1:
        raise ValueError("attribute matcher anchor changed")
    # The matcher recognizes unquoted attributes so the allow-list can reject
    # them instead of silently overlooking a dangerous handler or URL.
    lines[positions[0]] = r"""ATTR_RE = re.compile(r'''([A-Za-z_:][A-Za-z0-9:_.-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>]+))''', re.S)""" + "\n"
    src = "".join(lines)
    src = replace_once(src,
        "        for am in ATTR_RE.finditer(attr_s):\n"
        "            an = am.group(1).lower()\n"
        "            av = am.group(3) if am.group(3) is not None else (am.group(4) or '')\n",
        "        parsed_end = 0\n"
        "        for am in ATTR_RE.finditer(attr_s):\n"
        "            if attr_s[parsed_end:am.start()].strip():\n"
        "                errs.append('malformed or unsupported markup attribute')\n"
        "            parsed_end = am.end()\n"
        "            an = am.group(1).lower()\n"
        "            av = am.group(2) if am.group(2) is not None else (am.group(3) if am.group(3) is not None else (am.group(4) or ''))\n"
        "            if am.group(4) is not None:\n"
        "                errs.append(f'unquoted attribute {an} is forbidden')\n"
        "                continue\n",
        "quoted-attribute enforcement")
    src = replace_once(src,
        "    if re.search(r'<script\\b', text, re.I):\n",
        "        if attr_s[parsed_end:].strip().strip('/'):\n"
        "            errs.append('malformed or unsupported markup attribute')\n"
        "    if re.search(r'<script\\b', text, re.I):\n",
        "malformed-attribute rejection")
    head = "def _href_ok(value: str, allow_data_image: bool, svg_fragment_only: bool) -> bool:\n"
    tail = "def check_markup(text: str, kind: str, allow, allow_data_image: bool) -> list[str]:\n"
    if src.count(head) != 1 or src.count(tail) != 1:
        raise ValueError("URL policy patch boundaries have changed")
    start = src.index(head)
    end = src.index(tail, start)
    safe_url = r'''def _href_ok(value: str, allow_data_image: bool, svg_fragment_only: bool) -> bool:
    import html
    from urllib.parse import urlsplit
    # Check the decoded URL, not the literal HTML attribute encoding.
    compact = re.sub(r'[\x00-\x20\x7f]+', '', html.unescape((value or '').strip()))
    low = compact.lower()
    if not compact or '\\' in compact:
        return False
    if svg_fragment_only:
        return compact.startswith('#') and len(compact) > 1
    if low.startswith('data:'):
        if not allow_data_image:
            return False
        # The author exception is for raster formats, never executable SVG.
        return bool(re.match(r'^data:image/(?:png|jpeg|gif|webp)(?:;base64)?,', low))
    if compact.startswith('//'):
        return False
    if compact.startswith(('/', '#')):
        return True
    parts = urlsplit(compact)
    return parts.scheme.lower() in ('https', 'http') and bool(parts.netloc)


'''
    return src[:start] + safe_url + src[end:]


def patch_migrator(src: str) -> str:
    old = (
        "        for rec in reference_media:\n"
        "            path = (rec.get('href') or '').lower()\n"
        "            if 'answer-review' in path:\n"
        "                continue\n"
        "            if rec.get('alt') and rec not in learner_media:\n"
        "                rec = dict(rec)\n"
        "                rec['role'] = 'diagram'\n"
        "                learner_media.append(rec)\n"
    )
    new = (
        "        # Only explicitly candidate-visible diagrams can become learner media.\n"
        "        # Reviewer-only references must never be promoted by filename.\n"
        "        candidate_paths = {\n"
        "            normalize_href(im.get('path') or '') for im in images\n"
        "            if (im.get('kind') or '').lower() == 'diagram'\n"
        "            and (im.get('visibility') or '').lower() in {'candidate', 'learner', 'public'}\n"
        "            and not any(token in (im.get('path') or '').lower()\n"
        "                        for token in ('answer', 'review', 'marked', 'solution', 'correct', 'key'))\n"
        "        }\n"
        "        reviewer_paths = {\n"
        "            normalize_href(im.get('path') or '') for im in images\n"
        "            if (im.get('visibility') or '').lower() in {'reviewer', 'reviewer_only'}\n"
        "        }\n"
        "        candidate_paths -= reviewer_paths\n"
        "        for rec in reference_media:\n"
        "            if (rec.get('href') or '') not in candidate_paths:\n"
        "                continue\n"
        "            if rec.get('alt') and rec not in learner_media:\n"
        "                rec = dict(rec)\n"
        "                rec['role'] = 'diagram'\n"
        "                learner_media.append(rec)\n"
    )
    return replace_once(src, old, new, "reviewer-only media protection")


def apply(root: Path) -> list[str]:
    pin = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if pin != PIN:
        raise ValueError(f"Refusing unexpected upstream commit {pin}")
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True).strip():
        raise ValueError("Refusing to patch dirty upstream checkout")
    edits = []
    for relative, transform in (
        ("scripts/validate_question_v2.py", patch_validator),
        ("scripts/migrate_v1_to_v2.py", patch_migrator),
    ):
        path = root / relative
        output = transform(path.read_text(encoding="utf-8"))
        compile(output, str(path), "exec")
        edits.append((path, output))
    for path, text in edits:
        path.write_text(text, encoding="utf-8")
    return [str(path.relative_to(root)) for path, _ in edits]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--upstream", type=Path, required=True)
    args = ap.parse_args(argv)
    print("Applied checked V2 hotfixes:", apply(args.upstream.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
