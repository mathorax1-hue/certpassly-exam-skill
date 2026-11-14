#!/usr/bin/env python3
"""Private original-PDF text evidence for flagged structured CertPassly questions.

Compare source-page PDF text/OCR with archived STRUCTURED learner content.
Never conclude full source fidelity from OCR or publish extracted text/images.
No answer-key inspection, authoring, research, or publication.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import tempfile

PAGE_RE = re.compile(r"\bpages\s*\[([\d,\s]+)\]")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}")
SKIP = {"the", "and", "are", "you", "your", "that", "with", "for",
        "from", "this", "each", "which", "select", "answer", "correct",
        "question", "following", "note", "true", "false", "yes", "no",
        "otherwise", "one", "two", "three", "what", "have", "can"}

def pages_from_source(record):
    source = str(record.get("created_source") or "")
    m = PAGE_RE.search(source)
    if not m:
        return []
    pages = [int(x.strip()) for x in m.group(1).split(",")]
    if any(p < 1 or p > 10000 for p in pages) or len(set(pages)) != len(pages):
        raise ValueError("invalid source pages")
    return pages

def flatten_content(v):
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [s for x in v for s in flatten_content(x)]
    if isinstance(v, dict):
        result = []
        for k, x in v.items():
            if k in ("answer", "answer_key", "correct", "answer_raw", "explanations"):
                continue
            if k in ("text", "prompt", "prompt_template", "label", "rows",
                     "columns", "blanks", "choices", "options", "content"):
                result.extend(flatten_content(x))
        return result
    return []

def tokens(text):
    plain = re.sub(r"<[^>]+>", " ", html.unescape(str(text)))
    return {w.lower() for w in WORD.findall(plain) if w.lower() not in SKIP}

def source_page_text(pdf, number, ocr_fallback=True, force=False):
    p = subprocess.run(["pdftotext", "-f", str(number), "-l", str(number),
                        "-layout", "-enc", "UTF-8", str(pdf), "-"],
                       capture_output=True, text=True, errors="replace")
    if p.returncode != 0:
        return "", "PDF_TEXT_ERROR"
    if (len(tokens(p.stdout)) >= 20 and not force) or not ocr_fallback:
        return p.stdout, "PDF_TEXT_LAYER"
    with tempfile.TemporaryDirectory(prefix="certpassly-pdf-qa-") as folder:
        target = Path(folder) / "source"
        r = subprocess.run(["pdftoppm", "-f", str(number), "-l", str(number),
                            "-singlefile", "-r", "155", "-png", str(pdf), str(target)],
                           capture_output=True, text=True, errors="replace")
        if r.returncode != 0 or not target.with_suffix(".png").exists():
            return p.stdout, "PDF_TEXT_NO_OCR_RENDER_FAILED"
        t = subprocess.run(["tesseract", str(target) + ".png", "stdout", "-l", "eng"],
                           capture_output=True, text=True, errors="replace")
        if t.returncode != 0:
            return p.stdout, "PDF_TEXT_NO_OCR_ENGINE_FAILED"
        return p.stdout + "\n" + t.stdout, "PDF_TEXT_PLUS_OCR" if force else "OCR_REFERENCE_ONLY"

def inspect(bank, flagged_keys, pdf, ocr_fallback=True):
    questions = {q["question_key"]: q for q in bank["questions"]}
    evidence_cache = {}
    results = []
    for key in sorted(set(flagged_keys)):
        q = questions.get(key)
        if q is None:
            results.append({"question_key": key, "status": "QUESTION_MISSING"})
            continue
        if q.get("owner_question_replaced") == key:
            results.append({"question_key": key, "status": "ORIGINAL_QUESTION_REPLACEMENT",
                            "source_fidelity_verified": False,
                            "note": "Current authored replacement is not the superseded source PDF."})
            continue
        page_numbers = pages_from_source(q)
        if not page_numbers:
            results.append({"question_key": key, "status": "PAGE_REFERENCE_MISSING"})
            continue
        page_data = []
        for n in page_numbers:
            if n not in evidence_cache:
                evidence_cache[n] = source_page_text(pdf, n, ocr_fallback)
            content, method = evidence_cache[n]
            page_data.append({"page": n, "method": method,
                "text_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "token_count": len(tokens(content))})
        source_tokens = set().union(*(tokens(evidence_cache[p][0]) for p in page_numbers))
        structured = " ".join(flatten_content((q.get("response_schema") or {}).get("content") or {}))
        target = tokens(structured)
        found = sorted(target & source_tokens)
        missing = sorted(target - source_tokens)
        ratio = round(len(found) / len(target), 4) if target else 0.0
        # An answer-area may be rasterized even when the page has ample text.
        # Only low-overlap pages get a second, private OCR pass.
        enhanced = False
        if ocr_fallback and ratio < 0.8:
            for n in page_numbers:
                if evidence_cache[n][1] == "PDF_TEXT_LAYER":
                    evidence_cache[n] = source_page_text(pdf, n, True, force=True)
                    enhanced = True
            if enhanced:
                page_data = [{"page": n, "method": evidence_cache[n][1],
                    "text_sha256": hashlib.sha256(evidence_cache[n][0].encode()).hexdigest(),
                    "token_count": len(tokens(evidence_cache[n][0]))} for n in page_numbers]
                source_tokens = set().union(*(tokens(evidence_cache[p][0]) for p in page_numbers))
                found = sorted(target & source_tokens)
                missing = sorted(target - source_tokens)
                ratio = round(len(found) / len(target), 4) if target else 0.0
        results.append({"question_key": key, "status": "TEXT_EVIDENCE_ONLY_REVIEW_REQUIRED",
            "source_fidelity_verified": False, "pages": page_data,
            "structured_unique_terms": len(target), "matched_unique_terms": len(found),
            "unmatched_unique_terms": len(missing), "approx_token_recall": ratio,
            "unmatched_terms_sample": missing[:30],
            "low_overlap_ocr_recheck": enhanced,
            "note": "OCR or text-layer overlap does NOT validate diagram, cell placement, semantics or missing nontext elements."})
    return {"schema": "certpassly.pdf-text-evidence.v1",
            "source_fidelity_independently_verified": False,
            "answer_keys_researched": False, "simulator_images_generated": False,
            "flagged_question_count": len(set(flagged_keys)), "results": results,
            "status": "REVIEW_REQUIRED",
            "caution": "Text evidence is only one input to a private question-by-question visual source audit."}

def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--pdf", required=True, type=Path)
    a.add_argument("--questions", required=True, type=Path)
    a.add_argument("--cannot-convert", required=True, type=Path)
    a.add_argument("--output", required=True, type=Path)
    a.add_argument("--no-ocr", action="store_true")
    args = a.parse_args()
    bank = json.loads(args.questions.read_text(encoding="utf-8"))
    cannot = json.loads(args.cannot_convert.read_text(encoding="utf-8"))
    flags = cannot.get("question_keys") or [x["question_key"] for x in cannot.get("items") or []]
    report = inspect(bank, flags, args.pdf, not args.no_ocr)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"review_required": report["flagged_question_count"],
                      "evidence_records": len(report["results"]), "status": report["status"]}))

if __name__ == "__main__":
    main()
