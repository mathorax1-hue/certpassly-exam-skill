"""Synthetic tests for scripts/ocr_bench.py.

Uses a generated image with known text, never a real exam image, key, or
question text. Verifies the report shape, the structure scoring, and that a
missing model is recorded as an error instead of failing the run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ocr_bench  # noqa: E402


def _make_image(path: Path) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (600, 200), "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), "Yes No Statement One", fill="black")
    draw.text((20, 60), "Yes No Statement Two", fill="black")
    draw.text((20, 100), "Yes No Statement Three", fill="black")
    img.save(path)


def test_structure_grid(tmp_path: Path) -> None:
    st = ocr_bench._structure("matrix_q", "Yes No Statement One Yes No")
    assert st["check"] == "grid_yes_no"
    assert st["score"] == 2
    assert st["max"] == 2
    st2 = ocr_bench._structure("matrix_q", "Yes Statement One")
    assert st2["score"] == 1
    st3 = ocr_bench._structure("dropdown1", "anything")
    assert st3["check"] == "dropdown_selection"
    assert st3["score"] is None


def test_bench_tesseract_synthetic(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    img = images / "grid.png"
    _make_image(img)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([
        {"kind": "matrix_q", "question_key": "q000",
         "image": "grid.png", "file": "grid.png"},
    ]))
    outdir = tmp_path / "out"
    rc = ocr_bench.main([
        "--images", str(images), "--manifest", str(manifest),
        "--out", str(outdir), "--models", "tesseract",
    ])
    assert rc == 0
    bench = json.loads((outdir / "bench.json").read_text())
    assert bench["images"] == 1
    assert bench["models"] == ["tesseract"]
    row = bench["results"][0]
    assert row["kind"] == "matrix_q"
    assert row["sha256_8"]
    res = row["models"]["tesseract"]
    assert "words" in res
    assert "conf" in res
    assert "time_s" in res
    assert "ram_peak_mb" in res
    assert res["structure"]["check"] == "grid_yes_no"
    md = (outdir / "bench.md").read_text()
    assert "tesseract" in md
    assert "matrix_q" in md
    raw = (outdir / "matrix_q_tesseract.txt").read_text()
    assert isinstance(raw, str)


def test_unknown_model_is_error(tmp_path: Path) -> None:
    res = ocr_bench.run_model("not_a_model", tmp_path / "nope.png")
    assert "error" in res


def test_missing_image_returns_one(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([
        {"kind": "matrix_q", "question_key": "q000",
         "image": "missing.png", "file": "missing.png"},
    ]))
    rc = ocr_bench.main([
        "--images", str(tmp_path), "--manifest", str(manifest),
        "--out", str(tmp_path / "out"), "--models", "tesseract",
    ])
    assert rc == 1
