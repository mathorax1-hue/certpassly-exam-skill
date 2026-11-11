"""Environment readiness check. Missing optional tools never look like passing requirements."""
from __future__ import annotations

import shutil
import sys

TOOLS = {
    "git": "Required for GitHub source versioning",
    "uv": "Recommended for locked dependency installation",
    "docker": "Recommended for reproducible environments",
    "gh": "Optional GitHub Actions CLI control",
    "pdftoppm": "PDF page rendering (Poppler)",
    "pdfinfo": "PDF metadata (Poppler)",
    "tesseract": "OCR fallback for image-only sources",
    "node": "Browser and UI test tooling",
}


def inspect() -> dict:
    return {"python": {"version": sys.version.split()[0], "ready": sys.version_info >= (3, 11)},
            "tools": {name: {"installed": bool(shutil.which(name)), "path": shutil.which(name),
                             "use": description} for name, description in TOOLS.items()}}
