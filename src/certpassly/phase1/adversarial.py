#!/usr/bin/env python3
"""Phase 1 extraction: adversarial synthetic tests (public toolkit; NO real exam data).

Each scenario builds a SYNTHETIC PDF, runs the REAL pinned upstream extractor
(extract_owner_pdf.py / analyze_visual.py) and the REAL generalized builder
(certpassly.phase1.build_structured_v1), then asserts the expected behavior:
correct handling OR an explicit, safe failure (FAIL/BLOCKED with reason). No
test data comes from any real exam PDF.

27 scenarios = the 17 ZAI-EXTRACT-001 pilot scenarios (ported unchanged in
substance) + 10 ZAI-EXTRACT-002 scenarios: missing image binary, duplicate
question ids with gap, rotated 270 pages, text insertion order, vector-only
diagrams, multiple choices in answer screenshots, duplicate xref on three
pages, malformed MIME image streams, non-embedded (optional) fonts, and exact
answer-image privacy through the export layer.

Usage: python -m certpassly.phase1.adversarial --base <scratch-dir>
          --upstream <pinned-scripts-dir> [--engine <dir>]
          [--report-out <json path>] [--date <iso-date>]

By default the builder/exports stages run via ``python -m certpassly.phase1.*``
(this package). ``--engine <dir>`` optionally points at a directory containing
legacy standalone scripts (make_pmap.py / build_structured_v1.py /
build_exports.py) for compatibility replay against the historical private
toolkit.
"""
from __future__ import annotations
import argparse, hashlib, io, json, os, shutil, subprocess, sys

import fitz
from PIL import Image, ImageDraw, ImageFilter

results = []
A = None  # parsed args


def report(name, passed, detail):
    results.append(dict(scenario=name, passed=bool(passed), detail=str(detail)[:400]))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")


def png_bytes(w, h, draw_fn, blur=0):
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    draw_fn(d)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    b = io.BytesIO()
    img.save(b, format="PNG")
    return b.getvalue()


def q_text(page, x, y, lines, size=11, fontname="helv"):
    page.insert_text((x, y), lines[0], fontsize=size, fontname=fontname)
    for i, ln in enumerate(lines[1:], start=1):
        page.insert_text((x, y + 14 * i), ln, fontsize=size, fontname=fontname)


def std_question(page, n, stem, options=("A. one", "B. two", "C. three", "D. four"), answer="B"):
    q_text(page, 60, 80, [f"QUESTION {n}", stem, *options, f"Correct Answer: {answer}",
                          "Section: (none)", "Explanation", "Explanation/Reference:"])


def run_pinned(pdf, exam):
    out = f"{A.base}/workspace/out/{exam}"
    shutil.rmtree(out, ignore_errors=True)
    r = subprocess.run([sys.executable, f"{A.upstream}/extract_owner_pdf.py", pdf, out],
                       capture_output=True, text=True)
    return r, out


def _engine_cmd(script_name):
    """Command prefix for an engine stage: module mode, or legacy --engine dir."""
    if A.engine:
        return [sys.executable, f"{A.engine}/{script_name}.py"]
    return [sys.executable, "-m", f"certpassly.phase1.{script_name}"]


def make_config(exam, pdf, out_dir, expected_sha):
    cfg = dict(
        schema_version="structured-v1",
        exam_code=exam,
        generated_by={"worker": "Z.ai (adversarial suite)", "date": A.date,
                      "environment": "local sandbox"},
        paths=dict(pdf=pdf, out_dir=out_dir,
                   upstream_out=f"{A.base}/workspace/out/{exam}",
                   repo=f"{A.base}/fake-repo", pmap=f"{A.base}/pmap-{exam}.json",
                   build_stats=f"{A.base}/stats-{exam}.json"),
        source=dict(expected_pdf_sha256=expected_sha),
        upstream=dict(repo="msaqlainhaneef1/certpassly-exam-pipeline",
                      commit="13dea6bab662ab1c4bbf87017e912e519907c8bc"),
    )
    cfgp = f"{A.base}/cfg-{exam}.json"
    json.dump(cfg, open(cfgp, "w"))
    return cfgp


def run_builder(pdf, exam, expected_sha):
    out_dir = f"{A.base}/structured/{exam}"
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run(_engine_cmd("make_pmap") + [pdf,
                    f"{A.base}/workspace/out/{exam}/media/src", f"{A.base}/pmap-{exam}.json"],
                   capture_output=True, text=True)
    cfgp = make_config(exam, pdf, out_dir, expected_sha)
    r = subprocess.run(_engine_cmd("build_structured_v1") + [cfgp],
                       capture_output=True, text=True)
    return r, out_dir, cfgp


def run_exports(cfgp):
    return subprocess.run(_engine_cmd("build_exports") + [cfgp],
                          capture_output=True, text=True)


def jload(p):
    return json.load(open(p, encoding='utf-8'))


def setup():
    shutil.rmtree(A.base, ignore_errors=True)
    os.makedirs(f"{A.base}/workspace/config", exist_ok=True)
    os.makedirs(f"{A.base}/fake-repo/exams", exist_ok=True)
    shutil.copy(f"{os.path.dirname(A.upstream.rstrip('/'))}/config/pipeline.example.yaml",
                f"{A.base}/workspace/config/pipeline.yaml")


# ---------------- 17 ported pilot scenarios ----------------

def scenario_two_column():
    pdf = f"{A.base}/two_column.pdf"
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    q_text(p, 60, 80, ["QUESTION 1", "Left column synthetic stem.", "A. l1", "B. l2",
                       "Correct Answer: A", "Section: (none)", "Explanation"])
    q_text(p, 420, 80, ["QUESTION 2", "Right column synthetic stem.", "A. r1", "B. r2",
                        "Correct Answer: B", "Section: (none)", "Explanation"])
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-2COL")
    rb, out_dir, _ = run_builder(pdf, "SYN-2COL", sha)
    split = jload(f"{out}/extracted/split.json")
    pinned_corrupted = any(not rec["pages"] or "Left column" in rec["stem"] and "Right column" in rec["stem"]
                           for rec in split.values())
    builder_refused = rb.returncode != 0 and "page sets differ" in (rb.stderr + rb.stdout)
    correct_output = rb.returncode == 0 and os.path.isfile(f"{out_dir}/questions/q001.json") \
        and "Left column" in jload(f"{out_dir}/questions/q001.json")["stem"]["raw"] \
        and "Right column" in jload(f"{out_dir}/questions/q002.json")["stem"]["raw"]
    ok = correct_output or (pinned_corrupted and builder_refused)
    report("two_column_text", ok,
           f"pinned: {r.stdout.strip()!r}; pinned_corrupted={pinned_corrupted}; "
           f"builder fail-safe refusal={builder_refused}; correct_output={correct_output} "
           f"(identified pinned-extractor limitation: side-by-side columns interleave by (top,left))")


