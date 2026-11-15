#!/usr/bin/env python3
"""Recover an independently corroborated owner-marked dropdown answer candidate.

PRIVATE REVIEW AID, never direct publication: a unique four-edge selection box
must agree at two binarization thresholds; two answer crop OCR modes must match;
the exact chosen label must also appear in two OCR readings of the original
unmarked question screenshot. No key is guessed or generated.
"""
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

import cv2


def normalize(s):
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def marked_rectangles(image, threshold):
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)[1]
    contours = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0]
    found = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if not (max(80, width * 0.12) <= w <= width * 0.87
                and 13 <= h <= height * .22 and x < width * .75):
            continue
        patch = gray[y:y + h, x:x + w]
        if patch.shape[0] < 12:
            continue
        top = (patch[0, :] < threshold).mean()
        bottom = (patch[-1, :] < threshold).mean()
        left = (patch[:, 0] < threshold).mean()
        right = (patch[:, -1] < threshold).mean()
        if min(top, bottom, left, right) < .45:
            continue
        found.append((x, y, w, h))
    # Thick rectangular outlines can generate an inner and outer contour.
    # Treat overlapping near-identical geometry as ONE mark, never two keys.
    distinct = []
    for box in sorted(set(found), key=lambda z: z[2] * z[3]):
        if any(max(abs(a - b) for a, b in zip(box, prior)) <= 5
               for prior in distinct):
            continue
        distinct.append(box)
    return sorted(distinct)


def tesseract_text(image, mode):
    with tempfile.TemporaryDirectory() as tmp:
        file = Path(tmp) / "private.png"
        if not cv2.imwrite(str(file), image):
            raise OSError("Cannot write private OCR sample")
        p = subprocess.run(["tesseract", str(file), "stdout", "--psm", str(mode)],
                           capture_output=True, check=True, timeout=40)
        return normalize(p.stdout.decode("utf-8", "replace"))


def recover(question_path, answer_path):
    original = Path(question_path).read_bytes()
    marked = Path(answer_path).read_bytes()
    question = cv2.imread(str(question_path))
    answer = cv2.imread(str(answer_path))
    if question is None or answer is None:
        raise ValueError("Image unreadable")
    first = marked_rectangles(answer, 60)
    second = marked_rectangles(answer, 130)
    if len(first) != 1 or len(second) != 1:
        return {"status": "HELD_UNCERTAIN_MARK", "counts": [len(first), len(second)]}
    box = first[0]
    if max(abs(a - b) for a, b in zip(first[0], second[0])) > 2:
        return {"status": "HELD_MARK_METHOD_DISAGREEMENT"}
    x, y, w, h = box
    crop = answer[y + 3:y + h - 5, x + 4:x + w - 5]
    if crop.size == 0:
        return {"status": "HELD_EMPTY_CROP"}
    enlarged = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    chosen6 = tesseract_text(enlarged, 6)
    chosen7 = tesseract_text(enlarged, 7)
    if not chosen6 or chosen6 != chosen7:
        return {"status": "HELD_ANSWER_OCR_DISAGREEMENT",
                "ocr_counts": [len(chosen6.split()), len(chosen7.split())]}
    source6 = tesseract_text(question, 6)
    source11 = tesseract_text(question, 11)
    if chosen6 not in source6 or chosen6 not in source11:
        return {"status": "HELD_SOURCE_OPTION_NOT_VERIFIED"}
    return {
        "status": "OWNER_MARK_CANDIDATE_VERIFIED",
        "source_image_sha256": hashlib.sha256(original).hexdigest(),
        "answer_image_sha256": hashlib.sha256(marked).hexdigest(),
        "bbox": list(box), "selected_label": chosen6,
        "evidence": "Two pixel thresholds; answer OCR PSM 6/7; original question OCR PSM 6/11",
        "release_approved": False,
    }


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--question-image", required=True)
    p.add_argument("--answer-image", required=True)
    p.add_argument("--private-report", required=True)
    opts = p.parse_args()
    result = recover(opts.question_image, opts.answer_image)
    dest = Path(opts.private_report)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"],
                      "release_approved": False,
                      "report_path": str(dest)}))
    return 0 if result["status"] == "OWNER_MARK_CANDIDATE_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
