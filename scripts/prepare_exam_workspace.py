#!/usr/bin/env python3
"""Build a private pipeline workspace from one raw-exam folder.

Copies the owner PDF after checking it is not a Git LFS pointer, writes a
one-row catalog, and writes pipeline.yaml using the manifest rights statement.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_lfs_pointer(path: Path) -> bool:
    with path.open("rb") as fh:
        head = fh.read(200)
    return head.startswith(LFS_PREFIX) or path.stat().st_size < 400 and b"oid sha256:" in head


def load_manifest(raw_dir: Path) -> dict:
    path = raw_dir / "manifest.json"
    if not path.is_file():
        raise SystemExit(f"ERROR: missing {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("ERROR: manifest is not a JSON object")
    return data


def catalog_row(exam: str, manifest: dict, links: Path | None) -> dict:
    vendor_slug = str(manifest.get("vendor_slug") or "unknown")
    row = {
        "vendor": vendor_slug.replace("-", " ").title(),
        "vendor_slug": vendor_slug,
        "certification": "",
        "exam_code": exam,
        "exam_name": exam,
        "sheet_status": str(manifest.get("sheet_status") or ""),
        "drive_folder_url": "",
        "sheet_cell": str(manifest.get("source_sheet_row") or ""),
        "sheet_label": exam,
        "official_exam_url": "",
        "url_http": "",
        "page_names_exam": "",
        "url_sha256": "",
        "source_path": "",
        "empty_reason": "",
    }
    if links and links.is_file():
        with links.open(newline="", encoding="utf-8") as fh:
            for cand in csv.DictReader(fh):
                if (cand.get("exam_code") or cand.get("code")) == exam:
                    if cand.get("official_exam_url"):
                        row["official_exam_url"] = cand["official_exam_url"]
                    if cand.get("vendor"):
                        row["vendor"] = cand["vendor"]
                    if cand.get("vendor_slug"):
                        row["vendor_slug"] = cand["vendor_slug"]
                    break
    if not row["official_exam_url"]:
        row["empty_reason"] = "Official exam page not located in this phase (no confirmed URL pattern; not guessed)."
    return row


def prepare(raw_dir: Path, workspace: Path, exam: str, links: Path | None, pipeline_example: Path | None = None) -> dict:
    manifest = load_manifest(raw_dir)
    code = str(manifest.get("exam_code") or exam)
    if code != exam:
        raise SystemExit(f"ERROR: manifest exam_code {code} does not match {exam}")
    source = raw_dir / "source"
    pdfs = sorted([p for p in source.glob("*.pdf") if p.is_file()]) if source.is_dir() else []
    if not pdfs:
        raise SystemExit(f"ERROR: no PDF in {source}")
    owner = workspace / "owner-files" / exam
    owner.mkdir(parents=True, exist_ok=True)
    copied = []
    expected = {f["name"]: f for f in manifest.get("pdf_files") or [] if isinstance(f, dict)}
    for pdf in pdfs:
        if is_lfs_pointer(pdf):
            raise SystemExit(f"ERROR: {pdf.name} is a Git LFS pointer; fetch the real PDF first")
        digest = sha256(pdf)
        meta = expected.get(pdf.name)
        if meta and meta.get("sha256") and meta["sha256"] != digest:
            raise SystemExit(f"ERROR: {pdf.name} sha256 {digest} does not match manifest {meta['sha256']}")
        dest = owner / pdf.name
        shutil.copy2(pdf, dest)
        copied.append({"name": pdf.name, "sha256": digest, "bytes": dest.stat().st_size})
    workspace.mkdir(parents=True, exist_ok=True)
    catalog = workspace / "catalog.csv"
    row = catalog_row(exam, manifest, links)
    with catalog.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row.keys()))
        w.writeheader()
        w.writerow(row)
    cfg = workspace / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    rights = str(manifest.get("owner_rights_statement") or "").strip()
    if not rights:
        raise SystemExit("ERROR: manifest is missing owner_rights_statement")
    dest_yaml = cfg / "pipeline.yaml"
    if pipeline_example and pipeline_example.is_file():
        dest_yaml.write_text(pipeline_example.read_text(encoding="utf-8"), encoding="utf-8")
    elif not dest_yaml.is_file():
        dest_yaml.write_text(
            "brand: CertPassly\n"
            "disclaimer: \"CertPassly is an independent exam preparation platform. "
            "CertPassly is not sponsored, endorsed, run or approved by the vendors whose exams we cover.\"\n",
            encoding="utf-8",
        )
    text = dest_yaml.read_text(encoding="utf-8")
    escaped = rights.replace("\\", "\\\\").replace('"', '\\"')
    line = "owner_rights_statement: \"" + escaped + "\"\n"
    if "owner_rights_statement:" in text:
        lines = []
        for raw in text.splitlines(True):
            if raw.startswith("owner_rights_statement:"):
                lines.append(line)
            else:
                lines.append(raw)
        dest_yaml.write_text("".join(lines), encoding="utf-8")
    else:
        dest_yaml.write_text(text.rstrip() + "\n" + line, encoding="utf-8")

    review_files = []
    review_src = raw_dir / "review"
    if review_src.is_dir():
        dest_review = workspace / "review"
        dest_review.mkdir(parents=True, exist_ok=True)
        for src in sorted(review_src.glob("*.json")):
            shutil.copy2(src, dest_review / src.name)
            review_files.append(src.name)
        ai_dir = review_src / "ai-reads"
        if ai_dir.is_dir():
            dest_ai = dest_review / "ai-reads"
            dest_ai.mkdir(parents=True, exist_ok=True)
            for src in sorted(ai_dir.glob("*.json")):
                shutil.copy2(src, dest_ai / src.name)
                review_files.append("ai-reads/" + src.name)

    return {"exam_code": exam, "files": copied, "catalog": str(catalog), "workspace": str(workspace), "review_files": review_files}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-dir", required=True, type=Path)
    ap.add_argument("--workspace", required=True, type=Path)
    ap.add_argument("--exam", required=True)
    ap.add_argument("--exam-links", type=Path)
    ap.add_argument("--pipeline-example", type=Path, help="Upstream config/pipeline.example.yaml")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args(argv)
    report = prepare(args.raw_dir, args.workspace, args.exam, args.exam_links, args.pipeline_example)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(2)
        raise
