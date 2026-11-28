#!/usr/bin/env python3
"""Benchmark OCR and small vision models on exam page images.

Runs each available model on a set of images and writes a JSON report and a
markdown table with words, confidence, time, peak RAM, and a structure score.

Models, all optional and each guarded so a missing model does not fail the run:
- tesseract: system Tesseract, psm 6 (primary engine).
- rapidocr: rapidocr-onnxruntime (ONNX, fallback engine).
- paddleocr: paddleocr 2.8.1 with paddlepaddle 2.6.2 (pin avoids the OneDNN error
  seen with paddleocr 3.7.0 and paddlepaddle 3.3.1). Uses the 2.x ocr() API;
  predict() is a 3.x addition and does not exist in 2.8.1.
- doctr: docTR via python-doctr[torch]==0.10.0. PyPI "doctr" is an unrelated
  package; the real one is "python-doctr". In 0.10.0 the DocumentFile import
  works again, so images go through doctr.io as before.
- florence2: microsoft/Florence-2-base via transformers. The remote code is
  older than transformers 4.57, so it loads with attn_implementation="eager"
  and trust_remote_code=True. It loads in float32, not bf16: on the CPU
  runner bf16 weights clash with the float32 inputs. If that still fails,
  the native port "florence-community/Florence-2-base" with
  AutoModelForImageTextToText is the fallback. Needs einops and timm
  installed (the workflow installs them).
- smoldocling: ds4sd/SmolDocling-256M-preview via transformers. It is an
  Idefics3 vision-language model, so it loads with AutoModelForImageTextToText,
  not AutoModelForCausalLM. The prompt must carry an image token, so it is
  built with processor.apply_chat_template and an {"type": "image"} item.
- gotocr: stepfun-ai/GOT-OCR-2.0-hf via transformers. The plain
  stepfun-ai/GOT-OCR2_0 repo is remote-code only and has no processor class,
  so the native -hf repo is used with AutoProcessor and
  AutoModelForImageTextToText (no trust_remote_code). The prompt is empty on
  purpose: the native processor builds its own default OCR query with the
  image tokens, and passing text would drop them. Needs verovio installed
  (the workflow installs it).
- qwen2vl: Qwen/Qwen2-VL-2B-Instruct via transformers, bf16 if it fits. It is
  a vision-language model, so it loads with AutoModelForImageTextToText.
  The prompt must carry an image token, so it is built with
  processor.apply_chat_template and an {"type": "image"} item. Images are
  resized so the long side is at most 1024 to save RAM.
  The workflow also installs accelerate and qwen-vl-utils.

Structure scoring. For each image the manifest names a kind. The script checks
whether the model output contains the structural markers for that kind:
- matrix (Yes/No grid): output contains both "Yes" and "No" (2 points), one of
  them (1 point), or neither (0 points).
- dropdown: output contains a selection marker. This is heuristic; the script
  records the raw output and marks the structure as "manual" for a human to
  score from the saved output.
- dragdrop: output contains paired items. Heuristic; recorded as "manual".
- hotspot: output describes a region. Heuristic; recorded as "manual".
- low_ocr and plain: no structure check; words and confidence only.

No exam text, answer keys, or image content is printed. The report holds image
file names, sha256 prefixes, counts, confidence, time, RAM, and structure
scores only. Raw model output text is saved to the output directory for human
review, not printed to the log.

Usage:
    python3 scripts/ocr_bench.py --images <dir> --manifest <manifest.json> \
        --out <outdir> [--models tesseract,rapidocr] [--limit 10]

The manifest is a JSON list of {"kind": str, "question_key": str,
"image": str, "file": str}. The images directory holds the image files named
in the manifest. The output directory receives bench.json and bench.md, plus
one raw output text file per model per image.

Exit codes: 0 when the report is written (even if some models failed to load),
1 on a usage error or when no image could be read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import resource
import subprocess
import sys
import time
from pathlib import Path

# Pinned versions (Exam round 2 reply, updated with Exam's fixes). PaddleOCR
# 2.8.1 with PaddlePaddle 2.6.2 avoids the OneDNN error seen with paddleocr
# 3.7.0 and paddlepaddle 3.3.1. Torch and torchvision CPU wheels must come
# from the same index so they match. docTR is the real python-doctr package
# (PyPI "doctr" is unrelated); the workflow installs
# python-doctr[torch]==0.10.0.
PINNED = {
    "paddlepaddle": "2.6.2",
    "paddleocr": "2.8.1",
    "rapidocr-onnxruntime": "1.4.4",
    "python-doctr": "0.10.0",
    "transformers": "4.57.6",
}

ALL_MODELS = [
    "tesseract",
    "rapidocr",
    "paddleocr",
    "doctr",
    "florence2",
    "smoldocling",
    "gotocr",
    "qwen2vl",
]

# Image kinds and their structure checks.
GRID_KINDS = {"matrix_q", "matrix_a", "matrix_q2"}
DROPDOWN_KINDS = {"dropdown1", "dropdown2", "table_dropdown"}
DRAGDROP_KINDS = {"dragdrop", "dragdrop2"}
HOTSPOT_KINDS = {"hotspot"}


def _sha8(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


def _peak_ram_mb() -> float:
    # ru_maxrss is kilobytes on Linux.
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)


def _structure(kind: str, text: str) -> dict:
    """Score structure markers for one image kind. Returns a small dict."""
    low = text.lower()
    if kind in GRID_KINDS:
        has_yes = "yes" in low
        has_no = "no" in low
        score = int(has_yes) + int(has_no)
        return {"check": "grid_yes_no", "score": score, "max": 2,
                "detail": f"yes={has_yes} no={has_no}"}
    if kind in DROPDOWN_KINDS:
        return {"check": "dropdown_selection", "score": None, "max": None,
                "detail": "manual: read the saved output and score the selected option"}
    if kind in DRAGDROP_KINDS:
        return {"check": "dragdrop_pairs", "score": None, "max": None,
                "detail": "manual: read the saved output and score the item to slot pairs"}
    if kind in HOTSPOT_KINDS:
        return {"check": "hotspot_region", "score": None, "max": None,
                "detail": "manual: read the saved output and score the hotspot region"}
    return {"check": "none", "score": None, "max": None, "detail": "words and confidence only"}


def _run_tesseract(image: Path) -> tuple[str, float]:
    out = subprocess.run(
        ["tesseract", str(image), "stdout", "--psm", "6"],
        capture_output=True, text=True, timeout=120,
    )
    text = out.stdout or ""
    # Mean word confidence from TSV output.
    tsv = subprocess.run(
        ["tesseract", str(image), "stdout", "--psm", "6", "tsv"],
        capture_output=True, text=True, timeout=120,
    )
    confs = []
    for line in (tsv.stdout or "").splitlines()[1:]:
        parts = line.split("\t")
        # TSV columns: level, page_num, block_num, par_num, line_num, word_num,
        # left, top, width, height, conf, text. Conf is index 10, text is 11.
        if len(parts) >= 12 and parts[10].strip():
            try:
                confs.append(float(parts[10]))
            except ValueError:
                pass
    conf = round(sum(confs) / len(confs), 1) if confs else 0.0
    return text, conf


def _run_rapidocr(image: Path) -> tuple[str, float]:
    from rapidocr_onnxruntime import RapidOCR

    eng = RapidOCR()
    result, _elapsed = eng(str(image))
    lines = []
    confs = []
    for _box, txt, conf in (result or []):
        lines.append(txt)
        confs.append(float(conf) * 100.0)
    text = " ".join(lines)
    conf = round(sum(confs) / len(confs), 1) if confs else 0.0
    return text, conf


def _run_paddleocr(image: Path) -> tuple[str, float]:
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(lang="en", use_textline_orientation=False)
    # PaddleOCR 2.8.1 has no predict() method (that is a 3.x addition).
    # The 2.x API is ocr(), which returns a list with one entry per image,
    # each a list of [box, (text, score)] pairs.
    out = ocr.ocr(str(image))
    texts = []
    scores = []
    if out and out[0]:
        for _box, (text, score) in out[0]:
            texts.append(text)
            scores.append(float(score))
    text = " ".join(texts)
    conf = round(sum(scores) / len(scores) * 100.0, 1) if scores else 0.0
    return text, conf


def _run_doctr(image: Path) -> tuple[str, float]:
    # The real docTR package is python-doctr (PyPI "doctr" is unrelated).
    # The workflow installs python-doctr[torch]==0.10.0, which has doctr.io.
    from doctr.io import DocumentFile
    from doctr.models import ocr_predictor

    predictor = ocr_predictor(pretrained=True)
    doc = DocumentFile.from_images([str(image)])
    result = predictor(doc)
    texts = []
    confs = []
    for page in result.pages:
        for block in page.blocks:
            for line in block.lines:
                for word in line.words:
                    texts.append(word.value)
                    confs.append(float(word.confidence) * 100.0)
    text = " ".join(texts)
    conf = round(sum(confs) / len(confs), 1) if confs else 0.0
    return text, conf


def _run_hf_model(model_id: str, image: Path, prompt: str,
                  model_class: str = "causal_lm",
                  chat_template: bool = False,
                  attn_eager: bool = False,
                  trust_remote: bool = True,
                  max_side: int = 0,
                  dtype: str = "bf16") -> tuple[str, float]:
    """Generic Hugging Face vision model runner. Returns text and 0.0 confidence
    (these models do not report per-word confidence).
    model_class is "causal_lm" (Florence-2, GOT-OCR) or "image_text_to_text"
    (SmolDocling and Qwen2-VL, which are vision-language models whose config
    AutoModelForCausalLM does not recognise). chat_template builds the prompt
    with processor.apply_chat_template and an image item, which SmolDocling
    and Qwen2-VL need so the image token count matches the image count.
    attn_eager loads with attn_implementation="eager" (Florence-2 remote code
    is older than transformers 4.57 and has no _supports_sdpa). max_side
    resizes the image so its long side is at most that many pixels. dtype
    is "bf16" except Florence-2, which loads in float32: on the CPU runner
    its bf16 weights clash with the float32 inputs ("Input type (float) and
    bias type (c10::BFloat16) should be the same")."""
    import torch
    from PIL import Image
    from transformers import AutoModelForCausalLM, AutoModelForImageTextToText, AutoProcessor

    img = Image.open(image).convert("RGB")
    if max_side and max(img.size) > max_side:
        scale = max_side / max(img.size)
        img = img.resize((int(img.size[0] * scale), int(img.size[1] * scale)))
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=trust_remote)
    cls = AutoModelForImageTextToText if model_class == "image_text_to_text" else AutoModelForCausalLM
    torch_dtype = torch.float32 if dtype == "fp32" else torch.bfloat16
    kwargs = {"trust_remote_code": trust_remote, "torch_dtype": torch_dtype}
    if attn_eager:
        kwargs["attn_implementation"] = "eager"
    model = cls.from_pretrained(model_id, **kwargs)
    model.eval()
    if chat_template:
        messages = [{
            "role": "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": prompt},
            ],
        }]
        text_in = processor.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False)
        inputs = processor(images=[img], text=text_in, return_tensors="pt")
    elif prompt:
        inputs = processor(images=img, text=prompt, return_tensors="pt")
    else:
        # No text prompt: the processor builds its own default query (GOT-OCR
        # needs this, its default query carries the image tokens; passing a
        # plain text prompt would drop them).
        inputs = processor(images=img, return_tensors="pt")
    prompt_len = inputs["input_ids"].shape[1]
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=512)
    # Decode only the generated tokens, not the prompt echo. The prompt is
    # the chat-formatted text for chat-template models and the processor's
    # own query for GOT-OCR, so a string prefix strip would not match it.
    gen = out[:, prompt_len:] if out.shape[1] > prompt_len else out
    text = processor.batch_decode(gen, skip_special_tokens=True)[0]
    # Strip the prompt echo if present.
    if prompt and text.startswith(prompt):
        text = text[len(prompt):].strip()
    return text, 0.0


