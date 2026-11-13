"""Public synthetic tests: config loading, provenance resolution and byte-compat
legacy labels, template schema presence (stdlib-only; run on public CI)."""
import json
import unittest
from pathlib import Path

from certpassly.phase1 import p1common as P

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "config" / "phase1-config.example.json"
TEMPLATE = REPO / "src" / "certpassly" / "phase1" / "templates" / "extraction-schema.v1.json"


class ConfigLoadingTests(unittest.TestCase):
    def test_example_config_loads(self):
        cfg = P.load_config(str(EXAMPLE))
        self.assertEqual(cfg["exam_code"], "EXAMPLE-EXAM")
        for key in ("pdf", "repo", "out_dir", "upstream_out", "pmap"):
            self.assertIn(key, cfg["paths"])

    def test_missing_exam_code_fails_closed(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cfg.json")
            with open(p, "w") as f:
                json.dump({"paths": {"pdf": "x", "repo": "x", "out_dir": "x",
                                     "upstream_out": "x", "pmap": "x"}}, f)
            with self.assertRaises(P.ConfigError):
                P.load_config(p)

    def test_missing_paths_key_fails_closed(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cfg.json")
            with open(p, "w") as f:
                json.dump({"exam_code": "SYN"}, f)
            with self.assertRaises(P.ConfigError):
                P.load_config(p)

    def test_invalid_json_fails_closed(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cfg.json")
            with open(p, "w") as f:
                f.write("{not json")
            with self.assertRaises(json.JSONDecodeError):
                P.load_config(p)


class ProvenanceTests(unittest.TestCase):
    def test_legacy_labels_are_byte_stable(self):
        # These exact strings keep replay of previously accepted extractions
        # byte-identical; changing them is a breaking change requiring review.
        self.assertEqual(P.LEGACY_TOOLKIT_LABEL,
                         "the config-driven phase1-extraction toolkit (`tools/phase1-extraction/`, ZAI-EXTRACT-002)")
        self.assertEqual(P.LEGACY_COMMANDS_REFERENCE,
                         "`tools/phase1-extraction/README.md`")
        self.assertEqual(P.LEGACY_BUILDER_SCRIPT,
                         "tools/phase1-extraction/build_structured_v1.py")
        self.assertEqual(P.LEGACY_AUDIT_TOOL,
                         "tools/phase1-extraction/audit_source.py")

    def test_provenance_default_is_legacy(self):
        self.assertEqual(P.provenance({}, "builder_script", P.LEGACY_BUILDER_SCRIPT),
                         P.LEGACY_BUILDER_SCRIPT)

    def test_provenance_override(self):
        cfg = {"provenance": {"builder_script": "certpassly.phase1.build_structured_v1 @ abc123"}}
        self.assertEqual(P.provenance(cfg, "builder_script", P.LEGACY_BUILDER_SCRIPT),
                         "certpassly.phase1.build_structured_v1 @ abc123")

    def test_provenance_empty_block_uses_legacy(self):
        self.assertEqual(P.provenance({"provenance": {}}, "builder_script",
                                      P.LEGACY_BUILDER_SCRIPT), P.LEGACY_BUILDER_SCRIPT)


class TemplateSchemaTests(unittest.TestCase):
    def test_template_exists_and_is_valid_json(self):
        self.assertTrue(TEMPLATE.is_file(), f"missing template: {TEMPLATE}")
        schema = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(schema.get("$schema"), "http://json-schema.org/draft-07/schema#")
        self.assertIn("question_record", schema.get("definitions", {}))
        self.assertIn("page_record", schema.get("definitions", {}))

    def test_example_config_declares_extension(self):
        cfg = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertIn("typed_text_with_answer_image",
                      cfg["schema"]["source_kind_extension"])

    def test_exam_code_pattern_allows_underscores(self):
        """Owner exam codes may contain underscores (e.g. vendor codes with
        underscores); the schema must not reject them."""
        import re
        schema = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        pattern = schema["definitions"]["question_record"]["properties"]["exam_code"]["pattern"]
        rx = re.compile(pattern)
        self.assertTrue(rx.match("FCP_FGT_AD-7.6"))
        self.assertTrue(rx.match("AB-900"))
        self.assertTrue(rx.match("AI-901"))
        self.assertFalse(rx.match("_ leading underscore rejected"))
        self.assertFalse(rx.match(""))

    def test_result_accumulator_fail_closed(self):
        r = P.Result()
        r.check("ok_check", True, "fine")
        r.check("bad_check", False, "problem")
        self.assertEqual(len(r.failed), 1)
        self.assertEqual(r.summary(), "1/2 passed")


if __name__ == "__main__":
    unittest.main()
