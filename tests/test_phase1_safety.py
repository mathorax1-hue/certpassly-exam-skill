"""Public safety tests for the Phase 1 toolkit (stdlib-only; run on public CI).

1. No network-capable imports anywhere in the package source (strictly local
   tools; no upload/publication code paths).
2. No forbidden binary/exam artifacts inside the package or tests directory.
3. Package metadata and template ship with the wheel (package data).
"""
import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PHASE1_DIR = REPO / "src" / "certpassly" / "phase1"

FORBIDDEN_NETWORK_MODULES = {
    "socket", "ssl", "urllib", "urllib.request", "urllib.error", "urllib.parse",
    "http", "http.client", "ftplib", "smtplib", "telnetlib", "requests",
    "httpx", "aiohttp", "urllib3", "paramiko", "boto3", "ftp", "asyncio.streams",
}
FORBIDDEN_EXTENSIONS = {".pdf", ".zip", ".vce", ".7z", ".sqlite", ".sqlite3",
                        ".pem", ".p12", ".key"}


def _imports_of(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                yield node.module


class NoNetworkTests(unittest.TestCase):
    def test_no_network_imports_in_phase1_package(self):
        offenders = {}
        for py in sorted(PHASE1_DIR.glob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            bad = {m for m in _imports_of(tree) if m in FORBIDDEN_NETWORK_MODULES}
            if bad:
                offenders[py.name] = sorted(bad)
        self.assertEqual(offenders, {},
                         "Phase 1 toolkit must be strictly local (no network modules)")

    def test_subprocess_only_for_local_stage_orchestration(self):
        """subprocess is allowed ONLY for documented local use: run_all.py and
        adversarial.py (local ``python -m`` stages / pinned extractor) and
        p1common.py (read-only ``git rev-parse`` provenance helpers)."""
        allowed = {"run_all.py", "adversarial.py", "p1common.py"}
        for py in sorted(PHASE1_DIR.glob("*.py")):
            if py.name in allowed:
                continue
            tree = ast.parse(py.read_text(encoding="utf-8"))
            bad = [m for m in _imports_of(tree)
                   if m.split(".")[0] in {"subprocess", "os.system"}]
            self.assertEqual(bad, [], f"{py.name} must not shell out")


class NoPrivateArtifactTests(unittest.TestCase):
    def test_no_forbidden_files_in_package_and_tests(self):
        for base in (PHASE1_DIR, Path(__file__).resolve().parent,
                     REPO / "config"):
            for f in base.rglob("*"):
                if f.is_file() and f.suffix.lower() in FORBIDDEN_EXTENSIONS:
                    self.fail(f"forbidden artifact in public repo: {f}")

    def test_no_raw_exam_paths_in_public_sources(self):
        """No hardcoded private repository absolute paths in package code."""
        markers = ("/home/", "C:\\Users", "raw-exam/exams/", "ready-exams/")
        for py in sorted(PHASE1_DIR.glob("*.py")):
            text = py.read_text(encoding="utf-8")
            for marker in markers:
                self.assertNotIn(marker, text,
                                 f"{py.name} embeds a private path: {marker}")


class PackageDataTests(unittest.TestCase):
    def test_template_shipped_as_package_data(self):
        pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[tool.setuptools.package-data]", pyproject)
        self.assertIn('"certpassly.phase1"', pyproject)
        self.assertTrue((PHASE1_DIR / "templates" / "extraction-schema.v1.json").is_file())

    def test_example_config_is_synthetic(self):
        text = (REPO / "config" / "phase1-config.example.json").read_text(encoding="utf-8")
        cfg = __import__("json").loads(text)
        self.assertEqual(cfg["exam_code"], "EXAMPLE-EXAM")
        self.assertNotIn("AB-900", text)
        self.assertNotIn("AI-901", text)

    def test_metadata_constants(self):
        from certpassly.phase1 import (SCHEMA_COMPATIBLE_EXTENSIONS,
                                       STRUCTURED_SCHEMA_VERSION, UPSTREAM_PIN,
                                       UPSTREAM_REPO)
        self.assertEqual(STRUCTURED_SCHEMA_VERSION, "structured-v1")
        self.assertEqual(UPSTREAM_REPO, "msaqlainhaneef1/certpassly-exam-pipeline")
        self.assertRegex(UPSTREAM_PIN, r"^[0-9a-f]{40}$")
        self.assertIn("typed_text_with_answer_image", SCHEMA_COMPATIBLE_EXTENSIONS)


if __name__ == "__main__":
    unittest.main()