RUNNERS = {
    "tesseract": _run_tesseract,
    "rapidocr": _run_rapidocr,
    "paddleocr": _run_paddleocr,
    "doctr": _run_doctr,
}

# (model id, prompt, model class, chat_template, attn_eager, trust_remote,
#  max_side, dtype). Florence-2 and GOT-OCR load as a causal LM. SmolDocling
# (Idefics3) and Qwen2-VL load as an image-text-to-text model; AutoModelFor-
# CausalLM does not recognise their config class. SmolDocling and Qwen2-VL
# need the chat template so the image token is present. GOT-OCR uses the
# native -hf repo (the plain repo has no processor class). Florence-2 loads
# in float32, not bf16 (CPU dtype clash, see _run_hf_model).
HF_MODELS = {
    "florence2": ("microsoft/Florence-2-base", "<OCR>", "causal_lm", False, True, True, 0, "fp32"),
    "smoldocling": ("ds4sd/SmolDocling-256M-preview", "Convert this page to docling.", "image_text_to_text", True, False, True, 0, "bf16"),
    "gotocr": ("stepfun-ai/GOT-OCR-2.0-hf", "", "image_text_to_text", False, False, False, 0, "bf16"),
    "qwen2vl": ("Qwen/Qwen2-VL-2B-Instruct", "Read all text in this image.", "image_text_to_text", True, False, True, 1024, "bf16"),
}