def scenario_same_xref_two_pages():
    pdf = f"{A.base}/same_xref.pdf"
    img = png_bytes(300, 100, lambda d: d.rectangle([10, 10, 290, 90], outline="black", fill="#eeeeee"))
    doc = fitz.open()
    p1 = doc.new_page(width=792, height=612)
    q_text(p1, 60, 80, ["QUESTION 1", "Same image reused on two pages."])
    p1.insert_image(fitz.Rect(60, 200, 360, 300), stream=img)
    q_text(p1, 60, 330, ["A. one", "B. two", "Correct Answer: A", "Section: (none)", "Explanation"])
    p2 = doc.new_page(width=792, height=612)
    p2.insert_text((60, 60), "Continuation page", fontsize=11)
    p2.insert_image(fitz.Rect(60, 100, 360, 200), stream=img)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-XREF")
    rb, out_dir, _ = run_builder(pdf, "SYN-XREF", sha)
    ok = r.returncode == 0 and rb.returncode == 0
    detail = f"pinned: {r.stdout.strip()!r}; builder exit {rb.returncode}"
    if ok:
        au = jload(f"{out_dir}/asset-usage.json")
        assets = sorted(os.listdir(f"{out_dir}/assets"))
        usages = au["usages"]
        ok = len(assets) == 1 and len(usages) == 2 and len({u["asset"] for u in usages}) == 1 \
            and len({u["usage_id"] for u in usages}) == 2
        detail += f"; assets={len(assets)} usages={len(usages)} unique_assets={len({u['asset'] for u in usages})} " \
                  f"distinct_usage_ids={len({u['usage_id'] for u in usages})}"
    report("same_xref_reused_on_two_pages", ok, detail)


def scenario_raster_vector_tables():
    pdf = f"{A.base}/tables.pdf"
    raster = png_bytes(320, 140, lambda d: (
        d.rectangle([5, 5, 315, 135], outline="black"),
        d.line([5, 50, 315, 50], fill="black"), d.line([5, 95, 315, 95], fill="black"),
        d.text((15, 25), "raster cell r1", fill="black"),
        d.text((15, 70), "raster cell r2", fill="black")))
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    std_question(p, 1, "Tables in raster and vector form.")
    p.insert_image(fitz.Rect(60, 230, 380, 330), stream=raster)
    y = 360
    p.draw_rect(fitz.Rect(60, y, 380, y + 80), color=(0, 0, 0), width=1)
    p.draw_line(fitz.Point(60, y + 40), fitz.Point(380, y + 40), color=(0, 0, 0), width=1)
    p.insert_text((70, y + 25), "vector cell v1", fontsize=10)
    p.insert_text((70, y + 65), "vector cell v2", fontsize=10)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-TBL")
    rb, out_dir, _ = run_builder(pdf, "SYN-TBL", sha)
    ok = r.returncode == 0 and rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        pg = jload(f"{out_dir}/pages/page-0001.json")
        has_raster = len(pg["images"]) == 1
        has_vector = pg["vector_drawings"]["count"] >= 2
        ok = has_raster and has_vector
        detail += f"; raster_images={len(pg['images'])}, vector_drawings={pg['vector_drawings']['count']}"
    report("raster_and_vector_tables", ok, detail)


def scenario_answer_near_question():
    pdf = f"{A.base}/answer_near.pdf"
    qimg = png_bytes(300, 120, lambda d: (
        d.rectangle([5, 5, 295, 115], outline="black"),
        d.text((15, 30), "Answer Area", fill="black"),
        d.text((15, 60), "choice one", fill="black"),
        d.text((15, 85), "choice two", fill="black")))
    aimg = png_bytes(300, 120, lambda d: (
        d.rectangle([5, 5, 295, 115], outline="black"),
        d.text((15, 30), "Answer Area", fill="black"),
        d.text((15, 60), "choice one", fill="black"),
        d.ellipse([12, 55, 120, 75], outline="red", width=3),
        d.text((15, 85), "choice two", fill="black")))
    doc = fitz.open()
    p1 = doc.new_page(width=792, height=612)
    q_text(p1, 60, 80, ["QUESTION 1", "HOTSPOT - Select the answer that correctly completes the sentence."])
    p1.insert_image(fitz.Rect(60, 200, 360, 320), stream=qimg)
    p2 = doc.new_page(width=792, height=612)
    p2.insert_text((60, 60), "Correct Answer: ", fontsize=11)
    p2.insert_text((60, 80), "Section: (none)", fontsize=11)
    p2.insert_image(fitz.Rect(60, 110, 360, 230), stream=aimg)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-NEAR")
    rb, out_dir, _ = run_builder(pdf, "SYN-NEAR", sha)
    ok = r.returncode == 0 and rb.returncode == 0
    detail = f"pinned: {r.stdout.strip()!r}"
    if ok:
        q1 = jload(f"{out_dir}/questions/q001.json")
        roles = sorted(u["role"] for u in q1["media_usages"])
        ok = roles == ["answer_reference", "question_prompt"]
        detail += f"; roles={roles}"
    report("answer_screenshot_near_question_page", ok, detail)


