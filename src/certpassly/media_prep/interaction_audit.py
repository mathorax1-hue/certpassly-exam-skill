"""B4 technical responsive interaction-region audit (source geometry only).

This module does not emulate JavaScript, CSS hit testing, keyboard
navigation, a real website, or answer semantics. It only compares a declared
source-normalized target geometry against mobile/desktop viewport budgets.
"""
from __future__ import annotations

import math
from .media_layout import css_rect, validate_layout, rotate_point


def _region_box(item):
    rect = item.get("rect")
    if rect is not None:
        return rect
    polygon = item.get("polygon")
    if not isinstance(polygon, list) or len(polygon) < 3:
        return None
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]


def _iou(a, b):
    xa0, ya0, xa1, ya1 = a
    xb0, yb0, xb1, yb1 = b
    inter = max(0, min(xa1, xb1)-max(xa0, xb0))*max(0, min(ya1, yb1)-max(ya0, yb0))
    if not inter:
        return 0.0
    union=(xa1-xa0)*(ya1-ya0)+(xb1-xb0)*(yb1-yb0)-inter
    return inter / union if union > 0 else 1.0


def audit_interaction_geometry(layout: dict, registry: dict, *,
                               native_width: int, native_height: int,
                               viewports=(320, 375, 768, 1024, 1440),
                               dprs=(1, 2), zooms=(1.0, 2.0),
                               max_display_width=640,
                               minimum_touch_css_px=44) -> dict:
    """Fail closed for unsafe/too-small/overlapping interactive targets.

    Native image width/height MUST be read from the original-source raster
    or verifiable source PDF crop, not from an upscaled export.
    """
    check = validate_layout(layout, registry)
    problems = [{"reason":"LAYOUT_CONTRACT_BLOCKED",
                 "detail":reason} for reason in check["reasons"]]
    def positive(value):
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and value > 0)
    if not all(positive(v) for v in
               (native_width,native_height,max_display_width,minimum_touch_css_px)):
        return {"status":"MACHINE_GEOMETRY_BLOCKED",
                "problems":problems+[{"reason":"ORIGINAL_IMAGE_GEOMETRY_REQUIRED"}],
                "cases":[],"site_ui_status":"UNTESTED","keyboard_status":"UNTESTED"}
    if not all(positive(v) for v in (*viewports,*dprs,*zooms)):
        return {"status":"MACHINE_GEOMETRY_BLOCKED",
                "problems":problems+[{"reason":"VIEWPORT_MATRIX_INVALID"}],
                "cases":[],"site_ui_status":"UNTESTED","keyboard_status":"UNTESTED"}
    rotation=layout.get("source",{}).get("rotation_deg",0)
    if rotation not in (0,90,180,270):
        rotation=0
    w,h=(native_height,native_width) if rotation in (90,270) else (native_width,native_height)
    controls=layout.get("controls") or {}
    groups=[(g, controls.get(g) or []) for g in ("hotspots","drop_zones","blanks")]
    cases=[]
    for viewport in viewports:
        for dpr in dprs:
            for zoom in zooms:
                display_width=min(viewport,max_display_width)*zoom
                display_height=display_width*h/w
                case={"viewport_css_px":viewport, "dpr":dpr,"zoom":zoom,
                      "display_width_css_px":round(display_width,3),
                      "display_height_css_px":round(display_height,3),
                      "targets":[]}
                for group,targets in groups:
                    regions=[]
                    for item in targets:
                        if not isinstance(item,dict):
                            problems.append({"reason":"TARGET_NOT_OBJECT","group":group})
                            continue
                        rect=_region_box(item)
                        if rect is None:
                            problems.append({"reason":"TARGET_GEOMETRY_MISSING",
                                             "group":group,"id":item.get("id")})
                            continue
                        try:
                            scaled=css_rect(rect,width=display_width,
                                            height=display_height,dpr=dpr,
                                            rotation_deg=rotation)
                        except ValueError:
                            problems.append({"reason":"TARGET_GEOMETRY_INVALID",
                                             "group":group,"id":item.get("id")})
                            continue
                        record={"group":group,"id":item.get("id"),
                                "css_box":scaled["css"],
                                "device_box":scaled["device"],
                                "touch_44_css_px":scaled["touch_target_44_css_px"]}
                        css=scaled["css"]
                        if min(css[2]-css[0],css[3]-css[1])<minimum_touch_css_px:
                            problems.append({"reason":"TOUCH_TARGET_TOO_SMALL",
                                             "viewport_css_px":viewport,
                                             "group":group,"id":item.get("id"),
                                             "zoom":zoom})
                        regions.append(record)
                        case["targets"].append(record)
                    for i,a in enumerate(regions):
                        for b in regions[i+1:]:
                            if _iou(a["css_box"],b["css_box"])>0.35:
                                problems.append({"reason":"TARGETS_OVERLAP",
                                                 "viewport_css_px":viewport,
                                                 "group":group,"ids":[a["id"],b["id"]]})
                cases.append(case)
    return {"status":"MACHINE_GEOMETRY_BLOCKED" if problems else "MACHINE_GEOMETRY_PASS",
            "problems":problems, "cases":cases,
            "native_original_width_px":native_width,
            "native_original_height_px":native_height,
            "site_ui_status":"UNTESTED","keyboard_status":"UNTESTED",
            "source_geometry_only":True}