def run_model(model: str, image: Path) -> dict:
    """Run one model on one image. Returns a result dict, never raises."""
    t0 = time.time()
    ram0 = _peak_ram_mb()
    try:
        if model in RUNNERS:
            text, conf = RUNNERS[model](image)
        elif model in HF_MODELS:
            model_id, prompt, model_class, chat_template, attn_eager, trust_remote, max_side, dtype = HF_MODELS[model]
            text, conf = _run_hf_model(model_id, image, prompt, model_class,
                                       chat_template, attn_eager, trust_remote, max_side, dtype)
        else:
            return {"model": model, "error": f"unknown model {model}"}
    except Exception as exc:  # noqa: BLE001 - record the failure and continue
        return {
            "model": model, "error": f"{type(exc).__name__}: {exc}"[:200],
            "time_s": round(time.time() - t0, 2), "ram_peak_mb": _peak_ram_mb(),
        }
    dt = time.time() - t0
    words = text.split()
    return {
        "model": model,
        "words": len(words),
        "chars": len(text),
        "conf": conf,
        "time_s": round(dt, 2),
        "ram_peak_mb": max(_peak_ram_mb(), ram0),
        "text": text,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--images", required=True, help="Directory holding the image files")
    ap.add_argument("--manifest", required=True, help="JSON list of image entries")
    ap.add_argument("--out", required=True, help="Output directory for bench.json and bench.md")
    ap.add_argument("--models", default=",".join(ALL_MODELS),
                    help="Comma-separated model names (default: all)")
    ap.add_argument("--limit", type=int, default=0, help="Limit images (0 = all)")
    args = ap.parse_args(argv)

    images_dir = Path(args.images)
    manifest = json.loads(Path(args.manifest).read_text())
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    bad = [m for m in models if m not in ALL_MODELS]
    if bad:
        print(f"unknown models: {', '.join(bad)}", file=sys.stderr)
        return 1
    if args.limit:
        manifest = manifest[: args.limit]

    results: list[dict] = []
    for entry in manifest:
        kind = entry.get("kind", "")
        qkey = entry.get("question_key", "")
        image_name = entry.get("image", "")
        rel = entry.get("file", image_name)
        image = images_dir / Path(rel).name if not Path(rel).is_absolute() else Path(rel)
        if not image.exists():
            image = images_dir / image_name
        if not image.exists():
            print(f"skip {kind}: image not found: {image}", file=sys.stderr)
            continue
        sha = _sha8(image)
        size = image.stat().st_size
        row = {
            "kind": kind, "question_key": qkey, "image": image_name,
            "sha256_8": sha, "bytes": size, "models": {},
        }
        for model in models:
            res = run_model(model, image)
            text = res.pop("text", "")
            # Save raw output for human structure review, not printed.
            raw_path = outdir / f"{kind}_{model}.txt"
            raw_path.write_text(text, encoding="utf-8")
            res["structure"] = _structure(kind, text)
            row["models"][model] = res
            status = "error" if "error" in res else f"{res.get('words', 0)} words"
            print(f"{kind:15s} {model:10s} {status}")
        results.append(row)

    if not results:
        print("no images were read", file=sys.stderr)
        return 1

    bench = {
        "images": len(results),
        "models": models,
        "pinned": PINNED,
        "results": results,
    }
    (outdir / "bench.json").write_text(json.dumps(bench, indent=2), encoding="utf-8")

    # Markdown table.
    lines = [
        "# OCR bench results",
        "",
        "Models: " + ", ".join(models) + ".",
        "Pinned: " + ", ".join(f"{k} {v}" for k, v in PINNED.items()) + ".",
        "",
        "| Kind | Question | Image | Sha256 | Model | Words | Conf | Time (s) | RAM peak (MB) | Structure |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in results:
        for model in models:
            r = row["models"].get(model, {})
            if "error" in r:
                lines.append(
                    f"| {row['kind']} | {row['question_key']} | {row['image']} | "
                    f"{row['sha256_8']} | {model} | error | - | {r.get('time_s', '-')} | "
                    f"{r.get('ram_peak_mb', '-')} | {r.get('error', '')[:60]} |"
                )
            else:
                st = r.get("structure", {})
                struct = st.get("detail", "")
                if st.get("max"):
                    struct = f"{st.get('score')}/{st.get('max')} {struct}"
                lines.append(
                    f"| {row['kind']} | {row['question_key']} | {row['image']} | "
                    f"{row['sha256_8']} | {model} | {r.get('words', 0)} | {r.get('conf', 0)} | "
                    f"{r.get('time_s', 0)} | {r.get('ram_peak_mb', 0)} | {struct} |"
                )
    (outdir / "bench.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {outdir / 'bench.json'} and {outdir / 'bench.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