def scenario_blurred_key():
    pdf = f"{A.base}/blurred.pdf"
    qimg = png_bytes(300, 120, lambda d: (
        d.rectangle([5, 5, 295, 115], outline="black"),
        d.text((15, 30), "Answer Area", fill="black"),
        d.text((15, 60), "choice one", fill="black"),
        d.text((15, 85), "choice two", fill="black")))
    aimg = png_bytes(300, 120, lambda d: (
        d.rectangle([5, 5, 295, 115], outline="black"),
        d.text((15, 60), "illegible blurred selection", fill="black"),
        d.ellipse([12, 55, 180, 75], outline="red", width=3)), blur=9)
    doc = fitz.open()
    p1 = doc.new_page(width=792, height=612)
    q_text(p1, 60, 80, ["QUESTION 1", "HOTSPOT - Select the answer that correctly completes the sentence."])
    p1.insert_image(fitz.Rect(60, 200, 360, 320), stream=qimg)
    p2 = doc.new_page(width=792, height=612)
    p2.insert_text((60, 60), "Correct Answer: ", fontsize=11)
    p2.insert_image(fitz.Rect(60, 110, 360, 230), stream=aimg)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-BLUR")
    subprocess.run([sys.executable, f"{A.upstream}/analyze_visual.py", out], capture_output=True, text=True)
    rb, out_dir, _ = run_builder(pdf, "SYN-BLUR", sha)
    ok = rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        unres = jload(f"{out_dir}/unresolved.json")
        flagged = any(i.get("reason_code") == "visual_key_not_machine_readable" and i["item"] == "q001"
                      for i in unres["items"])
        ok = flagged
        detail += f"; visual_key_not_machine_readable flagged={flagged}"
    report("blurred_key_image", ok, detail)


def scenario_ligature():
    pdf = f"{A.base}/ligature.pdf"
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    std_question(p, 1, "This synthetic stem mentions a speci c veri cation case.")
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-LIG")
    rb, out_dir, _ = run_builder(pdf, "SYN-LIG", sha)
    ok = r.returncode == 0 and rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        q1 = jload(f"{out_dir}/questions/q001.json")
        raw_has = "speci c" in q1["stem"]["raw"]
        norm_has = "specific" in q1["stem"]["upstream_normalized"]
        logged = len(q1["stem"]["normalizations"]) > 0
        ok = raw_has and norm_has and logged
        detail += f"; raw_keeps_gap={raw_has}, normalized={norm_has}, normalizations_logged={logged}"
    report("lost_ligature_glyph", ok, detail)


def scenario_yes_no():
    qimg = png_bytes(320, 150, lambda d: (
        d.text((10, 20), "Statements", fill="black"), d.text((200, 20), "Yes", fill="black"),
        d.text((260, 20), "No", fill="black"),
        d.text((10, 60), "synthetic statement one", fill="black"),
        d.text((10, 110), "synthetic statement two", fill="black"),
        d.rectangle([195, 45, 225, 75], outline="black"), d.rectangle([255, 45, 285, 75], outline="black"),
        d.rectangle([195, 95, 225, 125], outline="black"), d.rectangle([255, 95, 285, 125], outline="black")))
    aimg = png_bytes(320, 150, lambda d: (
        d.text((10, 20), "Statements", fill="black"), d.text((200, 20), "Yes", fill="black"),
        d.text((260, 20), "No", fill="black"),
        d.text((10, 60), "synthetic statement one", fill="black"),
        d.text((10, 110), "synthetic statement two", fill="black"),
        d.rectangle([195, 45, 225, 75], outline="black"), d.rectangle([255, 45, 285, 75], outline="black"),
        d.rectangle([195, 95, 225, 125], outline="black"), d.rectangle([255, 95, 285, 125], outline="black"),
        d.rectangle([196, 46, 224, 74], fill="black"), d.rectangle([256, 96, 284, 124], fill="black")))
    pdf = f"{A.base}/yesno.pdf"
    doc = fitz.open()
    p1 = doc.new_page(width=792, height=612)
    q_text(p1, 60, 80, ["QUESTION 1",
                        "HOTSPOT - For each of the following statements, select Yes if the statement is true. Otherwise, select No."])
    p1.insert_image(fitz.Rect(60, 200, 380, 350), stream=qimg)
    p2 = doc.new_page(width=792, height=612)
    p2.insert_text((60, 60), "Correct Answer: ", fontsize=11)
    p2.insert_image(fitz.Rect(60, 90, 380, 240), stream=aimg)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-YN")
    subprocess.run([sys.executable, f"{A.upstream}/analyze_visual.py", out], capture_output=True, text=True)
    rb, out_dir, _ = run_builder(pdf, "SYN-YN", sha)
    ok = rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        q1 = jload(f"{out_dir}/questions/q001.json")
        t = q1["question_type"]["site_format_type"]
        ok = t == "yes_no_matrix"
        detail += f"; type={t}"
    report("yes_no_matrix", ok, detail)


def scenario_dropdown():
    qimg = png_bytes(300, 120, lambda d: (
        d.rectangle([5, 5, 295, 115], outline="black"),
        d.text((15, 30), "Answer Area", fill="black"),
        d.text((15, 60), "daily", fill="black"),
        d.text((15, 85), "weekly", fill="black")))
    aimg = png_bytes(300, 120, lambda d: (
        d.rectangle([5, 5, 295, 115], outline="black"),
        d.text((15, 30), "Answer Area", fill="black"),
        d.text((15, 60), "daily", fill="black"),
        d.ellipse([12, 55, 90, 75], outline="red", width=3),
        d.text((15, 85), "weekly", fill="black")))
    pdf = f"{A.base}/dropdown.pdf"
    doc = fitz.open()
    p1 = doc.new_page(width=792, height=612)
    q_text(p1, 60, 80, ["QUESTION 1", "HOTSPOT - Select the answer that correctly completes the sentence."])
    p1.insert_image(fitz.Rect(60, 200, 360, 320), stream=qimg)
    p2 = doc.new_page(width=792, height=612)
    p2.insert_text((60, 60), "Correct Answer: ", fontsize=11)
    p2.insert_image(fitz.Rect(60, 90, 360, 210), stream=aimg)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-DD")
    subprocess.run([sys.executable, f"{A.upstream}/analyze_visual.py", out], capture_output=True, text=True)
    rb, out_dir, _ = run_builder(pdf, "SYN-DD", sha)
    ok = rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        q1 = jload(f"{out_dir}/questions/q001.json")
        t = q1["question_type"]["site_format_type"]
        ok = t == "inline_dropdown"
        detail += f"; type={t}"
    report("dropdown", ok, detail)


