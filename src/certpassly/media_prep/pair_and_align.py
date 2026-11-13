"""Conservative clean/marked pair detection and registration (advisory only).

Scenario: an item carries a question image and an answer image (or two
question images) that show the SAME underlying exhibit, one with selection
marks and one without. This module decides, conservatively, whether two
images are the "same screenshot" (registration) and which one carries marks.

Hard rules from the operator order:
  - pair-diff is ADVISORY. It can never erase text/highlights from a
    marked-only screenshot and can never fabricate a clean image.
  - the only permitted learner output is the ALREADY-CLEAN member of a
    verified pair (or a deterministic crop of that same clean member);
  - registration must be conservative: low inlier counts, extreme
    transformations or strong aspect distortion mean "cannot pair" (which
    BLOCKS, never guesses).

Determinism: candidates are compared in (sha256, name) order via the
caller's file ordering; results never depend on directory listing order.
"""
from __future__ import annotations


def _lazy():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment guard
        from .errors import OperationalError
        raise OperationalError(
            "pair alignment requires the visual extra (opencv-python-headless): "
            "python -m pip install -e '.[phase1,visual]'") from exc
    return cv2, np


MIN_INLIERS = 25              # ORB matches surviving RANSAC
MIN_INLIER_RATIO = 0.55      # inliers / attempted matches
MAX_SCALE = 1.6              # |log2(scale)| bound
MAX_TRANSLATION = 0.25       # as fraction of image width/height


def _gray(pil_img):
    cv2, np = _lazy()
    arr = np.asarray(pil_img.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)


def _orb_keypoints(gray):
    cv2, _np = _lazy()
    orb = cv2.ORB_create(nfeatures=1200)
    kp, des = orb.detectAndCompute(gray, None)
    return kp, des


def register_pair(a_pil, b_pil) -> dict:
    """Try to register image b onto image a (ORB + RANSAC homography).

    Returns {"registered": bool, "inliers": int, "matches": int,
             "inlier_ratio": float, "scale": float, "reason": str}.
    """
    cv2, np = _lazy()
    ga, gb = _gray(a_pil), _gray(b_pil)
    ka, da = _orb_keypoints(ga)
    kb, db = _orb_keypoints(gb)
    if da is None or db is None or len(ka) < MIN_INLIERS or len(kb) < MIN_INLIERS:
        return {"registered": False, "inliers": 0, "matches": 0, "inlier_ratio": 0.0,
                "reason": "insufficient keypoints"}
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = bf.match(da, db)
    if len(matches) < MIN_INLIERS:
        return {"registered": False, "inliers": 0, "matches": len(matches),
                "inlier_ratio": 0.0, "reason": "insufficient matches"}
    matches = sorted(matches, key=lambda m: m.distance)
    src = np.float32([kb[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst = np.float32([ka[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if H is None or mask is None:
        return {"registered": False, "inliers": 0, "matches": len(matches),
                "inlier_ratio": 0.0, "reason": "homography failed"}
    inliers = int(mask.sum())
    ratio = inliers / float(len(matches))
    if inliers < MIN_INLIERS or ratio < MIN_INLIER_RATIO:
        return {"registered": False, "inliers": inliers, "matches": len(matches),
                "inlier_ratio": round(ratio, 4), "reason": "weak registration"}
    h, w = ga.shape
    sx = float(np.linalg.norm(H[:, 0]))
    sy = float(np.linalg.norm(H[:, 1]))
    scale = (sx + sy) / 2.0
    if abs(np.log2(max(scale, 1e-6))) > np.log2(MAX_SCALE):
        return {"registered": False, "inliers": inliers, "matches": len(matches),
                "inlier_ratio": round(ratio, 4), "reason": "extreme scale"}
    tx, ty = abs(H[0, 2]) / w, abs(H[1, 2]) / h
    if max(tx, ty) > MAX_TRANSLATION:
        return {"registered": False, "inliers": inliers, "matches": len(matches),
                "inlier_ratio": round(ratio, 4), "reason": "extreme translation"}
    return {"registered": True, "inliers": inliers, "matches": len(matches),
            "inlier_ratio": round(ratio, 4), "scale": round(scale, 4),
            "reason": "registered"}


def aligned_absdiff(a_pil, b_pil, reg: dict) -> dict | None:
    """Pixel difference of b resized onto a. None when not registered.

    Returns {"changed_fraction": float, "changed_regions": [...]} in the
    coordinate frame of image a. Advisory only: a region that differs tells
    us WHERE the two screenshots diverge (a candidate mark), never what
    to erase.
    """
    cv2, np = _lazy()
    if not reg.get("registered"):
        return None
    ga, gb = _gray(a_pil), _gray(b_pil)
    if abs(reg.get("scale", 1.0) - 1.0) > 0.02:
        return {"changed_fraction": None, "changed_regions": [],
                "note": "non-identity scale; warp comparison skipped (advisory)"}
    if ga.shape != gb.shape:
        gb = cv2.resize(gb, (ga.shape[1], ga.shape[0]), interpolation=cv2.INTER_AREA)
    diff = cv2.absdiff(ga, gb)
    changed = (diff > 28).astype(np.uint8())
    changed_fraction = float(changed.mean())
    n, labels, stats, _ = cv2.connectedComponentsWithStats(changed, 8)
    regions = []
    H, W = ga.shape
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 40:
            continue
        regions.append([round(x / W, 4), round(y / H, 4),
                        round(w / W, 4), round(h / H, 4), int(area)])
    regions.sort(key=lambda r: (-r[4], r[0], r[1]))
    return {"changed_fraction": round(changed_fraction, 6),
            "changed_regions": regions[:12], "note": "advisory diff; never used to erase"}


def compare_pair(a_img, b_img, a_marking, b_marking) -> dict:
    """Full pair comparison: registration + diff + which member is clean.

    The "clean member" call combines machine mark detection with the diff:
    the member with NO detected marks is the clean one, and if both or
    neither look marked the pair cannot certify anything (clean_member=None).
    """
    reg = register_pair(a_img.pil, b_img.pil)
    diff = aligned_absdiff(a_img.pil, b_img.pil, reg)
    a_marked = (a_marking or {}).get("detected_mark_boxes", 0) > 0
    b_marked = (b_marking or {}).get("detected_mark_boxes", 0) > 0
    clean_member = None
    if reg.get("registered"):
        if a_marked and not b_marked:
            clean_member = "b"
        elif b_marked and not a_marked:
            clean_member = "a"
    return {
        "registered": reg.get("registered", False),
        "registration": reg,
        "diff": diff,
        "a": {"sha256": a_img.sha256, "marked": a_marked},
        "b": {"sha256": b_img.sha256, "marked": b_marked},
        "clean_member": clean_member,
        "verdict": ("verified_pair_clean_member" if clean_member
                    else ("registered_both_marked" if reg.get("registered") and a_marked and b_marked
                          else ("registered_none_marked" if reg.get("registered") else "not_a_pair"))),
    }
