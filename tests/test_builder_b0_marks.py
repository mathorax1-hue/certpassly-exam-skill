"""B0 reproducible synthetic regressions for colored answer-state leakage.

All fixtures are generated from shapes in memory. No private exam data is used.
The first commit intentionally tests current behavior BEFORE the correction.
Run: python -m unittest discover -s tests -p 'test_builder_b0_marks.py' -v
"""
from __future__ import annotations

import io
import unittest

try:
    from PIL import Image, ImageDraw
    import cv2  # noqa: F401
    import numpy  # noqa: F401
    HAS_VISUAL = True
except ImportError:
    HAS_VISUAL = False

if HAS_VISUAL:
    from certpassly.media_prep.marking import detect_marks, looks_marked


def radio_fixture(*, filled=False, checkbox=False, jpeg=False):
    """Neutral gray UI chrome and one saturated blue selected control."""
    canvas = Image.new("RGB", (900, 600), "#fdfdfd")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((100, 100, 780, 500), outline="#a6a6a6", width=2)
    for i in range(3):
        y = 180 + 70 * i
        draw.ellipse((140, y, 170, y + 30), outline="#9e9e9e", width=2)
        draw.line((190, y + 13, 680, y + 13), fill="#c6c6c6", width=2)
    draw.rectangle((190, 420, 500, 464), outline="#a0a0a0", width=2)
    draw.polygon([(475, 434), (485, 434), (480, 442)], fill="#9e9e9e")
    if filled:
        if checkbox:
            draw.rectangle((140, 180, 168, 208), outline="#9e9e9e", width=2)
            draw.rectangle((147, 187, 161, 201), fill=(20, 104, 207))
        else:
            draw.ellipse((147, 187, 163, 203), fill=(20, 104, 207))
    if not jpeg:
        return canvas
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=88, subsampling=0)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


@unittest.skipUnless(HAS_VISUAL, "requires Pillow and OpenCV")
class B0ColoredStateRegression(unittest.TestCase):
    def test_blue_selected_radio_must_be_recognized(self):
        report = detect_marks(radio_fixture(filled=True))
        self.assertTrue(looks_marked(report), report)
        self.assertGreater(report["detected_mark_boxes"], 0)

    def test_blue_selected_checkbox_must_be_recognized(self):
        report = detect_marks(radio_fixture(filled=True, checkbox=True))
        self.assertTrue(looks_marked(report), report)

    def test_jpeg_compressed_blue_selected_radio_must_be_recognized(self):
        report = detect_marks(radio_fixture(filled=True, jpeg=True))
        self.assertTrue(looks_marked(report), report)

    def test_empty_gray_ui_controls_must_not_be_pen_marked(self):
        report = detect_marks(radio_fixture())
        self.assertFalse(looks_marked(report), report)


if __name__ == "__main__":
    unittest.main()
