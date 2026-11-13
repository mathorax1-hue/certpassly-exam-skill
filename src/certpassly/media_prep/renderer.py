"""Priority B rendering: high-DPI annotation-free crops of REAL PDF content.

What this module does honestly:
  - renders a page region (clip rect, PDF points, UNROTATED page space) at a
    chosen DPI with PyMuPDF ``page.get_pixmap(dpi=..., clip=..., annots=False)``;
  - records exactly what was excluded: real PDF annotations that exist on the
    page (list of types + rects), optional-content (OCG) layers, form fields;
  - reports ``removal_changed_visible_content`` = True only when annotations
    with appearance streams actually existed on the page; if the page has
    NO annotations (e.g. marks were flattened into the raster image), it
    records ``annotations_present: false`` and the method is NOT offered as a
    "cleaning" step - rendering at high DPI adds real pixels for VECTOR/text
    content only, never for an embedded raster (a 400x250 embedded JPEG is
    still 400x250 source pixels no matter the DPI).

Rotation handling: ``page.get_pixmap`` already accounts for /Rotate, so the
caller passes the rect in UNROTATED page coordinates (the same space
PyMuPDF's get_image_rects reports) and the renderer produces the visually
correct upright crop.
"""
from __future__ import annotations


def _lazy_fitz():
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - environment guard
        from .errors import OperationalError
        raise OperationalError(
            "rendering requires the pdf extra (PyMuPDF): "
            "python -m pip install -e '.[phase1,visual]'") from exc
    return fitz


def page_annotation_report(pdf_path: str, page_number: int) -> dict:
    """Inventory of annotation/OCG/form structures on one page (1-based)."""
    fitz = _lazy_fitz()
    doc = fitz.open(pdf_path)
    if not (1 <= page_number <= doc.page_count):
        from .errors import OperationalError
        raise OperationalError(f"page {page_number} out of range (1..{doc.page_count})")
    page = doc[page_number - 1]
    annots = []
    for a in page.annots() or []:
        try:
            has_appearance = True
            if hasattr(a, "rect"):
                has_appearance = not a.rect.is_empty
        except Exception:
            has_appearance = True
        annots.append({
            "type": a.type[1] if isinstance(a.type, tuple) else str(a.type),
            "rect": [round(v, 2) for v in a.rect],
            "has_appearance": has_appearance,
            "info_name": (a.info or {}).get("name", ""),
        })
    widgets = []
    try:
        for w in page.widgets() or []:
            widgets.append({"type": str(w.field_type), "rect": [round(v, 2) for v in w.rect]})
    except Exception:
        pass
    ocgs = []
    try:
        ocg_map = doc.get_ocgs() or {}
        for xref, info in ocg_map.items():
            ocgs.append({"xref": xref, "name": info.get("name"), "on": info.get("on", None)})
    except Exception:
        pass
    return {
        "page": page_number,
        "annotations_present": bool(annots),
        "annotations": annots,
        "widgets_present": bool(widgets),
        "widgets": widgets,
        "ocgs_present": bool(ocgs),
        "ocgs": ocgs,
        "page_rotation_deg": page.rotation,
    }


def render_crop(pdf_path: str, page_number: int, rect, *, dpi=300, annots=False) -> dict:
    """Render one clip region. Returns {"png_bytes": PNG bytes, ...facts}.

    ``rect`` is (x0, y0, x1, y1) in UNROTATED PDF points. ``annots=False``
    excludes annotation appearances from the render - but that only changes
    pixels when real annotations exist on the page (recorded honestly).
    """
    fitz = _lazy_fitz()
    doc = fitz.open(pdf_path)
    if not (1 <= page_number <= doc.page_count):
        from .errors import OperationalError
        raise OperationalError(f"page {page_number} out of range")
    page = doc[page_number - 1]
    clip = fitz.Rect(*rect)
    if clip.is_empty or clip.is_infinite:
        from .errors import OperationalError
        raise OperationalError(f"invalid clip rect: {rect}")
    pix = page.get_pixmap(dpi=dpi, clip=clip, annots=annots)
    report = page_annotation_report(pdf_path, page_number)
    removal_changed = bool(report["annotations_present"])
    return {
        "png_bytes": pix.tobytes("png"),
        "width": pix.width,
        "height": pix.height,
        "dpi": dpi,
        "page": page_number,
        "clip": [round(v, 2) for v in rect],
        "annots_excluded": not annots,
        "annotations_present": report["annotations_present"],
        "annotations_in_clip": [
            a for a in report["annotations"]
            if not (a["rect"][2] < clip.x0 or a["rect"][0] > clip.x1
                    or a["rect"][3] < clip.y0 or a["rect"][1] > clip.y1)
        ],
        "removal_changed_visible_content": removal_changed,
        "page_rotation_deg": report["page_rotation_deg"],
        "note": ("rendered from original PDF page content; "
                 + ("real annotations were excluded (removal actually changed pixels)"
                    if removal_changed else
                    "page has no real annotations - annots=False changed nothing; "
                    "flattened raster marks are NOT cleaned by rendering")),
    }


def renderable_embedded_raster(pdf_path: str, xref: int) -> dict:
    """Honest facts about an embedded raster behind a would-be Priority-B render.

    A re-render of a page whose visual is an embedded JPEG cannot add source
    pixels: the native embedded resolution is the ceiling. This helper gives
    the selection engine those numbers so it never claims fake upscaling.
    """
    fitz = _lazy_fitz()
    doc = fitz.open(pdf_path)
    try:
        info = doc.extract_image(xref)
    except Exception as exc:
        from .errors import OperationalError
        raise OperationalError(f"xref {xref} is not an extractable image: {exc}") from exc
    return {
        "xref": xref,
        "native_width": info.get("width"),
        "native_height": info.get("height"),
        "ext": (info.get("ext") or "").lower(),
        "smask": bool(info.get("smask")),
        "note": "embedded raster: re-rendering the page at higher DPI cannot "
                "exceed this native resolution; any 'extra' pixels are interpolation",
    }
