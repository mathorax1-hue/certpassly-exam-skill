"""Public synthetic tests: certpassly CLI surface for the Phase 1 toolkit
(phase1-info metadata, phase1-extract dry-run, phase1-audit argument gates).
Stdlib-only on CI; the fitz-gated real audit run is in test_phase1_audit.py."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from certpassly.cli import main
from certpassly.phase1 import UPSTREAM_PIN, TOOLKIT_VERSION

from phase1_fixture import build_fixture


class Phase1CLITests(unittest.TestCase):
    def test_phase1_info_metadata(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = main(["phase1-info"])
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["toolkit_version"], TOOLKIT_VERSION)
        self.assertEqual(data["upstream_pin"], UPSTREAM_PIN)
        self.assertEqual(data["upstream_pin"],
                         "13dea6bab662ab1c4bbf87017e912e519907c8bc")
        self.assertIn("typed_text_with_answer_image",
                      data["schema_compatible_extensions"])
        self.assertFalse(data["release_authority"])
        self.assertIn("none", data["network_access"])

    def test_phase1_extract_dry_run_through_cli(self):
        root = tempfile.mkdtemp(prefix="phase1-cli-")
        try:
            cfg = build_fixture(root)
            cfg_path = os.path.join(root, "config.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=1)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = main(["phase1-extract", "--config", cfg_path,
                             "--upstream-scripts", root, "--dry-run"])
            self.assertEqual(code, 0)
            text = out.getvalue()
            self.assertIn("DRY RUN", text)
            self.assertIn("certpassly.phase1.build_structured_v1", text)
            self.assertIn("not written in dry-run", text)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_phase1_extract_requires_config(self):
        with self.assertRaises(SystemExit) as cm:
            with contextlib.redirect_stderr(io.StringIO()):
                main(["phase1-extract", "--upstream-scripts", "."])
        self.assertEqual(cm.exception.code, 2)  # argparse missing required arg

    def test_phase1_audit_requires_pdf(self):
        with self.assertRaises(SystemExit) as cm:
            with contextlib.redirect_stderr(io.StringIO()):
                main(["phase1-audit"])
        self.assertEqual(cm.exception.code, 2)

    def test_phase1_audit_missing_pdf_file_reports_error(self):
        """A nonexistent PDF must fail loudly, never fabricate an audit."""
        try:
            import fitz  # noqa: F401
            have_fitz = True
        except ImportError:
            have_fitz = False
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = main(["phase1-audit", "--pdf", "/nonexistent/synthetic.pdf"])
        if have_fitz:
            # fitz.open on a missing file raises; the CLI must surface an error
            self.assertNotEqual(code, 0)
        else:
            self.assertEqual(code, 3)
            self.assertIn("pdf extra", err.getvalue())


if __name__ == "__main__":
    unittest.main()
