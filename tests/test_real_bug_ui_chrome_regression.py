"""Synthetic regressions for menu chrome vs true marked answers.

Zero private exam pixels, text, asset hashes or answer keys belong in PUBLIC
regression fixtures. The real private screenshots are replayed in raw-exam.
"""
from __future__ import annotations
import unittest
try:
    from PIL import Image, ImageDraw
    import cv2  # noqa: F401
    import numpy  # noqa: F401
    from certpassly.media_prep.marking import detect_marks
    VISUAL = True
except ImportError:
    VISUAL = False


def menu(*, marked=False, thin_penned=False, border_width=1):
    canvas = Image.new("RGB", (920, 300), "white")
    d = ImageDraw.Draw(canvas)
    # thin neutral UI drop-down and combo frame, from synthetic geometry
    d.rectangle((280, 85, 670, 240), outline=(12, 12, 12), width=border_width)
    d.line((280, 70, 670, 70), fill=(190, 190, 190), width=1)
    d.line((280, 70, 280, 85), fill=(190, 190, 190), width=1)
    d.line((670, 70, 670, 85), fill=(190, 190, 190), width=1)
    d.polygon([(650, 75), (660, 75), (655, 80)], fill=(80, 80, 80))
    # gray text-like rows WITHOUT source-sensitive language
    for y in (107, 140, 173, 206):
        d.line((300, y, 540, y), fill=(105, 105, 105), width=2)
    if marked:
        d.rounded_rectangle((283, 89, 563, 126), radius=5,
                            outline=(10, 10, 10), width=6)
    if thin_penned:
        # A hand-inked selection ring not equivalent to a rectangular menu border.
        d.ellipse((290, 130, 540, 188), outline=(7, 7, 7), width=2)
    return canvas


def decorative_icons(*, selected=False, jpeg=False):
    import io
    canvas = Image.new("RGB", (1000, 777), "white")
    d = ImageDraw.Draw(canvas)
    for idx, col in enumerate(((238, 72, 18), (17, 112, 202), (14, 198, 172))):
        y=400+idx*84
        d.ellipse((200, y, 221, y+21), fill=col)
        d.line((250, y+10, 510, y+10), fill=(170, 170, 170), width=2)
    if selected:
        d.ellipse((830, 320, 860, 350), outline=(153, 153, 153), width=2)
        d.ellipse((838, 328, 852, 342), fill=(20, 104, 207))
    if jpeg:
        b=io.BytesIO()
        canvas.save(b, format="JPEG", quality=86, subsampling=0)
        return Image.open(io.BytesIO(b.getvalue())).convert("RGB")
    return canvas


@unittest.skipUnless(VISUAL, "requires image extras")
class RealBugSyntheticRegression(unittest.TestCase):
    def test_plain_dropdown_border_is_not_ink_selection(self):
        self.assertEqual(0, detect_marks(menu())["detected_mark_boxes"])

    def test_native_two_pixel_dropdown_border_not_pen_selected(self):
        self.assertEqual(0, detect_marks(menu(border_width=2))["detected_mark_boxes"])

    def test_native_three_pixel_dropdown_border_not_pen_selected(self):
        self.assertEqual(0, detect_marks(menu(border_width=3))["detected_mark_boxes"])

    def test_thick_selection_frame_on_dropdown_is_detected(self):
        self.assertGreater(detect_marks(menu(marked=True))["detected_mark_boxes"], 0)

    def test_thin_hand_drawn_ellipse_is_not_exempted(self):
        self.assertGreater(detect_marks(menu(thin_penned=True))["detected_mark_boxes"], 0)

    def test_colorful_content_icons_are_not_selected_controls(self):
        self.assertEqual(0, detect_marks(decorative_icons())["detected_mark_boxes"])

    def test_colorful_icons_plus_real_selected_control_must_block(self):
        self.assertGreater(detect_marks(decorative_icons(selected=True))["detected_mark_boxes"], 0)

    def test_jpeg_compressed_icon_image_remains_clean(self):
        self.assertEqual(0, detect_marks(decorative_icons(jpeg=True))["detected_mark_boxes"])


if __name__ == "__main__":
    unittest.main()
