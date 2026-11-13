#!/usr/bin/env python3
"""Map pdftohtml-extracted image files (p-N_M.ext) to actual PDF xrefs by bytes/pixels.

Usage: python -m certpassly.phase1.make_pmap <pdf> <media_src_dir> <out_json>
"""
import fitz, hashlib, json, os, sys
import numpy as np
from PIL import Image
import io


def main(pdf, src_dir, out_json):
    doc = fitz.open(pdf)
    xref_data = {}
    for x in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(x, "Subtype")[1] == "/Image":
                info = doc.extract_image(x)
                xref_data[x] = (info["image"], hashlib.sha256(info["image"]).hexdigest())
        except Exception:
            pass
    mapping = {}
    for f in sorted(os.listdir(src_dir)):
        data = open(f"{src_dir}/{f}", 'rb').read()
        h = hashlib.sha256(data).hexdigest()
        hit = None
        method = None
        for x, (_, xh) in xref_data.items():
            if xh == h:
                hit, method = x, "bytes"
                break
        if hit is None:
            img = Image.open(io.BytesIO(data)).convert("RGB")
            arr = np.asarray(img)
            for x, (raw, _) in xref_data.items():
                try:
                    src = Image.open(io.BytesIO(raw)).convert("RGB")
                    sarr = np.asarray(src)
                    if sarr.shape == arr.shape and np.abs(arr.astype(int) - sarr.astype(int)).max() == 0:
                        hit, method = x, "pixels"
                        break
                except Exception:
                    continue
        if hit is None:
            print(f"WARNING: no xref match for {f}", file=sys.stderr)
            continue
        mapping[f] = dict(xref=hit, method=method)
    json.dump(mapping, open(out_json, "w"), indent=1)
    print(f"mapped {len(mapping)} image files to xrefs")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
