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


# --- Fake transformers/torch for the HF runner (no download, no model). ---

class _FakeTensor:
    """Minimal stand-in for a torch tensor: shape and [:, n:] slicing."""

    def __init__(self, length: int) -> None:
        self.shape = (1, length)

    def __getitem__(self, key):
        if isinstance(key, tuple):
            sl = key[1]
            start = sl.start or 0
            return _FakeTensor(self.shape[1] - start)
        return self


class _FakeNoGrad:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


class _FakeTorch:
    bfloat16 = "bfloat16"

    def no_grad(self):
        return _FakeNoGrad()


class _FakeProcessor:
    calls: list = []

    def __init__(self) -> None:
        self.calls = []

    def apply_chat_template(self, messages, add_generation_prompt=True, tokenize=False):
        return "CHAT:" + messages[0]["content"][1]["text"]

    def __call__(self, images=None, text=None, return_tensors=None):
        self.calls.append({"images": images is not None, "text": text})
        # Chat text is longer than a plain prompt; plain prompt is short.
        length = 12 if (text or "").startswith("CHAT:") else 4
        return {"input_ids": _FakeTensor(length)}

    def batch_decode(self, ids, skip_special_tokens=True):
        return [f"decoded-{ids.shape[1]}"]


class _FakeModel:
    floated = False

    def eval(self):
        return self

    def float(self):
        # Mirrors torch nn.Module.float(): converts all weights to float32.
        _FakeModel.floated = True
        return self

    def generate(self, **inputs):
        prompt_len = inputs["input_ids"].shape[1]
        return _FakeTensor(prompt_len + 7)


def _install_fake_hf(monkeypatch) -> _FakeProcessor:
    import sys
    import types

    proc = _FakeProcessor()
    fake_torch = types.ModuleType("torch")
    fake_torch.bfloat16 = "bfloat16"
    fake_torch.float32 = "float32"
    fake_torch.no_grad = _FakeNoGrad
    fake_tr = types.ModuleType("transformers")
    load_kwargs: dict = {}

    class _Auto:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            load_kwargs.update(kwargs)
            return _FakeModel()

    fake_tr.AutoModelForCausalLM = _Auto
    fake_tr.AutoModelForImageTextToText = _Auto

    class _AutoProc:
        @staticmethod
        def from_pretrained(model_id, **kwargs):
            return proc

    fake_tr.AutoProcessor = _AutoProc
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_tr)
    proc.load_kwargs = load_kwargs
    return proc


def test_florence2_uses_native_port(monkeypatch, tmp_path: Path) -> None:
    """Florence-2 must use the native florence-community port. The microsoft
    remote code leaves some layers in bf16 and fails on the CPU runner with
    a dtype mismatch even after model.float() (RuntimeError in run
    46133244718). The native port loads with AutoModelForImageTextToText,
    no trust_remote_code and no attn_implementation override."""
    proc = _install_fake_hf(monkeypatch)
    _make_image(tmp_path / "grid.png")
    _FakeModel.floated = False
    model_id, prompt, model_class, chat, eager, remote, side, dtype = ocr_bench.HF_MODELS["florence2"]
    assert model_id == "florence-community/Florence-2-base"
    assert model_class == "image_text_to_text"
    assert remote is False
    assert eager is False
    text, _conf = ocr_bench._run_hf_model(
        model_id, tmp_path / "grid.png", prompt, model_class, chat, eager, remote, side, dtype)
    assert proc.load_kwargs.get("torch_dtype") == "bfloat16"
    assert "attn_implementation" not in proc.load_kwargs
    assert _FakeModel.floated is False
    assert text == "decoded-7"


def test_gotocr_uses_images_only(monkeypatch, tmp_path: Path) -> None:
    """GOT-OCR-2.0-hf must use the images-only call, not the chat template.
    Its processor has no chat template, so apply_chat_template fails
    (ValueError in run 46134627812). The images-only call with an empty
    prompt works: the native processor builds its own default OCR query
    with the image tokens (run 46133244718, 10/10). The 0-token failure
    was with the old m-a-p repo, not with images-only."""
    proc = _install_fake_hf(monkeypatch)
    _make_image(tmp_path / "grid.png")
    model_id, prompt, model_class, chat, eager, remote, side, dtype = ocr_bench.HF_MODELS["gotocr"]
    assert chat is False
    assert prompt == ""
    text, _conf = ocr_bench._run_hf_model(
        model_id, tmp_path / "grid.png", prompt, model_class, chat, eager, remote, side, dtype)
    assert proc.calls and proc.calls[0].get("text") is None
    assert text == "decoded-7"


def test_chat_template_decodes_generated_tokens_only(monkeypatch, tmp_path: Path) -> None:
    """Chat-template models must decode only the generated tokens, not the
    chat-formatted prompt echo, or word counts are inflated."""
    proc = _install_fake_hf(monkeypatch)
    _make_image(tmp_path / "grid.png")
    model_id, prompt, model_class, chat, eager, remote, side, dtype = ocr_bench.HF_MODELS["smoldocling"]
    assert chat is True
    text, _conf = ocr_bench._run_hf_model(
        model_id, tmp_path / "grid.png", prompt, model_class, chat, eager, remote, side, dtype)
    assert proc.calls and (proc.calls[0]["text"] or "").startswith("CHAT:")
    assert text == "decoded-7"
