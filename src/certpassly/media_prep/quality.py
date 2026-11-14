"""Deterministic image quality checks with per-profile thresholds.

"High resolution is real, not cosmetic": the checker tracks NATIVE source
pixels, effective pixel density (native width / intended CSS display width)
against a goal (default 2.0 device px per CSS px), blur (Laplacian variance),
RMS contrast, histogram extremes, aspect ratio and lossless codec - with
per-profile thresholds (a diagram and a dense UI screenshot are not judged
by the same numbers) and stable reason codes. Lanczos/resize can never turn
a FAIL into a PASS: quality is measured on the SOURCE pixels only.

Hard failures (block learner eligibility):
  SOURCE_IMAGE_TINY               degenerate size (< 32px in either dimension)
  SOURCE_IMAGE_LOW_RESOLUTION     native width below profile minimum, or
                                  effective density below the profile floor
  SOURCE_IMAGE_ASPECT_EXTREME     aspect ratio outside [1/6, 6]
  SOURCE_IMAGE_BLURRY             Laplacian variance below profile threshold
  SOURCE_IMAGE_LOW_CONTRAST       RMS contrast below profile threshold

Advisories (recorded for review, never silently dropped):
  SOURCE_IMAGE_CLIPPED            histogram extreme saturation (black text on
                                  white is legitimate; only near-total absence
                                  of midtones is flagged here)
  BELOW_PIXEL_DENSITY_GOAL        eligible but below the 2x display goal
  ADVISORY_TEXT_EDGE_DENSITY      very low edge density may mean no content
"""
from __future__ import annotations

R_LOW_RES = "SOURCE_IMAGE_LOW_RESOLUTION"
R_BLURRY = "SOURCE_IMAGE_BLURRY"
R_LOW_CONTRAST = "SOURCE_IMAGE_LOW_CONTRAST"
R_CLIPPED = "SOURCE_IMAGE_CLIPPED"
R_TINY = "SOURCE_IMAGE_TINY"
R_ASPECT = "SOURCE_IMAGE_ASPECT_EXTREME"
R_ADVISORY_EDGES = "ADVISORY_TEXT_EDGE_DENSITY"
R_BELOW_DENSITY_GOAL = "BELOW_PIXEL_DENSITY_GOAL"


def _lazy():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment guard
        from .errors import OperationalError
        raise OperationalError(
            "quality checks require the visual extra: "
            "python -m pip install -e '.[phase1,visual]'") from exc
    return cv2, np


def assess(source_img, *, profile: dict, css_width: float, density_goal: float) -> dict:
    """Assess one decoded SourceImage against one quality profile.

    ``css_width`` is the intended learner display width in CSS px; the
    effective density is native_width / css_width and is compared against the
    profile floor, while ``density_goal`` (e.g. 2.0) is recorded as the target
    with ``meets_goal`` - a candidate can be learner-eligible (floor met)
    while honestly flagged as below the 2x goal.
    """
    cv2, np = _lazy()
    rgb = source_img.flattened_rgb()
    w, h = source_img.width, source_img.height
    gray = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2GRAY)

    issues = []
    advisory = []

    if w < 32 or h < 32:
        issues.append({"reason": R_TINY, "detail": f"{w}x{h}"})
    if w < profile["min_native_width"]:
        issues.append({"reason": R_LOW_RES,
                       "detail": f"native width {w} < profile minimum {profile['min_native_width']}"})
    aspect = w / float(h) if h else 0.0
    if aspect and (aspect > 6.0 or aspect < 1 / 6.0):
        issues.append({"reason": R_ASPECT, "detail": f"aspect {aspect:.3f}"})

    # effective pixel density vs intended display width
    effective_density = round(w / float(css_width), 4) if css_width else None
    if effective_density is not None and effective_density < profile["min_effective_density"]:
        issues.append({"reason": R_LOW_RES,
                       "detail": f"effective density {effective_density} < "
                                 f"profile minimum {profile['min_effective_density']} "
                                 f"(native {w}px at {css_width} CSS px)"})
    if effective_density is not None and effective_density < density_goal:
        advisory.append({"reason": R_BELOW_DENSITY_GOAL,
                         "detail": f"effective density {effective_density} below the "
                                   f"{density_goal}x display goal (advisory)"})

    # blur: Laplacian variance (higher = sharper)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if blur < profile["max_blur_flag"]:
        issues.append({"reason": R_BLURRY, "detail": f"laplacian variance {blur:.1f} "
                                                     f"< {profile['max_blur_flag']}"})

    # RMS contrast (std of grayscale in [0,1])
    rms_contrast = float(gray.std() / 255.0)
    if rms_contrast < profile["min_rms_contrast"]:
        issues.append({"reason": R_LOW_CONTRAST,
                       "detail": f"rms contrast {rms_contrast:.4f} < {profile['min_rms_contrast']}"})

    # histogram extremes: fraction of near-pure black / near-pure white.
    # Legitimate text exhibits are mostly white with pure-black text, so
    # these are ADVISORY unless essentially no midtones exist at all.
    dark_clip = float((gray <= 4).mean())
    white_clip = float((gray >= 251).mean())
    if dark_clip > profile.get("max_dark_clip_fraction", 0.5):
        advisory.append({"reason": R_CLIPPED,
                         "detail": f"dark-clipped fraction {dark_clip:.4f}"})
    if dark_clip + white_clip > 0.985:
        advisory.append({"reason": R_CLIPPED,
                         "detail": f"almost no midtone pixels (dark {dark_clip:.3f} + "
                                   f"white {white_clip:.3f})"})

    # advisory: edge density (proxy for "is there visible structure/text")
    edges = cv2.Canny(gray, 60, 160)
    edge_density = float(edges.mean() / 255.0)
    if profile.get("min_text_edge_density", 0) and edge_density < profile["min_text_edge_density"]:
        advisory.append({"reason": R_ADVISORY_EDGES,
                         "detail": f"edge density {edge_density:.5f} < "
                                   f"{profile['min_text_edge_density']}"})

    lossless = source_img.format in ("png", "gif", "bmp", "tiff")
    return {
        "native_width": w,
        "native_height": h,
        "format": source_img.format,
        "lossless": lossless,
        "alpha_flattened_for_check": source_img.has_alpha,
        "blur_laplacian_variance": round(blur, 2),
        "rms_contrast": round(rms_contrast, 5),
        "dark_clip_fraction": round(dark_clip, 5),
        "white_clip_fraction": round(white_clip, 5),
        "edge_density": round(edge_density, 6),
        "aspect_ratio": round(aspect, 4),
        "pixel_density": {
            "css_width": css_width,
            "native_width": w,
            "effective_density": effective_density,
            "goal": density_goal,
            "meets_goal": bool(effective_density is not None and effective_density >= density_goal),
        },
        "issues": issues,
        "advisory": advisory,
        "quality_ok": not issues,
    }


