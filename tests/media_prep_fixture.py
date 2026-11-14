"""Synthetic media-prep fixture builder (PUBLIC; 100% synthetic, no owner data).

Generates, deterministically (fixed coordinates, no randomness):
  - synthetic exhibit/answer screenshots with Pillow (clean and marked
    variants: rings, X strokes, highlight boxes);
  - synthetic exam PDFs with PyMuPDF (QUESTION n layout, options, answers,
    embedded images, real PDF annotations, vector-drawn exhibits, rotated
    pages);
  - upstream-compatible extraction workspaces (extracted/split.json +
    media/src/*) so the media-prep engine can be tested WITHOUT cloning the
    upstream pipeline; and
  - an optional INTEGRATION mode: when the environment variable
    CERTPASSLY_UPSTREAM_SCRIPTS points at a pinned upstream checkout, the
    REAL extract_owner_pdf.py is run on the synthetic PDF and its output is
    used instead of the hand-built split (tests then exercise the true
    upstream contract end to end).

Every image, string and layout here is invented for testing. No real exam
content, owner media or private data is used anywhere.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys

HAS_IMAGE_DEPS = True
try:
    import fitz  # noqa: F401
    from PIL import Image, ImageDraw, ImageFilter  # noqa: F401
    import numpy as np  # noqa: F401
    import cv2  # noqa: F401
except ImportError:  # pragma: no cover - skip guards in stdlib-only CI
    HAS_IMAGE_DEPS = False


# --------------------------------------------------------------------------
# deterministic synthetic images
# --------------------------------------------------------------------------

def png_bytes(w, h, draw_fn, mode="RGB", blur=0):
    img = Image.new(mode, (w, h), "white")
    d = ImageDraw.Draw(img)
    draw_fn(d, w, h)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def jpeg_bytes(w, h, draw_fn, quality=90):
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    draw_fn(d, w, h)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def draw_exhibit(d, w, h, title="SYNTHETIC EXHIBIT"):
    """A crisp UI-table-like exhibit: header band, rows, columns, small text."""
    d.rectangle([0, 0, w - 1, 26], fill=(240, 242, 248), outline=(90, 90, 110))
    d.text((8, 8), title, fill=(20, 20, 40))
    rows = 5
    row_h = (h - 34) // rows
    for r in range(rows):
        y = 30 + r * row_h
        d.line([(0, y), (w - 1, y)], fill=(150, 150, 165), width=1)
        d.text((8, y + row_h // 2 - 5), f"Row {r + 1} statement text sample", fill=(30, 30, 40))
        d.text((w // 2 + 10, y + row_h // 2 - 5), f"Column value {r + 1}", fill=(30, 30, 40))
    d.line([(w // 2, 30), (w // 2, h - 1)], fill=(150, 150, 165), width=1)


def draw_marked_exhibit(d, w, h, title="SYNTHETIC EXHIBIT"):
    """Same exhibit plus a thick dark ring around the Row 2 label (selection mark)."""
    draw_exhibit(d, w, h, title)
    row_h = (h - 34) // 5
    y = 30 + 1 * row_h + row_h // 2
    d.ellipse([10, y - 14, w // 3, y + 14], outline=(10, 10, 10), width=5)


def draw_x_marked_exhibit(d, w, h, title="SYNTHETIC EXHIBIT"):
    """Exhibit plus two thick diagonal strokes (X pen marks) over row 3."""
    draw_exhibit(d, w, h, title)
    row_h = (h - 34) // 5
    y = 30 + 2 * row_h + row_h // 2
    d.line([(w // 2 + 20, y - 18), (w // 2 + 130, y + 18)], fill=(10, 10, 10), width=6)
    d.line([(w // 2 + 130, y - 18), (w // 2 + 20, y + 18)], fill=(10, 10, 10), width=6)


def draw_highlight_box_exhibit(d, w, h, title="SYNTHETIC EXHIBIT"):
    """Exhibit plus a hollow rectangle drawn around the Column value 2 cell."""
    draw_exhibit(d, w, h, title)
    row_h = (h - 34) // 5
    y = 30 + 1 * row_h
    d.rectangle([w // 2 + 4, y + 2, w - 6, y + row_h - 2], outline=(10, 10, 10), width=4)


def draw_underlined_exhibit(d, w, h, title="SYNTHETIC EXHIBIT"):
    """Exhibit plus a thick solid underline under row 4 (solid_stroke mark)."""
    draw_exhibit(d, w, h, title)
    row_h = (h - 34) // 5
    y = 30 + 3 * row_h + row_h - 6
    d.line([(6, y), (w // 2 - 20, y)], fill=(10, 10, 10), width=6)


def clean_exhibit_png(w=900, h=420):
    return png_bytes(w, h, draw_exhibit)


def marked_exhibit_png(w=900, h=420):
    return png_bytes(w, h, draw_marked_exhibit)


def x_marked_exhibit_png(w=900, h=420):
    return png_bytes(w, h, draw_x_marked_exhibit)


def highlight_box_exhibit_png(w=900, h=420):
    return png_bytes(w, h, draw_highlight_box_exhibit)


def underlined_exhibit_png(w=900, h=420):
    return png_bytes(w, h, draw_underlined_exhibit)


def different_exhibit_png(w=900, h=420):
    """A second, visually different exhibit (not a registered pair partner)."""
    def draw(d, w, h):
        d.rectangle([0, 0, w - 1, h - 1], outline=(90, 90, 110))
        for i in range(8):
            x = 20 + i * (w - 40) / 8
            d.rectangle([x, h // 3, x + (w - 60) / 16, h // 3 + h // 4],
                        fill=(70, 110, 170), outline=(20, 40, 80))
        d.text((10, 10), "SYNTHETIC CHART B", fill=(20, 20, 40))
    return png_bytes(w, h, draw)


def blurry_exhibit_png(w=900, h=420):
    return png_bytes(w, h, draw_exhibit, blur=6)


def low_contrast_exhibit_png(w=900, h=420):
    def draw(d, w, h):
        d.rectangle([0, 0, w, h], fill=(235, 235, 235))
        for i in range(6):
            d.rectangle([20 + i * 40, 40, 40 + i * 40, h - 40], fill=(228, 228, 228),
                        outline=(230, 230, 230))
    return png_bytes(w, h, draw)


def transparent_exhibit_png(w=900, h=420):
    """RGBA exhibit with fully transparent background (alpha handling check)."""
    return png_bytes(900, 420, draw_exhibit, mode="RGBA")


def clipped_extremes_png(w=900, h=420):
    """Pure black + pure white halves with no midtones (histogram clipping check)."""
    def draw(d, w, h):
        d.rectangle([0, 0, w // 2, h], fill=(0, 0, 0))
        d.rectangle([w // 2, 0, w, h], fill=(255, 255, 255))
    return png_bytes(w, h, draw)


def extreme_aspect_png(w=2000, h=40):
    """Extremely wide clean exhibit (aspect-ratio check)."""
    return png_bytes(w, h, draw_exhibit)


def corrupt_bytes():
    return b"\x89PNG\r\n\x1a\nTRUNCATED-GARBAGE-NOT-A-REAL-IMAGE"[:40]


# --------------------------------------------------------------------------
# synthetic PDF + upstream workspace builders
# --------------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_pdf(path, *, pages_spec):
    """Build a synthetic exam PDF.

    pages_spec: list of dicts:
      {"text": [(x, y, [lines...]), ...],        # one insert_text block per tuple
       "images": [(rect, bytes)],
       "annot": {"rect": [..], "type": "square"|"highlight"|"ink"},
       "vector_table": {"x0":.., "y0":.., "x1":.., "y1":.., "rows": N},
       "vector_exhibit": True,                   # legacy default placement
       "rotate": 0}
    Deterministic output for identical input. Text is written UNROTATED into
    the page content stream (so on /Rotate 90 pages it reads top-to-bottom in
    the +y direction of unrotated space - the same convention every fixture
    page already uses); vector tables are drawn at the exact given rect so
    exhibit-crop geometry tests have deterministic bounds.
    """
    doc = fitz.open()
    for spec in pages_spec:
        page = doc.new_page(width=612, height=792)
        if spec.get("rotate"):
            page.set_rotation(spec["rotate"])
        for (x, y, lines) in spec.get("text", []):
            page.insert_text((x, y), lines[0], fontsize=11, fontname="helv")
            for i, ln in enumerate(lines[1:], start=1):
                page.insert_text((x, y + 14 * i), ln, fontsize=11, fontname="helv")
        for (rect, data) in spec.get("images", []):
            # PyMuPDF sniffs the format from the stream bytes itself
            page.insert_image(fitz.Rect(*rect), stream=data)
        table = spec.get("vector_table")
        if table or spec.get("vector_exhibit"):
            if table:
                x0 = table["x0"]; y0 = table["y0"]
                x1 = table["x1"]; y1 = table["y1"]
                rows = table.get("rows", 6)
            else:  # legacy default placement (old q008 layout)
                x0, y0, x1, y1, rows = 40, 200, 570, 440, 6
            row_h = (y1 - y0) / (rows + 1)
            for r in range(rows + 1):
                y = y0 + r * row_h
                page.draw_line(fitz.Point(x0, y), fitz.Point(x1, y),
                               color=(0.55, 0.55, 0.62), width=1)
                if r < rows:
                    page.insert_text((x0 + 8, y + row_h * 0.7),
                                     f"Vector row {r + 1} synthetic statement",
                                     fontsize=10, fontname="helv")
            page.draw_rect(fitz.Rect(x0, y0, x1, y1),
                           color=(0.55, 0.55, 0.62), width=1.2)
        annot = spec.get("annot")
        if annot:
            r = fitz.Rect(*annot["rect"])
            kind = annot.get("type", "square")
            if kind == "square":
                a = page.add_rect_annot(r)
                a.set_colors(stroke=(1, 0, 0))
                a.update()
            elif kind == "highlight":
                a = page.add_highlight_annot(r)
                a.update()
            else:  # ink
                pts = [fitz.Point(r.x0, r.y0), fitz.Point(r.x1, r.y1)]
                a = page.add_ink_annot([pts])
                a.set_colors(stroke=(0.8, 0, 0))
                a.update()
    doc.save(path, garbage=3, deflate=True)
    return path


def write_upstream_workspace(out_dir, split, media_files):
    """Write an upstream-compatible workspace: extracted/split.json + media/src.

    media_files: {filename: bytes}
    """
    ex = os.path.join(out_dir, "extracted")
    src = os.path.join(out_dir, "media", "src")
    os.makedirs(os.path.join(ex, "items"), exist_ok=True)
    os.makedirs(src, exist_ok=True)
    with open(os.path.join(ex, "split.json"), "w", encoding="utf-8") as f:
        json.dump(split, f, indent=1, ensure_ascii=False)
    for k, rec in split.items():
        with open(os.path.join(ex, "items", f"{k}.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1, ensure_ascii=False)
    for name, data in media_files.items():
        with open(os.path.join(src, name), "wb") as f:
            f.write(data)
    return out_dir


def run_real_upstream(pdf_path, out_dir):
    """INTEGRATION ONLY: run the real pinned upstream extractor on a synthetic PDF.

    Requires CERTPASSLY_UPSTREAM_SCRIPTS to point at the pinned checkout's
    scripts/ dir. Returns (completed, out_dir) - completed=False when the env
    var is absent (tests then skip the real-upstream variant).
    """
    scripts = os.environ.get("CERTPASSLY_UPSTREAM_SCRIPTS")
    if not scripts:
        return False, out_dir
    script = os.path.join(scripts, "extract_owner_pdf.py")
    if not os.path.isfile(script):
        return False, out_dir
    shutil.rmtree(out_dir, ignore_errors=True)
    r = subprocess.run([sys.executable, script, pdf_path, out_dir],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"pinned upstream extractor failed: {r.stderr[:400]}")
    return True, out_dir


# --------------------------------------------------------------------------
# the "full" synthetic scenario workspace (13+ processing scenarios)
# --------------------------------------------------------------------------

def build_full_workspace(root):
    """Build the full synthetic scenario: PDF + upstream workspace + config.

    Question map (deterministic expectations):
      q001 text-only                     -> eligible, no image required
      q002 clean q img + marked answer   -> Priority A eligible
      q003 marked-only q img (different answer content) -> BLOCKED MARKED_ONLY
      q004 tiny clean q img (240px)      -> BLOCKED SOURCE_IMAGE_LOW_RESOLUTION
      q005 marked q img + CLEAN registered pair in answer slot -> Priority C
      q006 inferred swap, clean q img that cannot be trusted, no pair proof
                                         -> BLOCKED SOURCE_IMAGE_AMBIGUOUS
      q007 clean JPEG q img              -> Priority A eligible (PNG re-encode)
      q008 vector exhibit (exact crop; marker/stem ABOVE the table,
           options + Correct Answer BELOW it, real square annotation over a
           table row)                    -> Priority B eligible, EXACT crop
      q009 blurry clean q img            -> BLOCKED SOURCE_IMAGE_BLURRY
      q010 corrupt q img bytes           -> BLOCKED SOURCE_IMAGE_CORRUPT
      q011 only answer images (no q img) -> BLOCKED CLEAN_ASSET_MISSING
      q012 clean + marked pair among TWO q images -> Priority A picks the clean
      q013 low-contrast q img            -> BLOCKED SOURCE_IMAGE_LOW_CONTRAST
      q014 rotated-90 vector exhibit page (twin of q008) -> Priority B exact
           crop; the render must match the rotation-0 twin page render
      q015 THE q074 REGRESSION: multi-question page carrying the PREVIOUS
           question's visible "Correct Answer:" + Explanation tail, QUESTION
           15, its vector exhibit, its options + own "Correct Answer:", and
           the NEXT question's marker. The old whole-page fallback would
           have rendered all of it; only an exact in-band crop is eligible
      q016 exhibit-ref question whose marker sits at the very bottom of
           the shared page (band too small, exhibit unverifiable) -> BLOCKED
           QUESTION_CROP_UNVERIFIED
      q017 exhibit-ref question WITHOUT a source_number in the upstream
           record (no provenance for the marker) -> BLOCKED
           QUESTION_CROP_UNVERIFIED
    Returns (facts dict with paths and expectations).
    """
    root = os.path.abspath(root)
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)

    media = {
        "p-002_1.png": clean_exhibit_png(),          # q002 exhibit (clean)
        "p-002_2.png": marked_exhibit_png(),         # q002 answer (marked)
        "p-003_1.png": marked_exhibit_png(),         # q003 marked q img
        "p-003_2.png": different_exhibit_png(),      # q003 answer (different)
        "p-004_1.png": png_bytes(240, 140, draw_exhibit),  # q004 tiny
        "p-005_1.png": marked_exhibit_png(),         # q005 marked q img
        "p-005_2.png": clean_exhibit_png(),          # q005 clean pair partner
        "p-006_1.png": different_exhibit_png(),      # q006 clean-looking q img (untrusted)
        "p-006_2.png": marked_exhibit_png(),         # q006 moved to answer (inferred)
        "p-007_1.jpg": jpeg_bytes(900, 420, draw_exhibit),  # q007 JPEG clean
        "p-007_2.png": x_marked_exhibit_png(),       # q007 X-marked answer
        "p-009_1.png": blurry_exhibit_png(),         # q009 blurry
        "p-009_2.png": different_exhibit_png(),
        "p-010_1.png": corrupt_bytes(),              # q010 corrupt
        "p-011_1.png": marked_exhibit_png(),         # q011 answer-only
        "p-012_1.png": clean_exhibit_png(),          # q012 clean member
        "p-012_2.png": marked_exhibit_png(),         # q012 marked member
        "p-013_1.png": low_contrast_exhibit_png(),   # q013 low contrast
    }

    def q(n, pages, qimg, aimg, stem=None, **extra):
        rec = {
            "question_key": f"q{n:03d}", "source_number": n,
            "marker": f"QUESTION n {n}", "pages": pages,
            "stem": stem or f"Synthetic stem {n}",
            "options": {"a": "Synthetic option A", "b": "Synthetic option B"},
            "answer_raw": "A", "question_images": qimg, "answer_images": aimg,
            "layout_profile": "question_n_correct_answer",
        }
        rec.update(extra)
        return rec

    split = {
        "q001": q(1, [1], [], []),
        "q002": q(2, [2], ["p-002_1.png"], ["p-002_2.png"]),
        "q003": q(3, [3], ["p-003_1.png"], ["p-003_2.png"]),
        "q004": q(4, [4], ["p-004_1.png"], []),
        "q005": q(5, [5], ["p-005_1.png"], ["p-005_2.png"]),
        "q006": q(6, [6], ["p-006_1.png"], ["p-006_2.png"],
                  answer_image_inferred=True),
        "q007": q(7, [7], ["p-007_1.jpg"], ["p-007_2.png"]),
        "q008": q(8, [8], [], [],
                  stem="Synthetic stem 8. Review the following exhibit and answer."),
        "q009": q(9, [9], ["p-009_1.png"], ["p-009_2.png"]),
        "q010": q(10, [10], ["p-010_1.png"], []),
        "q011": q(11, [11], [], ["p-011_1.png"]),
        "q012": q(12, [12], ["p-012_1.png", "p-012_2.png"], []),
        "q013": q(13, [13], ["p-013_1.png"], []),
        "q014": q(14, [14], [], [],
                  stem="Synthetic stem 14. Review the following exhibit and answer."),
        "q015": q(15, [15], [], [],
                  stem="Synthetic stem 15. Review the following exhibit and answer."),
        "q016": q(16, [15, 16], [], [],
                  stem="Synthetic stem 16. Study the following exhibit."),
        # q017: NO source_number - marker provenance is missing on purpose
        "q017": {"question_key": "q017", "source_number": None,
                 "marker": "QUESTION n 17", "pages": [17],
                 "stem": "Synthetic stem 17. See the following exhibit.",
                 "options": {"a": "one", "b": "two"}, "answer_raw": "A",
                 "question_images": [], "answer_images": [],
                 "layout_profile": "question_n_correct_answer"},
    }

    # synthetic PDF: page per question (q015/q016 share page 15); exhibits
    # embedded where the split says so (bytes-identical to the media files so
    # xref provenance maps); vector-exhibit questions get an EXACTLY placed
    # vector table inside their marker->answer band (reading flow +y).
    pages_spec = [{"text": [(60, 100, ["QUESTION 1", "Synthetic stem 1",
                                       "A. Synthetic option A", "B. Synthetic option B",
                                       "Correct Answer: A"])], "rotate": 90}]
    embed_plan = {
        2: ["p-002_1.png", "p-002_2.png"],
        3: ["p-003_1.png", "p-003_2.png"],
        4: ["p-004_1.png"],
        5: ["p-005_1.png", "p-005_2.png"],
        6: ["p-006_1.png", "p-006_2.png"],
        7: ["p-007_1.jpg", "p-007_2.png"],
        9: ["p-009_1.png", "p-009_2.png"],
        11: ["p-011_1.png"],
        12: ["p-012_1.png", "p-012_2.png"],
        13: ["p-013_1.png"],
    }
    for qno in range(2, 14):
        spec = {"text": [(60, 100, [f"QUESTION {qno}", f"Synthetic stem {qno}",
                                    "A. Synthetic option A", "B. Synthetic option B",
                                    "Correct Answer: A"])], "rotate": 90}
        for i, fname in enumerate(embed_plan.get(qno, [])):
            spec["images"] = spec.get("images", []) + [
                ((60, 240 + i * 240, 552, 240 + i * 240 + 200), media[fname])]
        if qno == 8:
            # exact-crop layout: marker+stem above the table, options+answer
            # below it, and a real square annotation over a table row (the
            # "key" annots=False must exclude)
            spec["text"] = [
                (60, 60, [f"QUESTION {qno}",
                          f"Synthetic stem {qno}. Review the following exhibit and answer."]),
                (60, 460, ["A. Synthetic option A", "B. Synthetic option B",
                           "Correct Answer: A"])]
            spec["vector_table"] = {"x0": 40, "y0": 120, "x1": 570, "y1": 400, "rows": 6}
            spec["annot"] = {"rect": [45, 200, 300, 240], "type": "square"}
        pages_spec.append(spec)

    # page 14 (q014): the rotation-90 twin of the q008 layout (annotation kept
    # so the twin render comparison exercises the same exclusion)
    pages_spec.append({
        "rotate": 90,
        "text": [(60, 60, ["QUESTION 14",
                           "Synthetic stem 14. Review the following exhibit and answer."]),
                 (60, 460, ["A. Synthetic option A", "B. Synthetic option B",
                            "Correct Answer: A"])],
        "vector_table": {"x0": 40, "y0": 120, "x1": 570, "y1": 400, "rows": 6},
        "annot": {"rect": [45, 200, 300, 240], "type": "square"}})

    # page 15 (q015 + q016 marker): THE q074 REGRESSION page - carries the
    # PREVIOUS question's visible Correct Answer + Explanation tail at the
    # top, QUESTION 15 + stem, the vector exhibit, q015's own options +
    # Correct Answer, and the NEXT question's marker at the bottom
    pages_spec.append({
        "rotate": 90,
        "text": [(60, 40, ["Correct Answer: D", "Explanation/Reference:"]),
                 (60, 130, ["QUESTION 15",
                            "Synthetic stem 15. Review the following exhibit and answer."]),
                 (60, 480, ["A. Synthetic option A", "B. Synthetic option B",
                            "Correct Answer: B"]),
                 (60, 700, ["QUESTION 16",
                            "Synthetic stem 16. Study the following exhibit."])],
        "vector_table": {"x0": 40, "y0": 200, "x1": 570, "y1": 420, "rows": 6}})

    # page 16 (q016 continuation): NO QUESTION 16 marker here - the exhibit
    # cannot be source-verified on this page
    pages_spec.append({
        "rotate": 90,
        "text": [(60, 60, ["Synthetic stem 16 continued from the previous page.",
                           "A. Synthetic option A", "B. Synthetic option B",
                           "Correct Answer: A"])]})

    # page 17 (q017): a perfectly good exhibit page, but the upstream record
    # has no source_number -> the marker cannot be tied to the question
    pages_spec.append({
        "rotate": 90,
        "text": [(60, 60, ["QUESTION 17", "Synthetic stem 17. See the following exhibit."]),
                 (60, 460, ["A. one", "B. two", "Correct Answer: A"])],
        "vector_table": {"x0": 40, "y0": 120, "x1": 570, "y1": 400, "rows": 6}})

    pdf_path = os.path.join(root, "synthetic-exam.pdf")
    build_pdf(pdf_path, pages_spec=pages_spec)

    out_dir = os.path.join(root, "out")
    write_upstream_workspace(out_dir, split, media)

    with open(pdf_path, "rb") as f:
        pdf_data = f.read()

    cfg = {
        "schema_version": "media-prep-v1",
        "exam_code": "SYNTHETIC-DEMO",
        "source": {"pdf": pdf_path, "expected_sha256": _sha(pdf_data),
                   "expected_bytes": len(pdf_data)},
        "upstream": {"repo": "msaqlainhaneef1/certpassly-exam-pipeline",
                     "commit": "13dea6bab662ab1c4bbf87017e912e519907c8bc",
                     "scripts_dir": None, "out_dir": out_dir, "run_extract": False},
        "output": {"clean_dir": os.path.join(root, "prepared", "clean"),
                   "private_dir": os.path.join(root, "prepared", "private"),
                   "manifest": os.path.join(root, "prepared", "image-manifest.json"),
                   "inventory": os.path.join(root, "prepared", "image-inventory.json")},
        "display": {"default_css_width": 640, "pixel_density_goal": 2.0},
        "quality_profiles": {},
        "privacy": {"allow_external_urls": False, "allowed_hosts": []},
    }
    cfg_path = os.path.join(root, "media-prep-config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1, ensure_ascii=False)

    expectations = {
        "q001": {"eligible": True, "requires_image": False},
        "q002": {"eligible": True, "method": "priority_a_direct_clean_source"},
        "q003": {"eligible": False, "reason": "MARKED_ONLY_REVIEW_REQUIRED"},
        "q004": {"eligible": False, "reason": "SOURCE_IMAGE_LOW_RESOLUTION"},
        "q005": {"eligible": True, "method": "priority_c_paired_clean_member"},
        "q006": {"eligible": False, "reason": "SOURCE_IMAGE_AMBIGUOUS"},
        "q007": {"eligible": True, "method": "priority_a_direct_clean_source"},
        "q008": {"eligible": True, "method": "priority_b_annotation_free_render"},
        "q009": {"eligible": False, "reason": "SOURCE_IMAGE_BLURRY"},
        "q010": {"eligible": False, "reason": "SOURCE_IMAGE_CORRUPT"},
        "q011": {"eligible": False, "reason": "CLEAN_ASSET_MISSING"},
        "q012": {"eligible": True, "method": "priority_a_direct_clean_source"},
        "q013": {"eligible": False, "reason": "SOURCE_IMAGE_LOW_CONTRAST"},
        "q014": {"eligible": True, "method": "priority_b_annotation_free_render"},
        "q015": {"eligible": True, "method": "priority_b_annotation_free_render"},
        "q016": {"eligible": False, "reason": "QUESTION_CROP_UNVERIFIED"},
        "q017": {"eligible": False, "reason": "QUESTION_CROP_UNVERIFIED"},
    }
    return {"root": root, "pdf": pdf_path, "config": cfg_path, "out_dir": out_dir,
            "media": {k: _sha(v) for k, v in media.items()}, "expectations": expectations}


if __name__ == "__main__":  # pragma: no cover - manual regeneration helper
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    facts = build_full_workspace(args.out)
    print(json.dumps({"root": facts["root"], "pdf": facts["pdf"],
                      "config": facts["config"],
                      "pdf_sha256": _sha(open(facts["pdf"], "rb").read())}, indent=2))
