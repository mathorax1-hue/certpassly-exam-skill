"""B4 JSON schema and implementation parity for 30 synthetic type layouts."""
from __future__ import annotations
import json
from pathlib import Path
import unittest

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

from tests.test_media_layout_contract import layout, registry, PUBLISHABLE, NONPUBLISHABLE, DISABLED
from certpassly.media_prep.media_layout import validate_layout

SCHEMA = Path(__file__).resolve().parents[1] / "src" / "certpassly" / "media_prep" / "schemas" / "media-layout-v1.schema.json"


@unittest.skipUnless(HAS_JSONSCHEMA, "requires phase1 jsonschema extra")
class MediaLayoutSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(self.schema)
        self.validator = jsonschema.Draft202012Validator(self.schema)

    def test_all_30_type_examples_are_wellformed(self):
        for key in sorted(registry()["types"]):
            with self.subTest(type_key=key):
                specimen = layout(key)
                self.validator.validate(specimen)
                report = validate_layout(specimen, registry())
                self.assertEqual(report["status"], "PASS" if key in PUBLISHABLE else "BLOCKED")

    def test_strict_schema_rejects_unexpected_answer_fields(self):
        specimen = layout("single_choice")
        specimen["correct_option_ids"] = ["A"]
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(specimen)

    def test_bad_normalized_geometry_fails_source(self):
        specimen = layout("single_choice")
        specimen["source"]["crop"] = [0, 0, 2, 1]
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(specimen)


if __name__ == "__main__":
    unittest.main()