def scenario_drag_drop():
    qimg = png_bytes(320, 140, lambda d: (
        d.text((10, 20), "Tiles", fill="black"),
        d.rectangle([10, 40, 90, 70], outline="black"), d.text((20, 60), "tile1", fill="black"),
        d.rectangle([100, 40, 180, 70], outline="black"), d.text((110, 60), "tile2", fill="black"),
        d.text((10, 100), "Targets", fill="black"),
        d.rectangle([10, 115, 180, 140], outline="black")))
    aimg = png_bytes(320, 80, lambda d: (
        d.rectangle([10, 30, 90, 60], outline="black"), d.text((20, 50), "tile1", fill="black"),
        d.rectangle([10, 62, 180, 78], outline="black")))
    pdf = f"{A.base}/dragdrop.pdf"
    doc = fitz.open()
    p1 = doc.new_page(width=792, height=612)
    q_text(p1, 60, 80, ["QUESTION 1", "DRAG DROP - Match each tile to its target."])
    p1.insert_image(fitz.Rect(60, 200, 380, 340), stream=qimg)
    p2 = doc.new_page(width=792, height=612)
    p2.insert_text((60, 60), "Correct Answer: ", fontsize=11)
    p2.insert_image(fitz.Rect(60, 90, 380, 170), stream=aimg)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-DDROP")
    subprocess.run([sys.executable, f"{A.upstream}/analyze_visual.py", out], capture_output=True, text=True)
    rb, out_dir, _ = run_builder(pdf, "SYN-DDROP", sha)
    ok = rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        q1 = jload(f"{out_dir}/questions/q001.json")
        unres = jload(f"{out_dir}/unresolved.json")
        t = q1["question_type"]["site_format_type"]
        flagged = any(i.get("reason_code") == "question_type_unknown" and i["item"] == "q001"
                      for i in unres["items"])
        ok = (t == "unknown") and flagged
        detail += f"; type={t} (fail-closed unknown, not guessed); unresolved_flagged={flagged}"
    report("drag_drop_fail_closed_unknown", ok, detail)


def scenario_missing_option():
    pdf = f"{A.base}/missing_opt.pdf"
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    std_question(p, 1, "Missing option line synthetic.", options=("A. one", "B. two", "D. four"))
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-MOPT")
    rb, out_dir, _ = run_builder(pdf, "SYN-MOPT", sha)
    ok = r.returncode == 0 and rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        q1 = jload(f"{out_dir}/questions/q001.json")
        labels = [e["label"] for e in q1["options"]["entries"]]
        ok = labels == ["A", "B", "D"]
        detail += f"; labels={labels} (gap preserved, no invented option)"
    report("missing_option_line", ok, detail)


def scenario_blank_key():
    pdf = f"{A.base}/blank_key.pdf"
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    q_text(p, 60, 80, ["QUESTION 1", "Blank key synthetic.", "A. one", "B. two",
                       "Correct Answer: ", "Section: (none)", "Explanation"])
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-BKEY")
    rb, out_dir, _ = run_builder(pdf, "SYN-BKEY", sha)
    ok = rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        q1 = jload(f"{out_dir}/questions/q001.json")
        unres = jload(f"{out_dir}/unresolved.json")
        ok = (q1["answer"]["source_kind"] == "missing" and
              any(i.get("reason_code") == "answer_missing_in_source" and i["item"] == "q001"
                  for i in unres["items"]))
        detail += f"; source_kind={q1['answer']['source_kind']}; flagged missing"
    report("blank_key", ok, detail)


def scenario_mixed_footers():
    pdf = f"{A.base}/footers.pdf"
    doc = fitz.open()
    footers = ["Page 1 of 2 - Synthetic", "Confidential draft footer"]
    for i, f in enumerate(footers):
        p = doc.new_page(width=792, height=612)
        std_question(p, 1 + i, f"Footer test question {i+1}.")
        p.insert_text((60, 590), f, fontsize=9)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-FOOT")
    rb, out_dir, _ = run_builder(pdf, "SYN-FOOT", sha)
    ok = r.returncode == 0 and rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        found = []
        una = 0
        for pgno in (1, 2):
            pg = jload(f"{out_dir}/pages/page-{pgno:04d}.json")
            for run in pg["text_runs"]:
                if run["classification"] == "unassigned":
                    una += 1
                if footers[pgno - 1] in run["text"]:
                    found.append((pgno, run["classification"]))
        ok = len(found) == 2 and una == 0
        detail += f"; footers_recorded={found}; unassigned_runs={una} (nothing lost)"
    report("mixed_footers", ok, detail)


def scenario_rotated():
    pdf = f"{A.base}/rotated.pdf"
    doc = fitz.open()
    p = doc.new_page(width=612, height=792)
    p.set_rotation(90)
    lines = ["QUESTION 1", "Rotated page synthetic stem.", "A. one", "B. two",
             "Correct Answer: A", "Section: (none)", "Explanation"]
    y = 560
    for ln in lines:
        p.insert_text((72, y), ln, fontsize=11, rotate=90)
        y -= 20
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-ROT")
    rb, out_dir, _ = run_builder(pdf, "SYN-ROT", sha)
    ok = r.returncode == 0 and rb.returncode == 0
    detail = f"pinned: {r.stdout.strip()!r}; builder exit {rb.returncode}"
    if ok:
        q1 = jload(f"{out_dir}/questions/q001.json")
        pg = jload(f"{out_dir}/pages/page-0001.json")
        in_bounds = all(0 <= run["bbox_display"][0] <= pg["display_rect"][2] and
                        0 <= run["bbox_display"][1] <= pg["display_rect"][3]
                        for run in pg["text_runs"])
        ok = ("Rotated page" in q1["stem"]["raw"]) and in_bounds and pg["rotation"] == 90
        detail += f"; stem ok={('Rotated page' in q1['stem']['raw'])}; display_rect={pg['display_rect']}; bboxes_in_bounds={in_bounds}"
    report("rotated_page", ok, detail)


