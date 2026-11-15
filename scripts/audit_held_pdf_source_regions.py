#!/usr/bin/env python3
"""Trace every held question to original PDF image blocks and OCR candidate regions.

PRIVATE diagnostic ONLY. No raw text, answer key, source image or screenshot is
stored in the JSON output. This tool does not certify source fidelity or scoring.
"""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import cv2
import fitz
import numpy as np
from scripts.segment_ui_ocr_regions import regions


def digest(data):
    return hashlib.sha256(data).hexdigest()


def audit(pdf_path, held_path, expected_pdf_sha256, ocr=False, max_ocr=500):
    ocr_regions = 0
    ocr_agreements = 0
    raw = Path(pdf_path).read_bytes()
    if digest(raw) != expected_pdf_sha256:
        raise ValueError("Original PDF SHA-256 mismatch; refusing to inspect a changed source")
    held_file = Path(held_path).read_bytes()
    held = json.loads(held_file)
    if not isinstance(held, list) or not held:
        raise ValueError("Expected a nonempty upstream export/cannot-convert.json list")
    names = [q.get("question_key") for q in held]
    if len(set(names)) != len(names) or any(not isinstance(x, str) for x in names):
        raise ValueError("Held question keys must be unique and nonempty")
    doc = fitz.open(stream=raw, filetype="pdf")
    current = None
    source_images = []
    all_markers = set()
    for page_index, page in enumerate(doc):
        # PyMuPDF's unrotated text coordinates advance along x for pages
        # rotated 90 degrees, and along y for ordinary upright pages.
        # Sorting y on this owner's 90-degree PDF misassigned q043 images.
        axis = 0 if page.rotation in (90, 270) else 1
        reverse_axis = page.rotation == 270
        events = []
        for block in page.get_text("dict")["blocks"]:
            if block["type"] == 0:
                for line in block["lines"]:
                    sentence = " ".join(span["text"] for span in line["spans"])
                    for hit in re.finditer(r"\bQUESTION\s+(\d+)\b", sentence, re.I):
                        number = int(hit.group(1))
                        if 1 <= number <= 89:
                            events.append((line["bbox"][axis], 0, number))
            elif block["type"] == 1 and block.get("image"):
                events.append((block["bbox"][axis], 1, block))
        for _, kind, value in sorted(events, key=lambda x: (-x[0] if reverse_axis else x[0], x[1])):
            if kind == 0:
                current = value
                all_markers.add(current)
            elif current:
                blob = value["image"]
                image = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_COLOR)
                candidates = []
                if image is not None:
                    for region in regions(image):
                        x1, y1, x2, y2 = region["bbox"]
                        if x2 <= x1 or y2 <= y1:
                            continue
                        ok, encoded = cv2.imencode(".png", image[y1:y2, x1:x2])
                        candidate = {
                            "kind": region["kind"], "bbox_pixels": region["bbox"],
                            "crop_sha256": digest(encoded.tobytes()) if ok else None}
                        if ocr and ok and ocr_regions < max_ocr:
                            # OCR is diagnostic only. Persist hashes and word counts,
                            # never question text or answers in the public report.
                            with tempfile.TemporaryDirectory() as tmp:
                                file = Path(tmp) / "private-crop.png"
                                file.write_bytes(encoded.tobytes())
                                token_sets = []
                                for mode in ("3", "6"):
                                    run = subprocess.run(
                                        ["tesseract", str(file), "stdout", "--psm", mode],
                                        check=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, timeout=40)
                                    token_sets.append(
                                        re.findall(r"[A-Za-z0-9_]+", run.stdout.decode(
                                            "utf-8", errors="replace").lower()))
                            candidate["ocr_pass_agreement"] = bool(token_sets[0]) and token_sets[0] == token_sets[1]
                            candidate["ocr_word_counts"] = [len(x) for x in token_sets]
                            candidate["ocr_empty_output"] = not token_sets[0] or not token_sets[1]
                            ocr_regions += 1
                            ocr_agreements += int(candidate["ocr_pass_agreement"])
                        candidates.append(candidate)
                source_images.append({
                    "question_key": "q%03d" % current, "pdf_page": page_index + 1,
                    "pdf_bbox": [round(float(z), 2) for z in value["bbox"]],
                    "image_sha256": digest(blob), "width": value["width"],
                    "height": value["height"], "candidates": candidates,
                })
    records = []
    kinds = Counter()
    for row in held:
        key = row["question_key"]
        imgs = [im for im in source_images if im["question_key"] == key]
        for im in imgs:
            kinds.update(roi["kind"] for roi in im["candidates"])
        records.append({
            "question_key": key,
            "upstream_type_suggestion": row.get("suggested_type"),
            "original_held": True,
            "source_images": imgs,
            "source_image_count": len(imgs),
            "source_verified": False,
            "answer_mapping_verified": False,
            "publishable": False,
        })
    return {
        "status": "HELD_DIAGNOSTIC_ONLY",
        "source_pdf_sha256": digest(raw),
        "upstream_held_report_sha256": digest(held_file),
        "pdf_pages": len(doc),
        "pdf_question_markers": len(all_markers),
        "held_count": len(records),
        "held_with_source_images": sum(bool(q["source_images"]) for q in records),
        "held_without_source_images": [q["question_key"] for q in records if not q["source_images"]],
        "roi_counts": dict(kinds),
        "ocr_regions_tested": ocr_regions,
        "ocr_regions_with_pass_agreement": ocr_agreements,
        "limits": [
            "Source image assignment uses page text-block reading order; requires source review",
            "ROI detection is geometric only, not an answer or text-fidelity verifier",
            "No held question is automatically released",
        ],
        "questions": records,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--held", required=True)
    ap.add_argument("--pdf-sha256", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--ocr", action="store_true",
                    help="Run Tesseract PSM 3 and 6 on isolated private regions")
    ap.add_argument("--max-ocr", type=int, default=500)
    args = ap.parse_args()
    report = audit(args.pdf, args.held, args.pdf_sha256,
                   ocr=args.ocr, max_ocr=args.max_ocr)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in
        ("status", "held_count", "held_with_source_images",
         "held_without_source_images", "roi_counts",
         "ocr_regions_tested", "ocr_regions_with_pass_agreement")}))
    return 0 if report["held_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
