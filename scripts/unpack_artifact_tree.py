#!/usr/bin/env python3
"""Unpack a pipeline ZIP into browsable directories with a SHA-256 file manifest.

Reject unsafe paths, symlinks and duplicate names. Nested ZIPs become folders.
Never publish data or award exam approvals. Standard-library-only utility.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

MAX_DEPTH = 4
DEFAULT_MAX_BYTES = 512 * 1024 * 1024


def safe_path(name):
    if '\\' in name or name.startswith('/'):
        raise ValueError('unsafe archive path')
    p = PurePosixPath(name)
    if not name or any(part in ('..', '.') for part in name.split('/')) or ':' in p.parts[0]:
        raise ValueError('unsafe archive path')
    return p


def unpack(archive, destination, max_bytes=DEFAULT_MAX_BYTES):
    source = Path(archive)
    target = Path(destination)
    if target.exists() and any(target.iterdir()):
        raise ValueError('destination must be an empty directory')
    if not source.is_file():
        raise FileNotFoundError(source)
    raw = source.read_bytes()
    files, used = [], set()
    remaining = max_bytes
    nested = 0

    def open_archive(data, prefix=PurePosixPath(), depth=0):
        nonlocal remaining, nested
        if depth > MAX_DEPTH:
            raise ValueError('nested archive depth exceeded')
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                path = safe_path(info.filename)
                if info.is_dir():
                    continue
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    raise ValueError('symlink member forbidden')
                rel = prefix.joinpath(path)
                # No opaque nested .zip files in final output.
                if path.suffix.lower() == '.zip':
                    nested += 1
                    blob = z.read(info)
                    remaining -= len(blob)
                    if remaining < 0:
                        raise ValueError('uncompressed size limit exceeded')
                    open_archive(blob, prefix.joinpath(path.with_suffix('')), depth + 1)
                    continue
                folded = str(rel).casefold()
                if folded in used or rel.name == 'FILE-MANIFEST.json':
                    raise ValueError('duplicate or reserved output path')
                used.add(folded)
                remaining -= info.file_size
                if remaining < 0:
                    raise ValueError('uncompressed size limit exceeded')
                blob = z.read(info)
                if len(blob) != info.file_size:
                    raise ValueError('archive member length mismatch')
                dest = target.joinpath(*rel.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open('xb') as f:
                    f.write(blob)
                files.append({'path': str(rel), 'bytes': len(blob),
                              'sha256': hashlib.sha256(blob).hexdigest()})

    try:
        open_archive(raw)
        manifest = {
            'source_archive_sha256': hashlib.sha256(raw).hexdigest(),
            'source_archive_name': source.name,
            'file_count': len(files),
            'total_uncompressed_bytes': sum(f['bytes'] for f in files),
            'nested_archives_expanded': nested,
            'draft_only': True,
            'release_approved': False,
            'note': 'Source inventory for private review. Not evidence of correct keys or completed release gates.',
            'files': sorted(files, key=lambda f: f['path'])
        }
        target.mkdir(parents=True, exist_ok=True)
        (target / 'FILE-MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        return manifest
    except Exception:
        # Preserve no misleading manifest after an unsuccessful extraction.
        # Caller uses a new empty destination for retries.
        if target.exists():
            for p in sorted(target.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                if p.is_file():
                    p.unlink()
                elif p.is_dir():
                    p.rmdir()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--max-bytes', type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args(argv)
    try:
        result = unpack(args.archive, args.destination, args.max_bytes)
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        print('Archive extraction refused: ' + str(e), file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
