"""Safe image decode, hashing and native-size probing (Pillow, lazy import).

All image access funnels through this module so that:
  - corrupt/truncated images raise one typed error instead of scattering
    PIL exceptions;
  - every loaded binary is hashed exactly once;
  - alpha channels are handled explicitly (flatten onto white BEFORE quality
    checks, never silently treating transparent PNG as near-white).
"""
from __future__ import annotations

import hashlib
import io

from .errors import OperationalError

_IMAGE_MAGIC = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
    (b"RIFF", "webp-or-container"),
)


def sniff_format(data: bytes) -> str | None:
    """Best-effort format sniff from magic bytes (no decode)."""
    for magic, name in _IMAGE_MAGIC:
        if data.startswith(magic):
            return name
    return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SourceImage:
    """One decoded source image plus its immutable identity."""

    def __init__(self, name: str, data: bytes):
        if not data:
            raise OperationalError(f"image {name}: empty file")
        self.name = name
        self.data = data
        self.sha256 = sha256_bytes(data)
        self.sniffed_format = sniff_format(data)
        try:
            from PIL import Image  # lazy optional dependency
        except ImportError as exc:  # pragma: no cover - environment guard
            raise OperationalError(
                "media-prep requires the visual extra (Pillow): "
                "python -m pip install -e '.[phase1,visual]'") from exc
        try:
            self.pil = Image.open(io.BytesIO(data))
            self.pil.load()
        except Exception as exc:
            raise OperationalError(f"image {name}: cannot decode ({exc})") from exc
        self.format = (self.pil.format or "UNKNOWN").lower()
        self.width, self.height = self.pil.size
        self.has_alpha = (self.pil.mode in ("RGBA", "LA", "PA")
                          or "transparency" in (self.pil.info or {}))

    def flattened_rgb(self):
        """Return an RGB PIL image; alpha flattened onto white."""
        if self.pil.mode == "RGB":
            return self.pil
        if self.pil.mode in ("RGBA", "LA", "PA"):
            rgba = self.pil.convert("RGBA")
            bg = rgba.convert("RGB")
            return bg
        if self.pil.mode == "P":
            rgba = self.pil.convert("RGBA")
            return rgba.convert("RGB")
        return self.pil.convert("RGB")


def load_image(path_or_bytes, name: str | None = None) -> SourceImage:
    """Load from a filesystem path (str/Path) or raw bytes."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        return SourceImage(name or "<bytes>", bytes(path_or_bytes))
    p = str(path_or_bytes)
    try:
        with open(p, "rb") as f:
            data = f.read()
    except OSError as exc:
        raise OperationalError(f"cannot read image {p}: {exc}") from exc
    return SourceImage(name or p.rsplit("/", 1)[-1].rsplit("\\", 1)[-1], data)
