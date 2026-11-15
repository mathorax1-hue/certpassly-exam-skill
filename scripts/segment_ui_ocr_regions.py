#!/usr/bin/env python3
"""Identify OCR-friendly regions in exam UI screenshots.

Diagnostic only: do not infer answer keys, release held questions, or turn
reference-image crops into published learner media. Store generated crops private.
"""
import argparse
import hashlib
import json
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def regions(image):
    import cv2
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    _, inv = cv2.threshold(gray, 115, 255, cv2.THRESH_BINARY_INV)

    horizontal = cv2.morphologyEx(
        inv, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(55, int(w * .2)), 1)))
    vertical = cv2.morphologyEx(
        inv, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(30, int(h * .12)))))

    lines = []
    for contour in cv2.findContours(horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, line_width, line_height = cv2.boundingRect(contour)
        if line_width >= max(55, int(w * .3)) and line_height <= 9:
            lines.append((x, y, line_width))

    edges = []
    for contour in cv2.findContours(vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, edge_width, edge_height = cv2.boundingRect(contour)
        if edge_height >= max(30, h * .12) and edge_width <= 12:
            edges.append((x, y, y + edge_height))

    lines.sort(key=lambda item: item[1])
    detected = []
    for i, (x, top, width) in enumerate(lines):
        for other_x, bottom, other_width in lines[i + 1:]:
            if not (35 <= bottom - top <= h * .9):
                continue
            if abs(other_x - x) > 9 or abs(other_width - width) > 11:
                continue
            end = x + width - 1
            left = any(abs(ex - x) <= 8 and ey <= top + 8 and ey2 >= bottom - 7
                       for ex, ey, ey2 in edges)
            right = any(abs(ex - end) <= 8 and ey <= top + 8 and ey2 >= bottom - 7
                        for ex, ey, ey2 in edges)
            if left and right:
                box = [x + 5, top + 6, end - 4, bottom - 4]
                if box[2] > box[0] + 30 and box[3] > box[1] + 20:
                    detected.append({
                        "kind": "enclosed_text_control", "bbox": box,
                        "method": "matched_horizontal_and_vertical_rules"})

    # Repeated right-aligned radio circles may indicate a matrix. Isolate only
    # the statement text column. Circle appearance is NOT answer evidence.
    blur = cv2.GaussianBlur(gray, (5, 5), 1)
    circles = cv2.HoughCircles(
        blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=18,
        param1=90, param2=16,
        minRadius=max(4, int(h * .018)),
        maxRadius=max(12, int(h * .07)))
    if circles is not None:
        columns = {}
        for cx, cy, _ in circles[0]:
            if cx <= w * .77:
                continue
            col = round(float(cx) / 8) * 8
            columns.setdefault(col, []).append(int(cy))
        aligned = []
        for col, ys in columns.items():
            separated = []
            for y in sorted(set(ys)):
                if not separated or y - separated[-1] >= max(20, h * .1):
                    separated.append(y)
            if len(separated) >= 3:
                aligned.append((col, separated))
        if len(aligned) >= 2:
            cut = max(1, min(col for col, _ in aligned) - max(14, int(w * .025)))
            detected.append({
                "kind": "matrix_statement_column", "bbox": [0, 0, cut, h],
                "method": "repeated_aligned_radio_columns"})

    unique = {tuple(row["bbox"]) + (row["kind"],): row for row in detected}
    return list(unique.values())


def process(image_path, out_dir):
    import cv2
    source = Path(image_path)
    image = cv2.imread(str(source))
    if image is None:
        raise ValueError("Cannot decode original image")
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    report = {
        "source_image_sha256": sha(source.read_bytes()),
        "original_dimensions": [image.shape[1], image.shape[0]],
        "status": "PRIVATE_DIAGNOSTIC_ONLY_NOT_SOURCE_APPROVAL",
        "regions": []}
    for i, row in enumerate(regions(image), 1):
        x1, y1, x2, y2 = row["bbox"]
        name = "ocr-region-%03d.png" % i
        fp = dest / name
        if not cv2.imwrite(str(fp), image[y1:y2, x1:x2]):
            raise OSError("Cannot write region crop")
        report["regions"].append({**row, "file": name, "sha256": sha(fp.read_bytes())})
    (dest / "regions.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    result = process(args.image, args.out_dir)
    print(json.dumps({"regions": len(result["regions"]),
                      "kinds": [row["kind"] for row in result["regions"]]}))


if __name__ == "__main__":
    main()
