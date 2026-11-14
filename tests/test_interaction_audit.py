"""B4 synthetic responsive hotspot/drop-zone accessibility and geometry audit."""
import unittest
from certpassly.media_prep.interaction_audit import audit_interaction_geometry
from tests.test_media_layout_contract import layout, registry


class InteractionGeometryAuditTests(unittest.TestCase):
    def test_large_hotspot_across_mobile_desktop_zoom_dpr(self):
        x=layout("hotspot_single")
        x["controls"]["hotspots"][0]["rect"]=[0.20,0.20,0.60,0.60]
        report=audit_interaction_geometry(x,registry(),native_width=1000,
                                          native_height=1000)
        self.assertEqual(report["status"],"MACHINE_GEOMETRY_PASS",report["problems"])
        self.assertEqual(len(report["cases"]),20)
        self.assertEqual(report["site_ui_status"],"UNTESTED")
        self.assertEqual(report["keyboard_status"],"UNTESTED")

    def test_tiny_hotspot_rejected_at_320_css(self):
        x=layout("hotspot_multi")
        x["controls"]["hotspots"][0]["rect"]=[0.1,0.1,0.15,0.15]
        report=audit_interaction_geometry(x,registry(),native_width=1000,
                                          native_height=800)
        self.assertEqual(report["status"],"MACHINE_GEOMETRY_BLOCKED")
        reasons={p["reason"] for p in report["problems"]}
        self.assertIn("TOUCH_TARGET_TOO_SMALL",reasons)

    def test_overlapping_drag_zones_blocked(self):
        x=layout("drag_drop")
        x["controls"]["drop_zones"]=[
            {"id":"zone-1","rect":[0.1,0.1,0.65,0.65]},
            {"id":"zone-2","rect":[0.2,0.2,0.75,0.75]},
        ]
        report=audit_interaction_geometry(x,registry(),native_width=1200,
                                          native_height=1000)
        self.assertEqual(report["status"],"MACHINE_GEOMETRY_BLOCKED")
        self.assertIn("TARGETS_OVERLAP", {p["reason"] for p in report["problems"]})

    def test_missing_original_dimensions_block(self):
        x=layout("hotspot_single")
        rep=audit_interaction_geometry(x,registry(),native_width=0,
                                        native_height=1000)
        self.assertEqual(rep["status"],"MACHINE_GEOMETRY_BLOCKED")
        self.assertIn("ORIGINAL_IMAGE_GEOMETRY_REQUIRED",
                      {p["reason"] for p in rep["problems"]})

    def test_rotated_90_hotspot_maps_inside_display_bounds(self):
        x=layout("hotspot_single")
        x["source"]["rotation_deg"]=90
        x["controls"]["hotspots"][0]["rect"]=[0.1,0.1,0.5,0.7]
        rep=audit_interaction_geometry(x,registry(),native_width=800,native_height=1200)
        self.assertEqual(rep["status"],"MACHINE_GEOMETRY_PASS",rep["problems"])
        for case in rep["cases"]:
            for tar in case["targets"]:
                self.assertGreaterEqual(tar["css_box"][0],0)
                self.assertLessEqual(tar["css_box"][2],case["display_width_css_px"])
                self.assertLessEqual(tar["css_box"][3],case["display_height_css_px"])

    def test_missing_polygon_hotspot_geometry_fails_closed(self):
        x=layout("hotspot_multi")
        x["controls"]["hotspots"][0].pop("rect")
        rep=audit_interaction_geometry(x,registry(),native_width=800,native_height=800)
        self.assertEqual(rep["status"],"MACHINE_GEOMETRY_BLOCKED")
        self.assertIn("LAYOUT_CONTRACT_BLOCKED",{p["reason"] for p in rep["problems"]})


if __name__=="__main__":
    unittest.main()
