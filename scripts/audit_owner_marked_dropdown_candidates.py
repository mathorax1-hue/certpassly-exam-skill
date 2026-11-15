#!/usr/bin/env python3
"""Inspect original PDF question/answer screenshot pairs for owner-selected dropdowns.

Produces review candidates, NEVER final keys or released exam content.
It does not infer answers from domain knowledge or bypass source fidelity.
Private input/output only; do not commit result JSON to a public repository.
"""
import argparse
import collections
import hashlib
import json
import re
import tempfile
from pathlib import Path

import fitz
from scripts.detect_owner_marked_dropdown import recover


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def source_image_pairs(doc, allowed_keys):
    current = None
    images = collections.defaultdict(list)
    for page_index, page in enumerate(doc):
        axis = 0 if page.rotation in (90, 270) else 1
        reversed_axis = page.rotation == 270
        events = []
        for block in page.get_text("dict")["blocks"]:
            if block["type"] == 0:
                for line in block["lines"]:
                    sentence = " ".join(s["text"] for s in line["spans"])
                    for match in re.finditer(r"\bQUESTION\s+(\d+)\b", sentence, re.I):
                        num = int(match.group(1))
                        if 1 <= num <= 9999:
                            events.append((line["bbox"][axis], 0, f"q{num:03d}"))
            elif block["type"] == 1 and block.get("image"):
                events.append((block["bbox"][axis], 1, block["image"]))
        for coord, kind, value in sorted(
            events, key=lambda item: (-item[0] if reversed_axis else item[0], item[1])
        ):
            if kind == 0:
                current = value
            elif current in allowed_keys:
                images[current].append({"page": page_index + 1, "bytes": value})
    return images


def audit(pdf_path, held_report, expected_source_sha):
    source = Path(pdf_path).read_bytes()
    if sha(source) != expected_source_sha:
        raise ValueError("Original PDF SHA256 mismatch")
    held_bytes = Path(held_report).read_bytes()
    held = json.loads(held_bytes)
    if not isinstance(held, list) or not held:
        raise ValueError("Held report must be nonempty JSON list")
    keys = [item["question_key"] for item in held]
    if len(keys) != len(set(keys)) or not all(re.fullmatch(r"q\d{3,4}", q) for q in keys):
        raise ValueError("Held question keys must be unique canonical keys")
    doc = fitz.open(stream=source, filetype="pdf")
    mapped = source_image_pairs(doc, set(keys))
    results = []
    for key in keys:
        pair = mapped.get(key, [])
        if len(pair) != 2:
            results.append({"question_key": key, "status": "HELD_NOT_EXACTLY_TWO_IMAGES",
                            "source_image_count": len(pair)})
            continue
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            question = root / "question.png"
            marked = root / "owner-answer.png"
            question.write_bytes(pair[0]["bytes"])
            marked.write_bytes(pair[1]["bytes"])
            try:
                verdict = recover(question, marked)
            except (OSError, ValueError, RuntimeError) as e:
                verdict = {"status": "HELD_DETECTOR_ERROR", "error_type": type(e).__name__}
            verdict["question_key"] = key
            verdict["source_image_count"] = 2
            verdict["question_page"] = pair[0]["page"]
            verdict["answer_page"] = pair[1]["page"]
            verdict["owner_key_candidate_only"] = True
            verdict["release_approved"] = False
            results.append(verdict)
    totals = collections.Counter(r["status"] for r in results)
    return {
        "status": "PRIVATE_REVIEW_CANDIDATES_NOT_RELEASED",
        "source_sha256": sha(source),
        "held_report_sha256": sha(held_bytes),
        "held_count": len(held),
        "source_pages": len(doc),
        "candidate_count": totals["OWNER_MARK_CANDIDATE_VERIFIED"],
        "status_counts": dict(totals),
        "all_held": True,
        "limits": [
            "Only exactly two source images are eligible for automatic candidate review",
            "Visual marker and OCR agreement are not proof of native interaction reconstruction",
            "Candidates must pass source-to-render QA and complete V2 interaction/answer mapping",
            "No question is released or imported by this tool",
        ],
        "questions": results,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pdf", required=True)
    p.add_argument("--held-report", required=True)
    p.add_argument("--pdf-sha256", required=True)
    p.add_argument("--private-report", required=True)
    args = p.parse_args()
    result = audit(args.pdf, args.held_report, args.pdf_sha256)
    out = Path(args.private_report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"],
                      "held_count": result["held_count"],
                      "candidate_count": result["candidate_count"],
                      "status_counts": result["status_counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
