"""Synthetic registry tests: no private paths or exam fixtures."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_tool_registry.py"
spec = importlib.util.spec_from_file_location("verify_tool_registry", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class ToolRegistryTest(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "config" / "tool-registry.json").read_text())

    def test_real_registry_paths_exist_and_policy_is_strict(self):
        self.assertEqual(tool.validate(ROOT, self.data), [])

    def test_duplicate_id_and_path_rejected(self):
        d = copy.deepcopy(self.data)
        d["tools"].append(copy.deepcopy(d["tools"][0]))
        errors = tool.validate(ROOT, d)
        self.assertTrue(any("duplicate tool ID" in x for x in errors))
        self.assertTrue(any("duplicate tool path" in x for x in errors))

    def test_missing_file_and_escape_rejected(self):
        d = copy.deepcopy(self.data)
        d["tools"][0]["path"] = "../secret"
        d["tools"][1]["test"] = "tests/nonexistent.py"
        errors = tool.validate(ROOT, d)
        self.assertTrue(any("unsafe path" in x for x in errors))
        self.assertTrue(any("missing test" in x for x in errors))

    def test_cannot_register_public_release_authority(self):
        d = copy.deepcopy(self.data)
        d["tools"][0]["release_authority"] = True
        d["rules"]["independent_reviewer_required"] = False
        errors = tool.validate(ROOT, d)
        self.assertTrue(any("release authority" in x for x in errors))
        self.assertTrue(any("reviewer gate" in x for x in errors))


if __name__ == "__main__":
    unittest.main()
