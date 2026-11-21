"""Tests for the site import gate wrapper. No live website and no port 3306."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_site_import_gate.py"
spec = importlib.util.spec_from_file_location("run_site_import_gate", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class SiteImportGateTests(unittest.TestCase):
    def test_refuses_missing_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site.json"
            site.write_text("{}", encoding="utf-8")
            rc = tool.main([
                "--sandbox", str(Path(tmp) / "missing"),
                "--site-file", str(site),
                "--output", str(Path(tmp) / "out.json"),
            ])
            self.assertEqual(rc, 2)

    def test_php_command_uses_sandbox_and_report_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            sb = Path(tmp) / "sandbox"
            sb.mkdir()
            (sb / "artisan").write_text("<?php\n", encoding="utf-8")
            site = Path(tmp) / "site.json"
            site.write_text("{}", encoding="utf-8")
            out = Path(tmp) / "out.json"
            with patch("scripts.run_site_import_gate.subprocess.run" if False else "subprocess.run") as mock:
                # patch via the loaded module
                pass
            with patch.object(tool.subprocess, "run") as mock:
                mock.return_value = type("R", (), {"returncode": 2})()
                rc = tool.main(["--sandbox", str(sb), "--site-file", str(site), "--output", str(out), "--php", "php"])
            self.assertEqual(rc, 2)
            args = mock.call_args[0][0]
            self.assertEqual(args[0], "php")
            self.assertTrue(args[1].endswith("site_import_gate.php"))
            self.assertIn(f"--sandbox={sb}", args)
            self.assertIn(f"--file={site}", args)
            self.assertIn(f"--report={out}", args)


if __name__ == "__main__":
    unittest.main()