def scenario_duplicate_number():
    pdf = f"{A.base}/dupnum.pdf"
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    std_question(p, 1, "First question one.")
    q_text(p, 60, 300, ["QUESTION 1", "Duplicate question one.", "A. x", "B. y",
                        "Correct Answer: A", "Section: (none)", "Explanation"])
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-DUP")
    rb, out_dir, _ = run_builder(pdf, "SYN-DUP", sha)
    ok = rb.returncode != 0 and "markers not sequential" in (rb.stderr + rb.stdout)
    detail = (f"builder exit {rb.returncode}; fail-safe assertion triggered="
              f"{'markers not sequential' in (rb.stderr + rb.stdout)}; "
              f"pinned extractor would silently merge: {r.stdout.strip()!r}")
    report("duplicate_question_number", ok, detail)


def scenario_hidden_text():
    pdf = f"{A.base}/hidden.pdf"
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    std_question(p, 1, "Hidden text synthetic.")
    tw = fitz.TextWriter(p.rect, color=(1, 1, 1))
    font = fitz.Font("helv")
    tw.append(fitz.Point(400, 500), "INVISIBLE_SECRET_TEXT", font=font, fontsize=11)
    tw.write_text(p, render_mode=3)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-HID")
    rb, out_dir, _ = run_builder(pdf, "SYN-HID", sha)
    ok = rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        pg = jload(f"{out_dir}/pages/page-0001.json")
        unres = jload(f"{out_dir}/unresolved.json")
        hid = pg.get("hidden_text_runs", [])
        flagged = any(i.get("reason_code") == "hidden_text_detected" for i in unres["items"])
        ok = len(hid) >= 1 and flagged
        detail += f"; hidden_runs={len(hid)}; unresolved_flagged={flagged}"
    report("hidden_text", ok, detail)


def scenario_malicious_annotation():
    pdf = f"{A.base}/malicious.pdf"
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    std_question(p, 1, "Malicious annotation synthetic.")
    p.insert_text((400, 300), "click here", fontsize=12)
    p.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(395, 285, 470, 305),
                   "uri": "javascript:evilSyntheticPayload()"})
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-MAL")
    rb, out_dir, _ = run_builder(pdf, "SYN-MAL", sha)
    ok = rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        pg = jload(f"{out_dir}/pages/page-0001.json")
        links = pg["links"]
        ok = any("javascript" in str(l.get("uri", "")) for l in links)
        detail += f"; links_recorded={len(links)} (recorded, never executed)"
    report("malicious_annotation_link", ok, detail)


def scenario_password():
    pdf = f"{A.base}/password.pdf"
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    std_question(p, 1, "Encrypted synthetic.")
    doc.save(pdf)
    d2 = fitz.open(pdf)
    d2.save(f"{A.base}/password_enc.pdf", encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="synthetic-owner",
            user_pw="synthetic-user")
    sha = hashlib.sha256(open(f"{A.base}/password_enc.pdf", 'rb').read()).hexdigest()
    r, out = run_pinned(pdf=f"{A.base}/password_enc.pdf", exam="SYN-ENC")
    rb, out_dir, _ = run_builder(f"{A.base}/password_enc.pdf", "SYN-ENC", sha)
    ok = rb.returncode == 2 and "BLOCKED_SOURCE_ENCRYPTED" in (rb.stderr + rb.stdout)
    no_output = not os.path.isdir(out_dir) or not os.listdir(out_dir)
    detail = (f"builder exit {rb.returncode}; BLOCKED_SOURCE_ENCRYPTED reported="
              f"{'BLOCKED_SOURCE_ENCRYPTED' in (rb.stderr + rb.stdout)}; "
              f"no fabricated output={no_output}; pinned extractor exit {r.returncode}")
    report("password_protected_pdf", ok, detail)


# ---------------- 10 new ZAI-EXTRACT-002 scenarios ----------------

def scenario_missing_image_binary():
    """A page-referenced image object stripped of its dimension key (binary unusable) must
    BLOCK the builder loudly (exit 3) instead of crashing or silently skipping the asset."""
    pdf0 = f"{A.base}/missing_img_base.pdf"
    img = png_bytes(200, 80, lambda d: d.rectangle([5, 5, 195, 75], outline="black"))
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    q_text(p, 60, 80, ["QUESTION 1", "Question with an image whose stream will vanish."])
    p.insert_image(fitz.Rect(60, 200, 260, 280), stream=img)
    q_text(p, 60, 330, ["A. one", "B. two", "Correct Answer: A", "Section: (none)", "Explanation"])
    doc.save(pdf0)
    pdf = f"{A.base}/missing_img.pdf"
    d2 = fitz.open(pdf0)
    for x in range(1, d2.xref_length()):
        try:
            if d2.xref_get_key(x, "Subtype")[1] == "/Image":
                d2.xref_set_key(x, "Width", "null")  # image object cannot yield its binary
        except Exception:
            pass
    d2.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-MISSIMG")
    rb, out_dir, _ = run_builder(pdf, "SYN-MISSIMG", sha)
    blocked = rb.returncode == 3 and "BLOCKED_UNEXTRACTABLE_IMAGE_STREAMS" in (rb.stderr + rb.stdout)
    report("missing_image_binary_blocks_loudly", blocked,
           f"builder exit {rb.returncode}; BLOCKED_UNEXTRACTABLE_IMAGE_STREAMS reported="
           f"{'BLOCKED_UNEXTRACTABLE_IMAGE_STREAMS' in (rb.stderr + rb.stdout)}; "
           f"pinned extractor exit {r.returncode}")