def choose_profile(source_img, question_record=None) -> str:
    """Pick a profile name for one image (screenshot default; diagram hint).

    The engine default is "screenshot" (conservative). "diagram" applies when
    the caller explicitly passes profile_hint="diagram" in the question
    record; everything else is judged as the denser screenshot profile.
    """
    hint = (question_record or {}).get("profile_hint")
    if hint in ("diagram", "screenshot"):
        return hint
    return "screenshot"


def responsive_density_matrix(source_img, *, max_css_width=640,
                              viewports=(320, 375, 768, 1024, 1440),
                              dprs=(1, 2), zooms=(1, 2),
                              minimum_density=1.0):
    """B3 truthful source-pixel audit, not a simulated browser approval.

    The image is displayed at min(viewport, max_css_width) CSS px at 100%
    zoom; a 200% zoom needs twice the logical source density. DPR controls
    whether native pixels can satisfy the physical display sample budget.
    DO NOT use an upscaled export's new width as source_img.width.
    """
    import math
    native = source_img.width
    if not math.isfinite(max_css_width) or max_css_width <= 0:
        raise ValueError("max_css_width must be positive")
    if minimum_density <= 0:
        raise ValueError("minimum_density must be positive")
    rows = []
    for viewport in viewports:
        for dpr in dprs:
            for zoom in zooms:
                if any(not isinstance(v, (int, float)) or
                       not math.isfinite(v) or v <= 0 for v in (viewport, dpr, zoom)):
                    raise ValueError("viewports, DPRs and zooms must be positive")
                css_width = min(viewport, max_css_width) * zoom
                density = native / css_width
                rows.append({
                    "viewport_css_px": viewport,
                    "dpr": dpr, "zoom": zoom,
                    "display_css_px": round(css_width, 3),
                    "source_native_width_px": native,
                    "native_pixels_per_css_px": round(density, 4),
                    "meets_minimum_density": bool(density >= minimum_density),
                    "meets_device_sample_budget": bool(native >= css_width * dpr),
                })
    return {
        "source_native_width_px": native,
        "source_pixel_provenance": "native; never upscale to clear quality",
        "rows": rows,
        "all_minimum_density_ok": all(r["meets_minimum_density"] for r in rows),
        "all_device_budgets_ok": all(r["meets_device_sample_budget"] for r in rows),
        "site_render_tested": False,
    }


def region_blur_matrix(source_img, *, columns=3, rows=3):
    """B3 per-region blur visibility proxy; NOT OCR or semantic crop proof.

    Blurry or tiny footer/options can be lost in a global sharpness average.
    Reports variance for every source-pixel tile, with no resizing.
    """
    cv2, np = _lazy()
    if not (1 <= columns <= 12 and 1 <= rows <= 12):
        raise ValueError("tile dimensions must be between 1 and 12")
    gray = cv2.cvtColor(np.asarray(source_img.flattened_rgb()),
                        cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    out = []
    for ry in range(rows):
        y0, y1 = round(ry * h / rows), round((ry + 1) * h / rows)
        for cx in range(columns):
            x0, x1 = round(cx * w / columns), round((cx + 1) * w / columns)
            roi = gray[y0:y1, x0:x1]
            if roi.size < 16:
                variance = 0.0
            else:
                variance = float(cv2.Laplacian(roi, cv2.CV_64F).var())
            out.append({"row": ry, "column": cx, "bbox_px": [x0, y0, x1, y1],
                        "blur_laplacian_variance": round(variance, 2)})
    return {"tiles": out, "source_width": w, "source_height": h,
            "semantic_text_legibility_tested": False,
            "clipped_options_checked_by_human": False}
