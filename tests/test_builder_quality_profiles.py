"""B3 synthetic source-pixel quality gates across responsive displays."""
from __future__ import annotations
import io
import unittest
try:
    from PIL import Image, ImageDraw, ImageFilter
    import cv2  # noqa: F401
    import numpy  # noqa: F401
    from certpassly.media_prep.imageio import SourceImage
    from certpassly.media_prep.quality import responsive_density_matrix, region_blur_matrix
    HAS_VISUAL = True
except ImportError:
    HAS_VISUAL = False


def _image(w=900, h=600, *, blurred_bottom=False):
    canvas = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(canvas)
    for y in range(15, h, 15):
        draw.line([(5, y), (w-5, y)], fill=(30, 30, 30), width=2)
    if blurred_bottom:
        half = canvas.crop((0, h//2, w, h)).filter(ImageFilter.GaussianBlur(5))
        canvas.paste(half, (0, h//2))
    out = io.BytesIO()
    canvas.save(out, "PNG")
    return SourceImage("synthetic.png", out.getvalue())


@unittest.skipUnless(HAS_VISUAL, "requires Pillow and OpenCV")
class ResponsiveQualityTests(unittest.TestCase):
    def test_native_613px_cannot_become_2x_640css_by_upscale(self):
        raw = _image(613, 400)
        digest = raw.sha256
        matrix = responsive_density_matrix(raw)
        self.assertEqual(len(matrix["rows"]), 20)
        desktop = [x for x in matrix["rows"]
                   if x["viewport_css_px"] == 1440 and x["dpr"] == 2 and x["zoom"] == 1][0]
        self.assertFalse(desktop["meets_minimum_density"])
        self.assertFalse(desktop["meets_device_sample_budget"])
        self.assertEqual(raw.sha256, digest)
        self.assertFalse(matrix["site_render_tested"])

    def test_mobile_320_css_at_dpr1_is_supported_by_900_native_pixels(self):
        m = responsive_density_matrix(_image())
        mobile = [x for x in m["rows"]
                  if x["viewport_css_px"] == 320 and x["dpr"] == 1 and x["zoom"] == 1][0]
        self.assertTrue(mobile["meets_device_sample_budget"])
        wide = [x for x in m["rows"]
                if x["viewport_css_px"] == 1440 and x["dpr"] == 2 and x["zoom"] == 2][0]
        self.assertFalse(wide["meets_device_sample_budget"])

    def test_regional_blur_not_hidden_by_sharp_upper_half(self):
        src = _image(600, 600, blurred_bottom=True)
        report = region_blur_matrix(src, columns=1, rows=2)
        upper, lower = report["tiles"]
        self.assertGreater(upper["blur_laplacian_variance"],
                           lower["blur_laplacian_variance"] * 2.0)
        self.assertFalse(report["semantic_text_legibility_tested"])

    def test_invalid_display_parameters_are_rejected(self):
        for args in ({"max_css_width": 0}, {"dprs": (0,)}, {"zooms": (-1,)},
                     {"viewports": (float("nan"),)}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                responsive_density_matrix(_image(), **args)


if __name__ == "__main__":
    unittest.main()