def scenario_duplicate_ids_with_gap():
    """Markers 1, 2, 2, 4 (duplicate AND gap) must fail the sequentiality assertion."""
    pdf = f"{A.base}/dup_gap.pdf"
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    std_question(p, 1, "First synthetic.")
    q_text(p, 60, 170, ["QUESTION 2", "Second synthetic.", "A. x", "B. y",
                        "Correct Answer: A", "Section: (none)", "Explanation"])
    q_text(p, 60, 300, ["QUESTION 2", "Duplicate of two.", "A. x", "B. y",
                        "Correct Answer: B", "Section: (none)", "Explanation"])
    q_text(p, 60, 430, ["QUESTION 4", "Gap after duplicate.", "A. x", "B. y",
                        "Correct Answer: A", "Section: (none)", "Explanation"])
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-DUPGAP")
    rb, out_dir, _ = run_builder(pdf, "SYN-DUPGAP", sha)
    refused = rb.returncode != 0 and "markers not sequential" in (rb.stderr + rb.stdout)
    report("duplicate_question_ids_with_gap_fail_safe", refused,
           f"builder exit {rb.returncode}; markers not sequential triggered="
           f"{'markers not sequential' in (rb.stderr + rb.stdout)}; pinned: {r.stdout.strip()!r}")


def scenario_rotated_270():
    pdf = f"{A.base}/rotated270.pdf"
    doc = fitz.open()
    p = doc.new_page(width=612, height=792)
    p.set_rotation(270)
    lines = ["QUESTION 1", "Rotated 270 synthetic stem.", "A. one", "B. two",
             "Correct Answer: A", "Section: (none)", "Explanation"]
    y = 80
    for ln in lines:
        p.insert_text((540, y), ln, fontsize=11, rotate=270)
        y += 20
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-ROT270")
    rb, out_dir, _ = run_builder(pdf, "SYN-ROT270", sha)
    ok = r.returncode == 0 and rb.returncode == 0
    detail = f"pinned exit {r.returncode}; builder exit {rb.returncode}"
    if ok:
        q1 = jload(f"{out_dir}/questions/q001.json")
        pg = jload(f"{out_dir}/pages/page-0001.json")
        in_bounds = all(0 <= run["bbox_display"][0] <= pg["display_rect"][2] and
                        0 <= run["bbox_display"][1] <= pg["display_rect"][3]
                        for run in pg["text_runs"])
        ok = ("Rotated 270" in q1["stem"]["raw"]) and in_bounds and pg["rotation"] == 270
        detail += f"; stem ok; display_rect={pg['display_rect']}; bboxes_in_bounds={in_bounds}"
    report("rotated_270_page", ok, detail)


def scenario_text_insertion_order():
    """Lines inserted into the PDF in scrambled order must still extract in reading order."""
    pdf = f"{A.base}/textorder.pdf"
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    p.insert_text((60, 120), "second line of the synthetic stem.", fontsize=11)   # inserted first
    p.insert_text((60, 100), "first line of the synthetic stem.", fontsize=11)    # inserted second
    p.insert_text((60, 80), "QUESTION 1", fontsize=11)                            # inserted last
    p.insert_text((60, 160), "A. one", fontsize=11)
    p.insert_text((60, 180), "B. two", fontsize=11)
    p.insert_text((60, 200), "Correct Answer: A", fontsize=11)
    p.insert_text((60, 220), "Section: (none)", fontsize=11)
    p.insert_text((60, 240), "Explanation", fontsize=11)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-ORD")
    rb, out_dir, _ = run_builder(pdf, "SYN-ORD", sha)
    ok = r.returncode == 0 and rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        q1 = jload(f"{out_dir}/questions/q001.json")
        raw = q1["stem"]["raw"]
        ok = raw.index("first line") < raw.index("second line")
        detail += f"; stem reading order correct={ok}; raw={raw!r}"
    report("text_insertion_order_reading_order", ok, detail)


def scenario_vector_only_diagram():
    """A question whose exhibit is purely vector (no raster) must not fabricate assets."""
    pdf = f"{A.base}/vectoronly.pdf"
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    std_question(p, 1, "Interpret the purely vector diagram below.")
    p.draw_rect(fitz.Rect(60, 250, 300, 350), color=(0, 0, 0.8), width=2)
    p.draw_line(fitz.Point(60, 300), fitz.Point(300, 300), color=(0, 0.8, 0), width=2)
    p.draw_circle(fitz.Point(180, 300), 40, color=(0.8, 0, 0), width=2)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-VEC")
    rb, out_dir, _ = run_builder(pdf, "SYN-VEC", sha)
    ok = r.returncode == 0 and rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        pg = jload(f"{out_dir}/pages/page-0001.json")
        q1 = jload(f"{out_dir}/questions/q001.json")
        assets = os.listdir(f"{out_dir}/assets") if os.path.isdir(f"{out_dir}/assets") else []
        ok = (len(assets) == 0 and len(q1["media_usages"]) == 0
              and pg["vector_drawings"]["count"] >= 3)
        detail += (f"; fabricated_assets={len(assets)} (must be 0); media_usages="
                   f"{len(q1['media_usages'])} (must be 0); vector_drawings="
                   f"{pg['vector_drawings']['count']} (recorded, review-required)")
    report("vector_only_diagram_no_fabricated_assets", ok, detail)


def scenario_multiple_choices_in_screenshot():
    """An answer screenshot showing several marked choices must stay unapproved/private;
    ambiguity must never resolve to a guessed key."""
    qimg = png_bytes(300, 120, lambda d: (
        d.rectangle([5, 5, 295, 115], outline="black"),
        d.text((15, 30), "Answer Area", fill="black"),
        d.text((15, 60), "choice one", fill="black"),
        d.text((15, 85), "choice two", fill="black")))
    aimg = png_bytes(300, 120, lambda d: (
        d.rectangle([5, 5, 295, 115], outline="black"),
        d.text((15, 30), "Answer Area", fill="black"),
        d.text((15, 60), "choice one", fill="black"),
        d.text((15, 85), "choice two", fill="black"),
        d.ellipse([12, 55, 120, 75], outline="red", width=3),
        d.ellipse([12, 80, 120, 100], outline="red", width=3)))   # TWO selections
    pdf = f"{A.base}/multiselect_shot.pdf"
    doc = fitz.open()
    p1 = doc.new_page(width=792, height=612)
    q_text(p1, 60, 80, ["QUESTION 1", "HOTSPOT - Select the answers that apply."])
    p1.insert_image(fitz.Rect(60, 200, 360, 320), stream=qimg)
    p2 = doc.new_page(width=792, height=612)
    p2.insert_text((60, 60), "Correct Answer: ", fontsize=11)
    p2.insert_image(fitz.Rect(60, 90, 360, 210), stream=aimg)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-MULTI")
    subprocess.run([sys.executable, f"{A.upstream}/analyze_visual.py", out], capture_output=True, text=True)
    rb, out_dir, _ = run_builder(pdf, "SYN-MULTI", sha)
    ok = rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        q1 = jload(f"{out_dir}/questions/q001.json")
        sai = jload(f"{out_dir}/source-answer-index.json")["questions"]["q001"]
        cands = q1["answer"]["selection_candidates_unapproved"]
        all_unapproved = all(c.get("approved") is False for c in cands)
        priv_ok = (sai["privacy"] == "private_reviewer_only"
                   and all(u["privacy"] == "private_reviewer_only"
                           for u in q1["media_usages"] if u["role"] == "answer_reference"))
        ok = all_unapproved and priv_ok
        detail += (f"; candidates={len(cands)} all_unapproved={all_unapproved}; "
                   f"sai_privacy={sai['privacy']}; answer usages private_reviewer_only={priv_ok}")
    report("multiple_choices_in_screenshot_stay_unapproved", ok, detail)


