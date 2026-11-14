"""Black-box B4 CLI tests: exact original flags, no answer content or site access."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_media_layout_contract import registry, layout


class LayoutCliTests(unittest.TestCase):
    def _run(self, type_key):
        with tempfile.TemporaryDirectory(prefix="layout-cli-synthetic-") as tmp:
            root = Path(tmp)
            (root / "registry.json").write_text(json.dumps(registry()), encoding="utf-8")
            (root / "layout.json").write_text(json.dumps(layout(type_key)), encoding="utf-8")
            script = Path(__file__).resolve().parents[1] / "scripts" / "validate_media_layout.py"
            run = subprocess.run([
                sys.executable, str(script), "--registry", str(root / "registry.json"),
                "--layout", str(root / "layout.json"), "--report", str(root / "report.json")
            ], capture_output=True, text=True, timeout=30,
                env=os.environ.copy())
            self.assertTrue((root / "report.json").exists(), run.stderr)
            report = json.loads((root / "report.json").read_text(encoding="utf-8"))
            return run.returncode, report

    def test_publishable_synthetic_contract_returns_zero(self):
        rc, report = self._run("inline_dropdown")
        self.assertEqual(rc, 0, report)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["site_ui_status"], "UNTESTED")
        self.assertEqual(report["human_review_status"], "NOT_APPROVED")

    def test_disabled_type_returns_2_never_downgrades(self):
        rc, report = self._run("terminal_task")
        self.assertEqual(rc, 2, report)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(report["publishable_in_registry"])


if __name__ == "__main__":
    unittest.main()
