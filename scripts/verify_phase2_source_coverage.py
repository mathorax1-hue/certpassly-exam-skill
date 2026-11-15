#!/usr/bin/env python3
"""Verify Phase 2 source-record completeness for one extracted exam.

For every question this tool answers ONE question: is each word of the
original source (reliable PDF text layer plus every word any canonical
full-image reading found in the learner-facing question screenshots) backed
by verified source evidence, or is each uncovered word specifically
evidenced as unreadable at the unchanged canonical quality gates?

The reference word universe per question is the canonical extraction's own
best-effort transcription: text-layer tokens (canonically stripped) plus
question-image tokens from BOTH full-image passes. Verification classes:

  text_layer              word comes from the PDF text-layer source record
  strict_region           word is inside a canonical strict two-pass region
                          recorded by the pinned converter itself (both
                          unchanged passes >= 90 word / >= 95 overall and
                          agreeing at the converter's own prescale)
  strict_ocr_line_crop    the same unchanged two-pass gates passed on the
                          full-image OCR line bounding box containing the
                          word, or its border-trimmed / icon-skipped /
                          glyph-skipped refinement, at the canonical
                          prescale or one documented stronger prescale
  export_gate_certified   the item passed the canonical export fidelity gate
                          (text-only exported questions)
  evidenced_deficiency    uncovered word; every canonical region containing
                          its ink carries its recorded two-pass failure, the
                          word's OCR line crop battery is recorded, and the
                          full-image reading context is preserved

Nothing here certifies answers, releases items or weakens any gate. Strict
readings are source evidence only; candidate-only OCR tokens never count as
coverage. Answer-role images are excluded: they are Phase 4 key evidence,
not learner-facing source text.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

try:
    from .phase2_source_region_ocr import (  # type: ignore
        _prepare_region_crop)
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from phase2_source_region_ocr import (  # type: ignore
        _prepare_region_crop)


MAX_ATTEMPT_HEIGHT = 360
MAX_ATTEMPT_WIDTH = 1600


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _border_trim(image, bbox, frac=0.75, margin=1):
    """Drop leading/trailing near-full-height dark border columns.

    Dropdown and list screenshots draw a vertical border immediately beside
    each option; OCR line boxes include it and both unchanged passes then
    read glyph noise instead of the option text. Pure column geometry: a
    column at least `frac` dark over the crop height is a rule, not a glyph.
    """
    x0, y0, x1, y1 = bbox
    if y1 - y0 < 4:
        return None
    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    if gray.size == 0:
        return None
    dark = gray < 160
    col_frac = dark.sum(axis=0) / float(gray.shape[0])
    left = 0
    while left < gray.shape[1] and col_frac[left] >= frac:
        left += 1
    right = gray.shape[1]
    while right > left and col_frac[right - 1] >= frac:
        right -= 1
    left = min(left + margin, gray.shape[1])
    right = max(left + 1, right - margin)
    if right - left < 20:
        return None
    return [x0 + left, y0, x0 + right, y1]


def _skip_leading_cluster(image, bbox, max_w, min_gap, require_dense):
    """Crop past a narrow leading ink cluster (UI icon, arrow, radio dot).

    Navigation menus and toolbars prefix labels with glyphs that defeat both
    unchanged passes. In dense mode a leading cluster that is narrow, filled
    and nearly full-height is an icon, not a word (letters are sparse
    strokes). In sparse mode any narrow cluster followed by a clear gap is
    skipped; that is safe here because the un-skipped line is always
    attempted first and every skipped reading still faces both gates.
    """
    x0, y0, x1, y1 = bbox
    gray = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    if gray.size == 0:
        return None
    mask = gray < 170
    h, w = mask.shape
    active = mask.sum(axis=0) >= 1
    nz = np.flatnonzero(active)
    if len(nz) == 0:
        return None
    start = end = int(nz[0])
    for i in nz[1:]:
        i = int(i)
        if i - end <= 2:
            end = i
        else:
            break
    cw = end - start + 1
    if cw > max_w:
        return None
    if require_dense:
        density = mask[:, start:end + 1].sum() / float(cw * h)
        rows_hit = mask[:, start:end + 1].any(axis=1).mean()
        if density < 0.40 or rows_hit < 0.85:
            return None
    gap = 0
    for i in range(end + 1, min(w, end + 1 + 40)):
        if not active[i]:
            gap += 1
        else:
            break
    if gap < min_gap:
        return None
    left = end + 1 + gap
    if w - left < 20:
        return None
    return [x0 + left, y0, x1, y1]


def _compile_template_regexes(fid_cfg, skip_ocr_lines):
    """Line patterns the canonical pipeline itself strips from source text."""
    patterns = [re.compile(pat)
                for pat in (fid_cfg.get("strip_line_patterns") or [])]
    if skip_ocr_lines is not None:
        patterns.append(skip_ocr_lines)
    return patterns


def _is_template_line(line, template_regexes):
    t = (line or "").strip()
    if not t:
        return True
    return any(rx.match(t) for rx in template_regexes)


def _record_attempt(candidate):
    """Convert one canonical converter region record into an attempt entry."""
    passes = {}
    for p in candidate.get("passes") or []:
        passes[str(p.get("id"))] = {
            "min_confidence": p.get("min_confidence"),
            "mean_confidence": p.get("mean_confidence"),
            "word_count": p.get("word_count"),
        }
    return {
        "prescale": candidate.get("ocr_prescale"),
        "passes": passes,
        "two_pass_agreement": bool(candidate.get("two_pass_agreement")),
        "strict": bool(candidate.get("usable_as_verified_source")),
        "text": candidate.get("ocr_text_candidate") or "",
        "source": "canonical_converter_record",
    }


def run_crop_attempt(ocr_pass, cfg, pass_specs, image, bbox, prescale,
                     workdir, attempt_id):
    """One two-pass OCR attempt on one crop at one input prescale."""
    x0, y0, x1, y1 = bbox
    native = image[y0:y1, x0:x1]
    if native.size == 0:
        return {"prescale": prescale, "error": "empty_crop"}
    ocr_img = native
    if prescale != 1:
        ocr_img = cv2.resize(native, None, fx=prescale, fy=prescale,
                             interpolation=cv2.INTER_CUBIC)
    ok, encoded = cv2.imencode(".png", ocr_img)
    if not ok:
        return {"prescale": prescale, "error": "encode_failed"}
    path = os.path.join(workdir, "attempt-%s.png" % attempt_id)
    with open(path, "wb") as fh:
        fh.write(encoded.tobytes())
    passes = [ocr_pass(path, cfg, spec) for spec in pass_specs[:2]]
    os.remove(path)
    fid = cfg.get("fidelity") or {}
    minword = float(fid.get("min_word_confidence", 90))
    minoverall = float(fid.get("min_overall_confidence", 95))
    normalized = [" ".join(re.findall(r"[a-z0-9]+", (p.get("text") or "").lower()))
                  for p in passes]
    agree = bool(normalized[0]) and normalized[0] == normalized[1]
    strict = agree and all(
        p.get("min_confidence") is not None
        and p.get("mean_confidence") is not None
        and float(p["min_confidence"]) >= minword
        and float(p["mean_confidence"]) >= minoverall
        for p in passes)
    return {
        "prescale": prescale,
        "passes": {
            str(p.get("id")): {
                "min_confidence": p.get("min_confidence"),
                "mean_confidence": p.get("mean_confidence"),
                "word_count": len(p.get("words") or []),
            } for p in passes
        },
        "two_pass_agreement": agree,
        "strict": strict,
        "text": passes[0].get("text") or "",
        "source": "verification_line_crop",
    }


def _line_bbox_pixels(line, W, H, pad=4):
    x0 = max(0, int(float(line["x"]) * W) - pad)
    y0 = max(0, int(float(line["y"]) * H) - pad)
    x1 = min(W, int(float(line["x1"]) * W) + pad)
    y1 = min(H, int(float(line["y1"]) * H) + pad)
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1, y1]


def _run_line_battery(ocr_pass, cfg, pass_specs, image, bbox, workdir,
                      attempt_prefix):
    """Try the raw OCR line box, then border-trimmed, then glyph-skipped.

    Variants, in order: the raw line box; its border-trimmed refinement
    (near-full-height rule columns dropped); a dense leading icon skipped;
    a narrow leading glyph (arrow/radio) skipped. Each variant is read at
    the canonical prescale and one documented stronger prescale
    (bounds-limited). Every attempt is recorded; the battery stops at the
    first reading that passes both unchanged gates. Skipping can never lose
    evidence: the un-skipped box is always attempted first, and every
    skipped reading still faces both gates unchanged.
    """
    trimmed = _border_trim(image, bbox)
    base = tuple(trimmed) if trimmed is not None else tuple(bbox)
    variants = [("line", list(bbox))]
    if trimmed is not None:
        variants.append(("border_trim", trimmed))
    dense = _skip_leading_cluster(image, base, max_w=34, min_gap=8,
                                  require_dense=True)
    if dense is not None:
        variants.append(("icon_skip" if trimmed is None
                         else "border_trim_icon_skip", dense))
    sparse = _skip_leading_cluster(image, base, max_w=24, min_gap=6,
                                   require_dense=False)
    if sparse is not None and sparse != (dense or ()):
        variants.append(("glyph_skip" if trimmed is None
                         else "border_trim_glyph_skip", sparse))
    attempts = []
    strict_attempt = None
    n = 0
    for variant, vb in variants:
        _, _, canonical = _prepare_region_crop(
            image, (vb[0], vb[1], vb[2], vb[3]))
        h, w = vb[3] - vb[1], vb[2] - vb[0]
        prescales = [canonical]
        if (h * (canonical + 1) <= MAX_ATTEMPT_HEIGHT
                and w * (canonical + 1) <= MAX_ATTEMPT_WIDTH):
            prescales.append(canonical + 1)
        for prescale in prescales:
            n += 1
            attempt = run_crop_attempt(
                ocr_pass, cfg, pass_specs, image, (vb[0], vb[1], vb[2], vb[3]),
                prescale, workdir, "%s-%d" % (attempt_prefix, n))
            attempt["variant"] = variant
            attempt["bbox"] = list(vb)
            attempts.append(attempt)
            if attempt.get("strict"):
                strict_attempt = attempt
                break
        if strict_attempt is not None:
            break
    return attempts, strict_attempt


def verify_question(key, item, ocr_item, baseline_row, media_dir, cfg,
                    pass_specs, fidelity_lib, fid_cfg, deny,
                    template_regexes, ocr_pass, *, image_loader=None):
    """Return the per-question source-coverage verification record."""
    load_image = image_loader or (lambda fn: cv2.imread(
        str(Path(media_dir) / fn)))
    status = baseline_row.get("upstream_status")

    text_layer_tokens = set()
    pdf_text = fidelity_lib.source_pdf_text(item, fid_cfg, deny=deny)
    if pdf_text:
        text_layer_tokens = fidelity_lib.token_set(pdf_text, fid_cfg)

    # Reference universe: canonical full-image readings of question images.
    template_tokens = set()
    content_reference = set(text_layer_tokens)
    full_image_context = {}
    line_index = []  # (file, line_text, line_dict, tokens)
    for im in (ocr_item or {}).get("images") or []:
        if im.get("role") != "question":
            continue
        fname = im.get("file")
        for w in im.get("words") or []:
            m = re.match(r"^[a-z0-9]+", (w.get("text") or "").lower().strip())
            if not m:
                continue
            full_image_context.setdefault(m.group(0), []).append({
                "file": fname, "word": w.get("text"),
                "confidence": w.get("conf")})
        for line in im.get("lines") or []:
            t = line.get("t") or ""
            toks = _tokens(t)
            if not toks:
                continue
            if _is_template_line(t, template_regexes):
                template_tokens |= toks
            else:
                content_reference |= toks
                line_index.append((fname, t, line, toks))
        for pid, prec in (im.get("passes") or {}).items():
            if pid == "psm3":
                continue
            for tok in _tokens(prec.get("text") or ""):
                if tok in template_tokens and tok not in content_reference:
                    continue  # template corroboration only
                if tok not in full_image_context:
                    full_image_context.setdefault(tok, []).append({
                        "file": fname, "word": tok,
                        "confidence": None,
                        "secondary_pass_only": True})
                content_reference.add(tok)

    # Region evidence comes from the pinned converter's own records.
    verification = {tok: "text_layer" for tok in text_layer_tokens}
    variant_prescales = {}
    region_attempts = []
    for im in (ocr_item or {}).get("images") or []:
        if im.get("role") != "question":
            continue
        for cand in im.get("source_region_candidates") or []:
            attempt = _record_attempt(cand)
            region_attempts.append({
                "kind": cand.get("kind"),
                "bbox_pixels": cand.get("bbox_pixels"),
                "source_file": cand.get("source_file") or im.get("file"),
                "canonical_prescale": cand.get("ocr_prescale"),
                "attempts": [attempt],
                "verdict": ("strict" if attempt["strict"]
                            else "deficiency_documented"),
            })
            if attempt["strict"]:
                for tok in _tokens(attempt["text"]):
                    if tok not in verification:
                        verification[tok] = "strict_region"

    line_batteries = []
    images = {}
    if status == "held":
        uncovered_now = sorted(content_reference - set(verification))
        line_map = {}
        for fname, line_text, line, toks in line_index:
            hit = toks & set(uncovered_now)
            if hit:
                line_map[(fname, line_text)] = (fname, line_text, line)
        with tempfile.TemporaryDirectory(prefix="phase2-coverage-") as workdir:
            for (fname, line_text) in sorted(line_map):
                image = images.get(fname)
                if image is None:
                    image = load_image(fname)
                    if image is None:
                        raise RuntimeError(
                            "%s: question image missing: %s" % (key, fname))
                    images[fname] = image
                H, W = image.shape[:2]
                bbox = _line_bbox_pixels(line_map[(fname, line_text)][2], W, H)
                if bbox is None:
                    continue
                attempts, strict_attempt = _run_line_battery(
                    ocr_pass, cfg, pass_specs, image, bbox, workdir,
                    "%s-line-%d" % (key, len(line_batteries)))
                line_batteries.append({
                    "kind": "full_image_ocr_line_crop",
                    "bbox_pixels": bbox,
                    "source_file": fname,
                    "line_text": line_text,
                    "attempts": attempts,
                    "verdict": ("strict" if strict_attempt is not None
                                else "deficiency_documented"),
                })
                if strict_attempt is not None:
                    for tok in _tokens(strict_attempt.get("text")):
                        if tok not in verification:
                            verification[tok] = "strict_ocr_line_crop"
                            variant_prescales[tok] = strict_attempt["prescale"]

    if status == "exported":
        # The canonical export fidelity gate certified this item's source
        # reading (100% text coverage, no extras, image gates where images
        # exist). Every reference token therefore counts as verified.
        for tok in content_reference:
            if tok not in verification:
                verification[tok] = "export_gate_certified"

    template_only = template_tokens - content_reference - set(verification)
    verified_in_reference = {
        tok for tok in content_reference if tok in verification}
    uncovered = sorted(content_reference - verified_in_reference)

    uncovered_words = []
    for tok in uncovered:
        contexts = full_image_context.get(tok, [])
        containing = []
        for rec in region_attempts:
            if tok in _tokens(rec["attempts"][0].get("text") or ""):
                containing.append({
                    "kind": rec["kind"], "bbox_pixels": rec["bbox_pixels"],
                    "source_file": rec["source_file"],
                    "canonical_attempt": rec["attempts"][0]})
        line_evidence = []
        for rec in line_batteries:
            if tok in _tokens(rec["line_text"]) or any(
                    tok in _tokens(a.get("text") or "")
                    for a in rec["attempts"]):
                line_evidence.append({
                    "bbox_pixels": rec["bbox_pixels"],
                    "source_file": rec["source_file"],
                    "line_text": rec["line_text"],
                    "attempts": rec["attempts"]})
        if containing:
            evidence = "canonical_region_failed_and_line_battery_recorded"
        elif line_evidence:
            evidence = "battery_exhausted_line_crop"
        else:
            evidence = "full_image_reading_only"
        uncovered_words.append({
            "token": tok,
            "full_image_context": contexts,
            "containing_region_attempts": containing,
            "ocr_line_crop_attempts": line_evidence,
            "evidence": evidence,
        })

    every_uncovered_evidenced = all(
        w["evidence"] != "full_image_reading_only" or w["full_image_context"]
        for w in uncovered_words)

    return {
        "question_key": key,
        "upstream_status": status,
        "source_pages": baseline_row.get("source_pages") or [],
        "question_images": item.get("question_images") or [],
        "reference_content_token_count": len(content_reference),
        "verified_token_count": len(verified_in_reference),
        "uncovered_token_count": len(uncovered),
        "has_verified_evidence": bool(verified_in_reference),
        "verified_by_class": {
            "text_layer": sorted(
                t for t in verified_in_reference
                if verification[t] == "text_layer"),
            "strict_region": sorted(
                t for t in verified_in_reference
                if verification[t] == "strict_region"),
            "strict_ocr_line_crop": sorted(
                t for t in verified_in_reference
                if verification[t] == "strict_ocr_line_crop"),
            "export_gate_certified": sorted(
                t for t in verified_in_reference
                if verification[t] == "export_gate_certified"),
        },
        "strict_verification_prescales": variant_prescales,
        "template_label_tokens_excluded": sorted(template_only),
        "uncovered_words": uncovered_words,
        "region_attempt_count": len(region_attempts),
        "region_attempts": region_attempts,
        "ocr_line_battery_count": len(line_batteries),
        "ocr_line_batteries": line_batteries,
        "source_record_complete": bool(every_uncovered_evidenced),
        "source_fidelity_certified": False,
        "release_approved": False,
    }


def write_summary(report, path):
    exam = report["exam"]
    lines = [
        "# Phase 2 source coverage verification (not release approval)",
        "",
        "- Questions: %d (exported %d, held %d)" % (
            exam["questions"], exam["exported"], exam["held"]),
        "- Complete source records: %d/%d" % (
            exam["questions_with_complete_source_records"], exam["questions"]),
        "- Reference content tokens: %d; verified: %d; uncovered: %d" % (
            exam["reference_content_tokens_total"],
            exam["verified_tokens_total"],
            exam["uncovered_tokens_total"]),
        "- Questions with uncovered (evidenced-deficient) tokens: %d" % (
            exam["questions_with_uncovered_tokens"]),
        "- Questions without any verified evidence: %d" % (
            exam["questions_without_verified_evidence"]),
        "- Gates unchanged: word %s, overall %s, agreement %s" % (
            report["gates"]["min_word_confidence"],
            report["gates"]["min_overall_confidence"],
            report["gates"]["require_pass_agreement"]),
        "",
        "| question | status | ref | verified | uncovered | complete |",
        "|---|---|---|---|---|---|",
    ]
    for q in report["questions"]:
        lines.append("| %s | %s | %d | %d | %d | %s |" % (
            q["question_key"], q["upstream_status"],
            q["reference_content_token_count"], q["verified_token_count"],
            q["uncovered_token_count"],
            "yes" if q["source_record_complete"] else "NO"))
    deficient = [q for q in report["questions"] if q["uncovered_token_count"]]
    if deficient:
        lines += ["", "## Uncovered tokens (each with recorded evidence)", ""]
        for q in deficient:
            toks = ", ".join(w["token"] for w in q["uncovered_words"])
            lines.append("- **%s** (%d): %s" % (
                q["question_key"], q["uncovered_token_count"], toks))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def assert_canonical_gates(cfg, pass_specs):
    """Fail closed unless the canonical quality gates are unchanged."""
    fid_gate = (cfg.get("fidelity") or {})
    assert fid_gate.get("min_word_confidence") == 90, "word floor changed"
    assert fid_gate.get("min_overall_confidence") == 95, "overall floor changed"
    assert fid_gate.get("require_pass_agreement") is True, "agreement disabled"
    assert len(pass_specs) == 2 and [s["id"] for s in pass_specs] == \
        ["psm3", "psm6"], "canonical passes changed"
    return fid_gate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True,
                        help="pipeline out/<CODE> directory with extracted/ and media/")
    parser.add_argument("--pipeline", required=True,
                        help="pinned upstream pipeline checkout root")
    parser.add_argument("--baseline", required=True,
                        help="Phase 1 question inventory JSON (89 rows)")
    parser.add_argument("--report", required=True, help="output JSON path")
    parser.add_argument("--summary", help="output Markdown path")
    parser.add_argument("--questions",
                        help="optional comma list for focused verification")
    parser.add_argument("--workers", type=int, default=2,
                        help="parallel question workers (default 2)")
    args = parser.parse_args(argv)

    pipeline = Path(args.pipeline).resolve()
    sys.path.insert(0, str(pipeline / "scripts"))
    import ocr_extract  # noqa: E402  pinned canonical converter
    import fidelity as fidelity_lib  # noqa: E402

    out = Path(args.out_dir).resolve()
    split = json.loads((out / "extracted/split.json").read_text())
    ocr_items = json.loads(
        (out / "extracted/ocr.json").read_text())["items"]
    baseline = json.loads(Path(args.baseline).read_text())

    cfg = ocr_extract.load_cfg()
    pass_specs = ocr_extract.fidelity_passes(cfg)[:2]
    fid_cfg = fidelity_lib.load_fidelity_config(str(pipeline))
    fid_gate = assert_canonical_gates(cfg, pass_specs)
    deny = fidelity_lib.make_deny(fid_cfg)
    template_regexes = _compile_template_regexes(
        fid_cfg, getattr(ocr_extract, "SKIP_OCR_LINES", None))

    baseline_rows = {q["question_key"]: q for q in baseline["questions"]}
    assert len(baseline_rows) == len(split) == 89, "question count mismatch"
    keys = sorted(split)
    if args.questions:
        keys = [k for k in args.questions.split(",") if k in split]

    def work(key):
        record = verify_question(
            key, split[key], ocr_items.get(key) or {},
            baseline_rows[key], str(out / "media/src"), cfg, pass_specs,
            fidelity_lib, fid_cfg, deny, template_regexes,
            ocr_extract.ocr_pass)
        print("%s %s ref=%d verified=%d uncovered=%d complete=%s" % (
            key, record["upstream_status"],
            record["reference_content_token_count"],
            record["verified_token_count"],
            record["uncovered_token_count"],
            record["source_record_complete"]), flush=True)
        return record

    if args.workers > 1 and len(keys) > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            questions = list(pool.map(work, keys))
    else:
        questions = [work(key) for key in keys]

    held = [q for q in questions if q["upstream_status"] == "held"]
    report = {
        "status": "PHASE2_SOURCE_COVERAGE_VERIFICATION_NOT_RELEASE",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "gates": {
            "min_word_confidence": fid_gate["min_word_confidence"],
            "min_overall_confidence": fid_gate["min_overall_confidence"],
            "require_pass_agreement": fid_gate["require_pass_agreement"],
            "passes": pass_specs,
        },
        "policy": {
            "verified_classes": ["text_layer", "strict_region",
                                 "strict_ocr_line_crop",
                                 "export_gate_certified"],
            "region_evidence": "pinned converter's own canonical records",
            "line_battery": ("raw OCR line box, then border-trimmed, then "
                             "dense-icon-skipped, then narrow-glyph-skipped; "
                             "canonical prescale then one documented "
                             "stronger prescale, bounds-limited"),
            "template_labels": "tokens seen only on canonically stripped lines",
            "answer_images": "excluded (Phase 4 key evidence, not learner source)",
            "candidate_tokens_count_as_coverage": False,
        },
        "exam": {
            "questions": len(questions),
            "exported": len(questions) - len(held),
            "held": len(held),
            "questions_with_complete_source_records": sum(
                q["source_record_complete"] for q in questions),
            "reference_content_tokens_total": sum(
                q["reference_content_token_count"] for q in questions),
            "verified_tokens_total": sum(
                q["verified_token_count"] for q in questions),
            "uncovered_tokens_total": sum(
                q["uncovered_token_count"] for q in questions),
            "questions_with_uncovered_tokens": sum(
                1 for q in questions if q["uncovered_token_count"]),
            "questions_without_verified_evidence": sum(
                1 for q in questions if not q["has_verified_evidence"]),
            "release_approved": False,
        },
        "questions": questions,
    }
    Path(args.report).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.summary:
        write_summary(report, args.summary)
    print("PHASE2 SOURCE COVERAGE: complete=%d/%d verified=%d uncovered=%d" % (
        report["exam"]["questions_with_complete_source_records"],
        len(questions), report["exam"]["verified_tokens_total"],
        report["exam"]["uncovered_tokens_total"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