def scenario_duplicate_xref_three_pages():
    pdf = f"{A.base}/same_xref3.pdf"
    img = png_bytes(300, 100, lambda d: (
        d.rectangle([10, 10, 290, 90], outline="black", fill="#eeeeee"),
        d.text((20, 50), "shared synthetic", fill="black")))
    doc = fitz.open()
    p1 = doc.new_page(width=792, height=612)
    q_text(p1, 60, 80, ["QUESTION 1", "Shared image on three pages."])
    p1.insert_image(fitz.Rect(60, 200, 360, 300), stream=img)
    q_text(p1, 60, 330, ["A. one", "B. two", "Correct Answer: A", "Section: (none)", "Explanation"])
    for pno in (2, 3):
        p = doc.new_page(width=792, height=612)
        p.insert_text((60, 60), f"Continuation page {pno}", fontsize=11)
        p.insert_image(fitz.Rect(60, 100, 360, 200), stream=img)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-XREF3")
    rb, out_dir, _ = run_builder(pdf, "SYN-XREF3", sha)
    ok = r.returncode == 0 and rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        au = jload(f"{out_dir}/asset-usage.json")
        usages = au["usages"]
        assets = sorted(os.listdir(f"{out_dir}/assets"))
        ok = (len(assets) == 1 and len(usages) == 3
              and len({u["asset"] for u in usages}) == 1
              and len({u["usage_id"] for u in usages}) == 3
              and len({u["page"] for u in usages}) == 3)
        detail += (f"; assets={len(assets)} usages={len(usages)} "
                   f"distinct_usage_ids={len({u['usage_id'] for u in usages})} "
                   f"pages={sorted(u['page'] for u in usages)}")
    report("duplicate_xref_used_on_three_pages", ok, detail)


def scenario_malformed_mime():
    """An image object declaring a JPEG filter over PNG bytes must BLOCK loudly."""
    pdf0 = f"{A.base}/malmime_base.pdf"
    img = png_bytes(200, 80, lambda d: d.rectangle([5, 5, 195, 75], outline="black"))
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    q_text(p, 60, 80, ["QUESTION 1", "Question with a lying image filter."])
    p.insert_image(fitz.Rect(60, 200, 260, 280), stream=img)
    q_text(p, 60, 330, ["A. one", "B. two", "Correct Answer: A", "Section: (none)", "Explanation"])
    doc.save(pdf0)
    pdf = f"{A.base}/malmime.pdf"
    d2 = fitz.open(pdf0)
    for x in range(1, d2.xref_length()):
        try:
            if d2.xref_get_key(x, "Subtype")[1] == "/Image":
                d2.xref_set_key(x, "Filter", "/JPXDecode")  # declared JPX over PNG/flate bytes
        except Exception:
            pass
    d2.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-MIME")
    rb, out_dir, _ = run_builder(pdf, "SYN-MIME", sha)
    blocked = rb.returncode == 3 and "BLOCKED_UNEXTRACTABLE_IMAGE_STREAMS" in (rb.stderr + rb.stdout)
    report("malformed_mime_image_stream_blocks_loudly", blocked,
           f"builder exit {rb.returncode}; BLOCKED reported="
           f"{'BLOCKED_UNEXTRACTABLE_IMAGE_STREAMS' in (rb.stderr + rb.stdout)}; "
           f"pinned extractor exit {r.returncode}")


def scenario_optional_font():
    """Non-embedded (optional) base-14 fonts must extract losslessly."""
    pdf = f"{A.base}/optfont.pdf"
    doc = fitz.open()
    p = doc.new_page(width=792, height=612)
    q_text(p, 60, 80, ["QUESTION 1"], fontname="cour")
    p.insert_text((60, 100), "Courier non-embedded synthetic stem part one.", fontsize=11, fontname="cour")
    p.insert_text((60, 120), "Courier non-embedded synthetic stem part two.", fontsize=14, fontname="cour")
    q_text(p, 60, 150, ["A. one", "B. two", "Correct Answer: A", "Section: (none)", "Explanation"],
           fontname="tiro")
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-FONT")
    rb, out_dir, _ = run_builder(pdf, "SYN-FONT", sha)
    ok = r.returncode == 0 and rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        q1 = jload(f"{out_dir}/questions/q001.json")
        pg = jload(f"{out_dir}/pages/page-0001.json")
        fonts = {run.get("font") for run in pg["text_runs"]}
        stem_ok = "part one" in q1["stem"]["raw"] and "part two" in q1["stem"]["raw"]
        ok = stem_ok and any("Courier" in f for f in fonts)
        detail += f"; stem complete={stem_ok}; fonts recorded={sorted(f for f in fonts if f)}"
    report("optional_non_embedded_fonts_extract_losslessly", ok, detail)


