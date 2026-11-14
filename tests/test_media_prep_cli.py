"""Media-prep CLI contract tests: subcommands, flags, exit codes, doctor.

The exit-code contract is a stable public interface:
  0 = applicable machine gates passed
  1 = invalid config or operational failure
  2 = blocked source / ambiguous / missing clean source
  3 = privacy / integrity / manifest-tamper refusal
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from media_prep_fixture import HAS_IMAGE_DEPS, build_full_workspace  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if HAS_IMAGE_DEPS:
    from certpassly.media_prep import cli as mp_cli


@unittest.skipUnless(HAS_IMAGE_DEPS, "image extras not installed")
class CliContractTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="mp-cli-")
        cls.facts = build_full_workspace(os.path.join(cls.root, "ws"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def _run(self, *argv):
        return mp_cli.main(list(argv))

    def test_doctor_json_and_modules(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self._run("doctor", "--json")
        self.assertEqual(rc, 0)
        rep = json.loads(buf.getvalue())
        self.assertEqual(rep["toolkit"], "certpassly-media-prep")
        self.assertTrue(rep["media_prep_ready"])
        self.assertEqual(rep["upstream_pin"]["commit"],
                         "13dea6bab662ab1c4bbf87017e912e519907c8bc")
        self.assertFalse(rep["release_authority"])

    def test_doctor_with_config_reports_upstream(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self._run("doctor", "--json", "--config", self.facts["config"])
        self.assertEqual(rc, 0)
        rep = json.loads(buf.getvalue())
        cu = rep["configured_upstream"]
        self.assertFalse(cu["configured"])

    def test_scan_invalid_config_exit_1(self):
        bad = os.path.join(self.root, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"schema_version": "wrong"}, f)
        rc = self._run("scan", "--config", bad)
        self.assertEqual(rc, 1)

    def test_scan_missing_pdf_exit_1(self):
        cfg = json.load(open(self.facts["config"]))
        cfg["source"]["pdf"] = os.path.join(self.root, "missing.pdf")
        p = os.path.join(self.root, "missing-cfg.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        rc = self._run("scan", "--config", p)
        self.assertEqual(rc, 1)

    def test_scan_sha_mismatch_exit_1(self):
        cfg = json.load(open(self.facts["config"]))
        cfg["source"]["expected_sha256"] = "0" * 64
        p = os.path.join(self.root, "sha-cfg.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        rc = self._run("scan", "--config", p)
        self.assertEqual(rc, 1)

    def test_scan_blocked_exit_2_and_json(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self._run("scan", "--config", self.facts["config"], "--json")
        self.assertEqual(rc, 2)
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc["counts"]["blocked"], 9)

    def test_prepare_dry_run_writes_no_files(self):
        out = os.path.join(self.root, "dryrun-out")
        rc = self._run("prepare", "--config", self.facts["config"],
                       "--out-dir", out, "--dry-run")
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(out), "dry-run must not write output files")

    def test_prepare_out_dir_override(self):
        out = os.path.join(self.root, "override-out")
        rc = self._run("prepare", "--config", self.facts["config"],
                       "--out-dir", out)
        self.assertEqual(rc, 2)
        self.assertTrue(os.path.isdir(out))
        self.assertEqual(len(os.listdir(out)), 7)

    def test_prepare_refuses_inside_upstream_workspace(self):
        cfg = json.load(open(self.facts["config"]))
        cfg["output"]["clean_dir"] = os.path.join(cfg["upstream"]["out_dir"],
                                                  "media", "clean")
        p = os.path.join(self.root, "inside-cfg.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        rc = self._run("prepare", "--config", p)
        self.assertEqual(rc, 1)

    def test_verify_package_missing_zip_exit_1(self):
        rc = self._run("verify-package", "--config", self.facts["config"],
                       "--package", os.path.join(self.root, "nope.zip"))
        self.assertEqual(rc, 1)

    def test_verify_package_not_a_zip_exit_1(self):
        notzip = os.path.join(self.root, "not.zip")
        with open(notzip, "wb") as f:
            f.write(b"this is not a zip file")
        rc = self._run("verify-package", "--config", self.facts["config"],
                       "--package", notzip)
        self.assertEqual(rc, 1)

    def test_python_dash_m_entry_point(self):
        """python -m certpassly.media_prep --help works and lists subcommands."""
        import subprocess
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.join(REPO_ROOT, "src") + os.pathsep + env.get("PYTHONPATH", "")
        r = subprocess.run([sys.executable, "-m", "certpassly.media_prep", "--help"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        for cmd in ("doctor", "scan", "prepare", "verify-package"):
            self.assertIn(cmd, r.stdout)

    def test_help_lists_every_subcommand(self):
        import contextlib
        import io
        for cmd in ("doctor", "scan", "prepare", "verify-package"):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit) as cm:
                    mp_cli.build_parser().parse_args([cmd, "--help"])
            self.assertEqual(cm.exception.code, 0)
            self.assertIn(cmd, buf.getvalue())


if __name__ == "__main__":
    unittest.main()
