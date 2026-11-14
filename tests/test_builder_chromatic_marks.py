"""B2 mark matrix: saturated selected rings/highlights vs unselected UI.

Generated entirely from synthetic Pillow shapes. Conservative selection-mark
classification blocks both genuine and ambiguous colored UI decorations; it
never declares an actual exam source clean.
"""
from __future__ import annotations
import unittest

try:
    from PIL import Image, ImageDraw
    import numpy  # noqa: F401
    import cv2  # noqa: F401
    from certpassly.media_prep.marking import detect_marks
    HAS_VISUAL = True
except ImportError:
    HAS_VISUAL = False


def sample(kind):
    image = Image.new("RGB", (900, 480), "white")
    d = ImageDraw.Draw(image)
    for y in (150, 250, 350):
        d.rectangle((90, y, 775, y+47), outline=(164, 164, 164), width=2)
    d.ellipse((110, 160, 134, 184), outline=(153, 153, 153), width=2)
    if kind == "blue-ring":
        d.ellipse((100, 145, 250, 194), outline=(10, 91, 211), width=5)
    elif kind == "green-selection-box":
        d.rectangle((101, 240, 460, 302), outline=(10, 154, 71), width=5)
    elif kind == "yellow-highlight":
        d.rectangle((170, 270, 600, 303), fill=(247, 218, 38))
    elif kind == "red-selection-stroke":
        d.rectangle((175, 355, 490, 366), fill=(196, 24, 27))
    return image


@unittest.skipUnless(HAS_VISUAL, "requires image visual extra")
class ChromaticMarkTests(unittest.TestCase):
    def test_blue_hollow_ring_is_not_missed(self):
        report = detect_marks(sample("blue-ring"))
        self.assertGreater(report["detected_mark_boxes"], 0, report)
        self.assertIn("chromatic_pen_ring_or_box", {m["kind"] for m in report["marks"]})

    def test_green_selection_rectangle_is_not_missed(self):
        report = detect_marks(sample("green-selection-box"))
        self.assertGreater(report["detected_mark_boxes"], 0, report)

    def test_yellow_highlight_bar_is_not_missed(self):
        report = detect_marks(sample("yellow-highlight"))
        self.assertIn("chromatic_highlight_bar", {m["kind"] for m in report["marks"]})

    def test_red_highlight_stroke_is_not_missed(self):
        report = detect_marks(sample("red-selection-stroke"))
        self.assertIn("chromatic_highlight_bar", {m["kind"] for m in report["marks"]})

    def test_unselected_gray_ui_never_marked_by_color_mask(self):
        report = detect_marks(sample("neutral"))
        self.assertEqual(report["detected_mark_boxes"], 0, report)


if __name__ == "__main__":
    unittest.main()