def scenario_answer_privacy_exact():
    """End-to-end privacy: answer-reference images must be exactly private_reviewer_only and
    must not leak (bytes or filename) into the fail-closed site export."""
    qimg = png_bytes(300, 120, lambda d: (
        d.rectangle([5, 5, 295, 115], outline="black"),
        d.text((15, 30), "Answer Area", fill="black"),
        d.text((15, 60), "choice one", fill="black"),
        d.text((15, 85), "choice two", fill="black")))
    aimg = png_bytes(300, 120, lambda d: (
        d.rectangle([5, 5, 295, 115], outline="black"),
        d.text((15, 30), "Answer Area", fill="black"),
        d.text((15, 60), "choice one", fill="black"),
        d.ellipse([12, 55, 120, 75], outline="red", width=3),
        d.text((15, 85), "choice two", fill="black")))
    pdf = f"{A.base}/privacy.pdf"
    doc = fitz.open()
    p1 = doc.new_page(width=792, height=612)
    q_text(p1, 60, 80, ["QUESTION 1", "HOTSPOT - Select the answer that correctly completes the sentence."])
    p1.insert_image(fitz.Rect(60, 200, 360, 320), stream=qimg)
    p2 = doc.new_page(width=792, height=612)
    p2.insert_text((60, 60), "Correct Answer: ", fontsize=11)
    p2.insert_image(fitz.Rect(60, 110, 360, 230), stream=aimg)
    doc.save(pdf)
    sha = hashlib.sha256(open(pdf, 'rb').read()).hexdigest()
    r, out = run_pinned(pdf, "SYN-PRIV")
    rb, out_dir, cfgp = run_builder(pdf, "SYN-PRIV", sha)
    ok = rb.returncode == 0
    detail = f"builder exit {rb.returncode}"
    if ok:
        re_ = run_exports(cfgp)
        q1 = jload(f"{out_dir}/questions/q001.json")
        au = jload(f"{out_dir}/asset-usage.json")
        ans_usages = [u for u in au["usages"] if u["role"] == "answer_reference"]
        privacy_exact = all(u["privacy"] == "private_reviewer_only" for u in ans_usages)
        sai = jload(f"{out_dir}/source-answer-index.json")["questions"]["q001"]
        leak_names, leak_bytes = [], []
        site_dir = f"{out_dir}/export/site-format-v1-draft"
        if os.path.isdir(site_dir):
            for root, _, files in os.walk(site_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    if any(u["asset"] == f for u in ans_usages):
                        leak_names.append(fp)
                    if os.path.getsize(fp) > 0 and open(fp, 'rb').read(64) == \
                            open(f"{out_dir}/assets/{ans_usages[0]['asset']}", 'rb').read(64):
                        leak_bytes.append(fp)
        blockers = jload(f"{site_dir}/export-blockers.json")
        gated = blockers["blocked_questions"] == 1
        ok = (re_.returncode == 0 and privacy_exact and sai["privacy"] == "private_reviewer_only"
              and not leak_names and not leak_bytes and gated)
        detail += (f"; exports exit {re_.returncode}; answer usages privacy_exact={privacy_exact}; "
                   f"sai_privacy={sai['privacy']}; site-export leaks names={leak_names} "
                   f"bytes={leak_bytes}; all questions gated={gated}")
    report("answer_image_privacy_exact_no_export_leak", ok, detail)


def main():
    global A
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="scratch dir for synthetic PDFs and outputs")
    ap.add_argument("--upstream", required=True, help="pinned upstream scripts dir")
    ap.add_argument("--engine", default=None,
                    help="optional legacy engine dir with standalone scripts; default: "
                         "run this package via python -m certpassly.phase1.*")
    ap.add_argument("--report-out")
    ap.add_argument("--date", default="2026-11-13")
    A = ap.parse_args()
    check_dirs = [A.upstream] + ([A.engine] if A.engine else [])
    for p in check_dirs:
        if not os.path.isdir(p):
            print(f"FATAL: directory does not exist: {p}")
            return 2
    os.makedirs(A.base, exist_ok=True)

    setup()
    print("Running adversarial synthetic scenarios (real pinned extractor + real generalized builder):")
    scenario_two_column()
    scenario_same_xref_two_pages()
    scenario_raster_vector_tables()
    scenario_answer_near_question()
    scenario_blurred_key()
    scenario_ligature()
    scenario_yes_no()
    scenario_dropdown()
    scenario_drag_drop()
    scenario_missing_option()
    scenario_blank_key()
    scenario_mixed_footers()
    scenario_rotated()
    scenario_duplicate_number()
    scenario_hidden_text()
    scenario_malicious_annotation()
    scenario_password()
    # --- new ZAI-EXTRACT-002 scenarios ---
    scenario_missing_image_binary()
    scenario_duplicate_ids_with_gap()
    scenario_rotated_270()
    scenario_text_insertion_order()
    scenario_vector_only_diagram()
    scenario_multiple_choices_in_screenshot()
    scenario_duplicate_xref_three_pages()
    scenario_malformed_mime()
    scenario_optional_font()
    scenario_answer_privacy_exact()

    passed = sum(1 for r_ in results if r_["passed"])
    print(f"\n===== ADVERSARIAL SUITE: {passed}/{len(results)} scenarios passed =====")
    out = dict(suite="phase1-extraction adversarial synthetic tests (ZAI-EXTRACT-003 public port: 17 ported + 10)",
               date=A.date,
               synthetic_only=True,
               real_exam_data_used=False,
               tools=dict(pinned_extractor="msaqlainhaneef1/certpassly-exam-pipeline@13dea6bab "
                                           "scripts/extract_owner_pdf.py (unmodified)",
                          visual_draft="scripts/analyze_visual.py (unmodified)",
                          builder=(f"{A.engine}/build_structured_v1.py (legacy standalone engine)"
                                   if A.engine else
                                   "certpassly.phase1.build_structured_v1 (public skill package)")),
               total=len(results), passed=passed, failed=len(results) - passed,
               scenarios=results)
    if A.report_out:
        os.makedirs(os.path.dirname(os.path.abspath(A.report_out)), exist_ok=True)
        json.dump(out, open(A.report_out, "w"), indent=1, ensure_ascii=False)
        print("wrote", A.report_out)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
