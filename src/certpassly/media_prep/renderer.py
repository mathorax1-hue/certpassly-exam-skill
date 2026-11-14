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

Rotation handling (2026-11-14 P0 correction): PyMuPDF reports text, image
and drawing geometry in UNROTATED page points, but ``get_pixmap(clip=...)``
interprets its clip in the ROTATED (display) coordinate system. Passing an
unrotated rect directly renders the WRONG region on any rotated page. The
caller still passes the rect in UNROTATED page coordinates (the same space
get_image_rects reports); this module now maps it through the page's
rotation matrix before rendering and records BOTH rects plus the page
rotation, so every crop is visually correct and independently checkable.
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

    ``rect`` is (x0, y0, x1, y1) in UNROTATED PDF points (the same space as
    get_text/get_drawings/get_image_rects geometry); it is mapped through the
    page rotation matrix before ``get_pixmap`` so rotated pages render the
    visually correct upright region. ``annots=False`` excludes annotation
    appearances from the render - but that only changes pixels when real
    annotations exist on the page (recorded honestly).
    """
    fitz = _lazy_fitz()
    doc = fitz.open(pdf_path)
    if not (1 <= page_number <= doc.page_count):
        from .errors import OperationalError
        raise OperationalError(f"page {page_number} out of range")
    page = doc[page_number - 1]
    clip_unrot = fitz.Rect(*rect)
    if clip_unrot.is_empty or clip_unrot.is_infinite:
        from .errors import OperationalError
        raise OperationalError(f"invalid clip rect: {rect}")
    rotation = page.rotation or 0
    if rotation == 0:
        clip = fitz.Rect(clip_unrot)
    else:
        d = clip_unrot * page.rotation_matrix
        clip = fitz.Rect(min(d.x0, d.x1), min(d.y0, d.y1),
                         max(d.x0, d.x1), max(d.y0, d.y1))
    pix = page.get_pixmap(dpi=dpi, clip=clip, annots=annots)
    report = page_annotation_report(pdf_path, page_number)
    removal_changed = bool(report["annotations_present"])
    # annot rects are reported in UNROTATED points (like all PyMuPDF
    # geometry); map them into the same display space as the clip before the
    # overlap test so rotated pages report annotations_in_clip correctly
    if rotation == 0:
        annot_rects = [fitz.Rect(a["rect"]) for a in report["annotations"]]
    else:
        rm = page.rotation_matrix
        annot_rects = []
        for a in report["annotations"]:
            r = fitz.Rect(a["rect"]) * rm
            annot_rects.append(fitz.Rect(min(r.x0, r.x1), min(r.y0, r.y1),
                                          max(r.x0, r.x1), max(r.y0, r.y1)))
    annotations_in_clip = [a for a, r in zip(report["annotations"], annot_rects)
                           if not (r.x1 < clip.x0 or r.x0 > clip.x1
                                   or r.y1 < clip.y0 or r.y0 > clip.y1)]
    return {
        "png_bytes": pix.tobytes("png"),
        "width": pix.width,
        "height": pix.height,
        "dpi": dpi,
        "page": page_number,
        "clip": [round(v, 2) for v in (clip.x0, clip.y0, clip.x1, clip.y1)],
        "clip_unrotated": [round(v, 2) for v in rect],
        "page_rotation_deg": rotation,
        "annots_excluded": not annots,
        "annotations_present": report["annotations_present"],
        "annotations_in_clip": annotations_in_clip,
        "removal_changed_visible_content": removal_changed,
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
