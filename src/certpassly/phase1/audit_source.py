#!/usr/bin/env python3
"""Phase 1 extraction: independent read-only source PDF audit, any exam (public toolkit).

Usage: python -m certpassly.phase1.audit_source --pdf <pdf>
                       [--expected-sha256 <hex>] [--expected-bytes <n>]
                       [--marker-regex <re>] [--answer-regex <re>]
                       [--tool-label <label>] [--out <json>]

Verifies source integrity and structure WITHOUT extracting anything:
  - exact bytes / SHA-256 (fails on mismatch with expected values)
  - encryption / password protection
  - page count, per-page geometry/rotation uniformity
  - marker detection (question numbering pattern): count, sequence, duplicates
  - per-marker answer states (typed key vs answer images vs missing)
  - image inventory: unique xrefs, duplicated xrefs across pages, extractable binaries
  - fonts (embedded vs not), annotations/links, hidden text, vector drawings
  - multi-document identity signals (metadata, geometry, marker continuity)

Exit codes: 0 = audit complete (see JSON for verdict), 2 = BLOCKED (hash/encryption
mismatch). This script never modifies the PDF and never fabricates counts; the
advertised filename question count is NOT trusted.
"""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from collections import Counter

import fitz


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def run_audit(argv=None):
    """CLI entry: accepts an argv list (module mode passes sys.argv[1:])."""
    ap = argparse.ArgumentParser(prog="certpassly.phase1.audit_source")
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--expected-sha256")
    ap.add_argument("--expected-bytes", type=int)
    ap.add_argument("--marker-regex", default=r"^QUESTION\s+(\d+)\s*$")
    ap.add_argument("--answer-regex", default=r"^Correct Answers?:\s*(.*)$")
    ap.add_argument("--tool-label", default="tools/phase1-extraction/audit_source.py",
                    help="provenance label recorded in the audit JSON (default keeps the "
                         "historical private-toolkit label for byte-compatible replay)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)

    blocked = []
    size = __import__("os").path.getsize(a.pdf)
    sha = sha256_file(a.pdf)
    if a.expected_sha256 and sha != a.expected_sha256.lower():
        blocked.append(f"sha256 mismatch: got {sha} expected {a.expected_sha256}")
    if a.expected_bytes and size != a.expected_bytes:
        blocked.append(f"byte size mismatch: got {size} expected {a.expected_bytes}")

    doc = fitz.open(a.pdf)
    if doc.is_encrypted or doc.needs_pass:
        blocked.append("PDF is encrypted/password-protected; extraction refused")
        # Fail closed: page-level APIs raise on an unauthenticated encrypted
        # document, so emit the blocked report WITHOUT any page analysis and
        # never fabricate counts. (Found by the public synthetic test suite;
        # the historical private toolkit crashed unhandled here.)
        early = dict(
            schema_version="structured-v1",
            tool=a.tool_label,
            pdf=dict(path=a.pdf, sha256=sha, bytes=size,
                     expected_sha256=a.expected_sha256, expected_bytes=a.expected_bytes),
            verdict="BLOCKED",
            blocked_reasons=blocked,
            pages=None, markers=None, answers=None, images=None, fonts=None,
            links=None, annotations=None, hidden_text_runs=None,
            vector_drawings=None, identity=None, identity_ambiguous=True,
            notes=["Encrypted PDF: no page/text/image analysis was attempted; "
                   "nothing was measured and nothing is fabricated."],
        )
        txt = json.dumps(early, indent=1, ensure_ascii=False)
        if a.out:
            with open(a.out, "w", encoding='utf-8') as f:
                f.write(txt)
        print(txt[:4000])
        return 2

    marker_re = re.compile(a.marker_regex)
    answer_re = re.compile(a.answer_regex)

    # ---- page geometry ----
    pages_geo = []
    for pno in range(doc.page_count):
        p = doc[pno]
        pages_geo.append(dict(page=pno + 1, rotation=p.rotation,
                              mediabox=[round(v, 2) for v in p.mediabox],
                              display=[round(v, 2) for v in p.rect]))
    geo_uniform = len({(g["rotation"], tuple(g["mediabox"])) for g in pages_geo}) == 1

    # ---- text scan: markers, answers ----
    markers = []           # (page, number, text)
    answer_lines = Counter()
    fonts = Counter()
    fonts_not_embedded = Counter()
    hidden_text = 0
    links = 0
    annots = 0
    for pno in range(doc.page_count):
        p = doc[pno]
        d = p.get_text("dict", sort=True)
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            for l in b.get("lines", []):
                for s in l.get("spans", []):
                    t = s["text"].strip()
                    if not t:
                        continue
                    m = marker_re.match(t)
                    if m:
                        markers.append(dict(page=pno + 1, number=int(m.group(1))))
                    if answer_re.match(t):
                        answer_lines["typed"] += 1
                    fonts[s["font"]] += 1
        try:
            for sp in p.get_texttrace():
                if sp.get("type") == 3 and "".join(chr(c[0]) for c in sp.get("chars", [])).strip():
                    hidden_text += 1
        except Exception:
            pass
        links += len(p.get_links())
        annots += len(list(p.annots() or []))
    for f in doc.get_page_fonts(0):
        try:
            name, ext, ftype, enc = f[3], f[1], f[2], f[5]
        except Exception:
            continue
        if ext == "n/a":
            fonts_not_embedded[ftype or name] += 1

    nums = [m["number"] for m in markers]
    seq_ok = nums == list(range(1, len(nums) + 1))
    dup_nums = [n for n, c in Counter(nums).items() if c > 1]

    # ---- image inventory ----
    image_xrefs = {}
    unextractable = []
    page_image_refs = Counter()
    for pno in range(doc.page_count):
        seen = set()
        for info in doc[pno].get_image_info(xrefs=True):
            x = info.get("xref")
            if not isinstance(x, int) or x <= 0 or x in seen:
                continue
            seen.add(x)
            page_image_refs[x] += 1
    for x in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(x, "Subtype")[1] == "/Image":
                try:
                    info = doc.extract_image(x)
                    image_xrefs[x] = dict(ext=info["ext"], width=info["width"],
                                          height=info["height"],
                                          sha256=hashlib.sha256(info["image"]).hexdigest(),
                                          bytes=len(info["image"]))
                except Exception as e:
                    image_xrefs[x] = None
                    unextractable.append(dict(xref=x, error=repr(e)[:200]))
        except Exception:
            pass
    unique_binaries = {v["sha256"] for v in image_xrefs.values() if v}
    dup_xrefs = {x: c for x, c in page_image_refs.items() if c > 1}

    # ---- vector drawings ----
    vector_counts = [len(doc[p].get_drawings()) for p in range(doc.page_count)]

    # ---- multi-document identity signals ----
    identity_signals = dict(
        metadata=doc.metadata,
        geometry_uniform=geo_uniform,
        marker_sequence_contiguous=seq_ok,
        distinct_geometries=len({(g["rotation"], tuple(g["mediabox"])) for g in pages_geo}),
    )
    ambiguous_identity = (not geo_uniform) or (not seq_ok)

    report = dict(
        schema_version="structured-v1",
        tool=a.tool_label,
        pdf=dict(path=a.pdf, sha256=sha, bytes=size,
                 expected_sha256=a.expected_sha256, expected_bytes=a.expected_bytes),
        verdict="BLOCKED" if blocked else "AUDIT_COMPLETE",
        blocked_reasons=blocked,
        pages=dict(count=doc.page_count, geometry=pages_geo[:3] + ["..."] if doc.page_count > 3
                   else pages_geo, geometry_uniform=geo_uniform),
        markers=dict(count=len(markers), sequential_1_to_n=seq_ok,
                     duplicates=dup_nums, first=markers[:2], last=markers[-2:] if markers else []),
        answers=dict(typed_answer_lines=answer_lines["typed"]),
        images=dict(unique_xrefs=len(image_xrefs),
                    extractable=len([v for v in image_xrefs.values() if v]),
                    unextractable=unextractable,
                    unique_binaries=len(unique_binaries),
                    xrefs_used_on_multiple_pages={str(k): v for k, v in dup_xrefs.items()}),
        fonts=dict(distinct=len(fonts), not_embedded=dict(fonts_not_embedded)),
        links=links, annotations=annots, hidden_text_runs=hidden_text,
        vector_drawings=dict(total=sum(vector_counts),
                             pages_with_drawings=sum(1 for c in vector_counts if c)),
        identity=identity_signals,
        identity_ambiguous=ambiguous_identity,
        notes=[
            "Counts above are measured from the actual PDF; the filename's advertised question "
            "count is not used as evidence.",
            "answer states per question (typed vs image vs missing) require the pinned upstream "
            "split; this audit counts raw signals only.",
        ],
    )
    txt = json.dumps(report, indent=1, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding='utf-8') as f:
            f.write(txt)
    print(txt[:4000])
    return 2 if blocked else 0


if __name__ == "__main__":
    sys.exit(run_audit())
