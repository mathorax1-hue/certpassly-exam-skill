import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from certpassly.pipeline import PlanError
from certpassly.upstream import expected_pin, upstream_command, run_upstream

ROOT = Path(__file__).resolve().parents[1]


class UpstreamTests(unittest.TestCase):
    def test_expected_upstream_pin(self):
        self.assertEqual(len(expected_pin(ROOT)), 40)

    def test_reject_unapproved_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "upstream/scripts").mkdir(parents=True)
            (d / "upstream/scripts/run_pipeline.py").write_text("print('demo')")
            (d / "private").mkdir()
            with patch("certpassly.upstream.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "badsha\n", "")):
                with self.assertRaises(PlanError):
                    upstream_command(ROOT, d / "upstream", d / "private", "AB-900", ["extract"])

    def test_refuse_unknown_stage(self):
        with self.assertRaises(PlanError):
            upstream_command(ROOT, Path("."), Path("."), "AB-900", ["promote"])

    def test_no_shell_injection_in_exam_code(self):
        with self.assertRaises(PlanError):
            upstream_command(ROOT, Path("."), Path("."), "AB-900; echo x", ["extract"])

    def test_offline_default_and_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "upstream/scripts").mkdir(parents=True)
            (d / "upstream/scripts/run_pipeline.py").write_text("print('demo')")
            (d / "private").mkdir()
            pin = expected_pin(ROOT)
            with patch("certpassly.upstream.subprocess.run", return_value=subprocess.CompletedProcess([], 0, pin + "\n", "")) as mock:
                data = run_upstream(ROOT, d / "upstream", d / "private", "AB-900", ["extract"], True, True)
            self.assertEqual(mock.call_count, 1)
            self.assertEqual(data["status"], "dry_run")
            self.assertTrue(data["offline"])


if __name__ == "__main__":
    unittest.main()
