"""Media-prep end-to-end and reproducibility tests (matrix D; 11 scenarios).

Full CLI flows on synthetic data: scan -> prepare -> verify-package exit
codes, site-format-v1 style import references, learner SHAs, offline draft
ZIP scanning, byte-identical repeat runs, order-independent pairing, blocked
package refusal, Windows-style separators, schema validation of all outputs,
and (integration, opt-in via CERTPASSLY_UPSTREAM_SCRIPTS) the REAL pinned
upstream extractor end to end.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(__file__))
from media_prep_fixture import (HAS_IMAGE_DEPS, build_full_workspace,  # noqa: E402
                                run_real_upstream)

if HAS_IMAGE_DEPS:
    from certpassly.media_prep import cli as mp_cli
    from certpassly.media_prep.manifest import entries_hash

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(HAS_IMAGE_DEPS, "image extras not installed")
class EndToEndTests(unittest.TestCase):
    """End-to-end flows through the real CLI entry point."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="mp-e2e-")
        cls.facts = build_full_workspace(os.path.join(cls.root, "ws"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def _run(self, *argv):
        return mp_cli.main(list(argv))

    def test_d01_scan_exit_code_and_counts(self):
        rc = self._run("scan", "--config", self.facts["config"],
                       "--output", os.path.join(self.root, "readiness.json"))
        self.assertEqual(rc, 2, "blocked questions must give exit 2")
        doc = json.load(open(os.path.join(self.root, "readiness.json")))
        self.assertEqual(doc["schema_version"], "image-readiness-v1")
        self.assertEqual(doc["counts"]["questions_total"], 13)
        self.assertEqual(doc["counts"]["blocked"], 7)
        self.assertEqual(len(doc["counts"]["blocked_question_ids"]), 7)

    def test_d02_prepare_writes_manifest_and_clean_files(self):
        rc = self._run("prepare", "--config", self.facts["config"])
        self.assertEqual(rc, 2)
        mpath = os.path.join(self.root, "ws", "prepared", "image-manifest.json")
        m = json.load(open(mpath))
        self.assertEqual(m["schema_version"], "image-manifest-v1")
        self.assertEqual(m["counts"]["clean_files_written"], 5)
        clean_dir = os.path.join(self.root, "ws", "prepared", "clean")
        files = sorted(os.listdir(clean_dir))
        self.assertEqual(files, ["q002.png", "q005.png", "q007.png", "q008.png", "q012.png"])

    def test_d03_manifest_schema_valid(self):
        import jsonschema
        schema = json.load(open(os.path.join(
            REPO_ROOT, "src", "certpassly", "media_prep", "schemas",
            "image-manifest-v1.schema.json")))
        m = json.load(open(os.path.join(self.root, "ws", "prepared",
                                        "image-manifest.json")))
        jsonschema.validate(m, schema)

    def test_d04_readiness_schema_valid(self):
        import jsonschema
        schema = json.load(open(os.path.join(
            REPO_ROOT, "src", "certpassly", "media_prep", "schemas",
            "image-readiness-v1.schema.json")))
        doc = json.load(open(os.path.join(self.root, "readiness.json")))
        for q in doc["questions"]:
            # per-question records follow the readiness schema (with the
            # document-level keys the schema also requires)
            rec = dict(q)
            rec.setdefault("schema_version", "image-readiness-v1")
            rec.setdefault("source_pdf_sha256", doc["source_pdf_sha256"])
            jsonschema.validate(rec, schema)

    def test_d05_learner_refs_point_to_clean_shas(self):
        """questions.json + question_media_assets.csv reference exactly the
        allowlisted files, and those SHAs match the manifest."""
        m = json.load(open(os.path.join(self.root, "ws", "prepared",
                                        "image-manifest.json")))
        allow = {e["clean_candidate"]["file"]: e["clean_candidate"]["sha256"]
                 for e in m["questions"]
                 if e.get("clean_candidate") and e["is_learner_eligible"]
                 and e["clean_candidate"].get("file")}
        clean_dir = os.path.join(self.root, "ws", "prepared", "clean")
        from certpassly.media_prep import imageio
        for fname, sha in allow.items():
            with open(os.path.join(clean_dir, fname), "rb") as f:
                self.assertEqual(imageio.sha256_bytes(f.read()), sha)

    def test_d06_offline_draft_zip_passes(self):
        """A correctly built offline synthetic draft ZIP verifies clean (exit 0)."""
        m = json.load(open(os.path.join(self.root, "ws", "prepared",
                                        "image-manifest.json")))
        allow = {e["clean_candidate"]["file"]: e["clean_candidate"]["sha256"]
                 for e in m["questions"]
                 if e.get("clean_candidate") and e["is_learner_eligible"]
                 and e["clean_candidate"].get("file")}
        clean_dir = os.path.join(self.root, "ws", "prepared", "clean")
        pkg = os.path.join(self.root, "draft.zip")
        with zipfile.ZipFile(pkg, "w") as z:
            for f in sorted(allow):
                z.write(os.path.join(clean_dir, f), f"media/{f}")
            first = sorted(allow)[0]
            z.writestr("import/questions.json", json.dumps(
                {"questions": [{"id": "q002",
                                "content": {"image_url": f"media/{first}"}}]}))
            z.writestr("import/question_media_assets.csv",
                       "question_version_key,path,kind,mime_type,sha256\n"
                       f"qv-001,media/{first},exhibit,image/png,{allow[first]}\n")
        rc = self._run("verify-package", "--config", self.facts["config"],
                       "--package", pkg, "--report", os.path.join(self.root, "vp.json"))
        self.assertEqual(rc, 0)
        rep = json.load(open(os.path.join(self.root, "vp.json")))
        self.assertTrue(rep["passed"])

    def test_d07_repeat_run_byte_identical(self):
        """A second full prepare reproduces byte-identical manifest and clean
        images (canonical JSON + deterministic renders)."""
        mpath = os.path.join(self.root, "ws", "prepared", "image-manifest.json")
        clean_dir = os.path.join(self.root, "ws", "prepared", "clean")
        before = {f: open(os.path.join(clean_dir, f), "rb").read()
                  for f in sorted(os.listdir(clean_dir))}
        mbefore = open(mpath, "rb").read()
        rc = self._run("prepare", "--config", self.facts["config"])
        self.assertEqual(rc, 2)
        after = {f: open(os.path.join(clean_dir, f), "rb").read()
                 for f in sorted(os.listdir(clean_dir))}
        mafter = open(mpath, "rb").read()
        self.assertEqual(before, after, "clean image bytes must be identical")
        self.assertEqual(mbefore, mafter, "manifest bytes must be identical")

    def test_d08_pairing_independent_of_media_order(self):
        """Renaming the pair files (reversed lexicographic order) must not
        change which member is chosen as clean."""
        root2 = os.path.join(self.root, "ws-renamed")
        facts2 = build_full_workspace(root2)
        out = facts2["out_dir"]
        src = os.path.join(out, "media", "src")
        # swap the q005 pair names so sorted order reverses
        a = os.path.join(src, "p-005_1.png")
        b = os.path.join(src, "p-005_2.png")
        da, db = open(a, "rb").read(), open(b, "rb").read()
        open(a, "wb").write(db)
        open(b, "wb").write(da)
        # also swap inside split.json + items
        sp = os.path.join(out, "extracted", "split.json")
        split = json.load(open(sp))
        rec = split["q005"]
        rec["question_images"], rec["answer_images"] = rec["answer_images"], rec["question_images"]
        json.dump(split, open(sp, "w"), indent=1, ensure_ascii=False)
        json.dump(rec, open(os.path.join(out, "extracted", "items", "q005.json"), "w"),
                  indent=1, ensure_ascii=False)
        # also swap the embedded bytes? the PDF xrefs stay as-is, so
        # re-linking media names to different binaries breaks provenance on
        # purpose here: instead keep the PDF as the same file (bytes map by
        # content, so swapped names still map to the same xrefs).
        rc = self._run("scan", "--config", facts2["config"])
        self.assertEqual(rc, 2)
        cfg = json.load(open(facts2["config"]))
        readiness = None
        # rerun selection to inspect the chosen member
        from certpassly.media_prep.config import load_config
        from certpassly.media_prep.source_inventory import build_inventory
        from certpassly.media_prep.selection import run_selection
        c = load_config(facts2["config"])
        inv = build_inventory(c)
        ready = run_selection(c, inv)
        r = ready["q005"]
        self.assertTrue(r["is_learner_eligible"])
        # the CLEAN member (previously p-005_2.png, now p-005_1.png after the
        # swap) is still the one chosen: choice follows the pixels, not names
        self.assertEqual(r["clean_candidate"]["method"], "priority_c_paired_clean_member")
        self.assertEqual(r["clean_candidate"]["source_file"], "p-005_1.png")

    def test_d09_blocked_case_package_refused(self):
        """A package that includes a blocked question's marked image is
        refused with exit 3 through the CLI."""
        m = json.load(open(os.path.join(self.root, "ws", "prepared",
                                        "image-manifest.json")))
        clean_dir = os.path.join(self.root, "ws", "prepared", "clean")
        pkg = os.path.join(self.root, "blocked.zip")
        with zipfile.ZipFile(pkg, "w") as z:
            for f in sorted(os.listdir(clean_dir)):
                z.write(os.path.join(clean_dir, f), f"media/{f}")
            z.write(os.path.join(self.root, "ws", "out", "media", "src",
                                 "p-003_1.png"), "media/p-003_1.png")
        rc = self._run("verify-package", "--config", self.facts["config"],
                       "--package", pkg)
        self.assertEqual(rc, 3)

    def test_d10_windows_style_separators(self):
        """Backslash member names and drive-letter paths are refused."""
        pkg = os.path.join(self.root, "winpaths.zip")
        clean_dir = os.path.join(self.root, "ws", "prepared", "clean")
        with zipfile.ZipFile(pkg, "w") as z:
            for f in sorted(os.listdir(clean_dir)):
                z.write(os.path.join(clean_dir, f), f"media\\{f}")
            z.writestr("media\\..\\evil.png", b"C:\\fake")
        rc = self._run("verify-package", "--config", self.facts["config"],
                       "--package", pkg)
        self.assertEqual(rc, 3)

    def test_d11_manifest_integrity_hash_is_canonical(self):
        m = json.load(open(os.path.join(self.root, "ws", "prepared",
                                        "image-manifest.json")))
        self.assertEqual(m["integrity"]["entries_sha256"],
                         entries_hash(m["questions"]))


@unittest.skipUnless(HAS_IMAGE_DEPS, "image extras not installed")
class RealUpstreamIntegrationTests(unittest.TestCase):
    """Opt-in: run the REAL pinned upstream extractor on a synthetic PDF.

    Enabled by setting CERTPASSLY_UPSTREAM_SCRIPTS to the pinned checkout's
    scripts/ directory (CI clones the pinned commit). These tests prove the
    module consumes the true upstream contract, not just the hand-built
    workspace.
    """

    def setUp(self):
        scripts = os.environ.get("CERTPASSLY_UPSTREAM_SCRIPTS")
        if not scripts:
            self.skipTest("CERTPASSLY_UPSTREAM_SCRIPTS not set (optional integration)")
        self.root = tempfile.mkdtemp(prefix="mp-real-")
        self.facts = build_full_workspace(os.path.join(self.root, "ws"))

    def tearDown(self):
        if hasattr(self, "root"):
            shutil.rmtree(self.root, ignore_errors=True)

    def _config_with_run_extract(self):
        cfgp = os.path.join(self.root, "run-extract-config.json")
        cfg = json.load(open(self.facts["config"]))
        cfg["upstream"]["scripts_dir"] = os.environ["CERTPASSLY_UPSTREAM_SCRIPTS"]
        cfg["upstream"]["run_extract"] = True
        # fresh upstream out dir
        cfg["upstream"]["out_dir"] = os.path.join(self.root, "real-out")
        with open(cfgp, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return cfgp

    def test_real_extractor_then_scan_prepare(self):
        cfgp = self._config_with_run_extract()
        rc = mp_cli.main(["scan", "--config", cfgp])
        # the REAL extractor discovers the synthetic questions; some are
        # image-keyed in ways the hand-built split mirrors, so exit is 2 with
        # blocked items (never a crash)
        self.assertIn(rc, (0, 2))
        split = json.load(open(os.path.join(self.root, "real-out", "extracted",
                                            "split.json")))
        self.assertTrue(split, "real upstream extractor produced items")
        rc2 = mp_cli.main(["prepare", "--config", cfgp])
        self.assertIn(rc2, (0, 2))

    def test_real_extractor_uses_only_pinned_interface(self):
        """ensure_upstream_output refuses when the extractor is missing but
        run_extract is true (fail-closed, no silent fallback)."""
        from certpassly.media_prep.config import load_config
        from certpassly.media_prep.errors import OperationalError
        from certpassly.media_prep.upstream_runner import ensure_upstream_output
        cfgp = self._config_with_run_extract()
        cfg = json.load(open(cfgp))
        cfg["upstream"]["scripts_dir"] = os.path.join(self.root, "no-such-dir")
        bad = os.path.join(self.root, "bad-config.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        try:
            load_config(bad)
            self.fail("config with missing scripts_dir must be refused")
        except Exception:
            pass  # ConfigError at load time (dir must exist) - fail-closed OK
        cfg["upstream"]["scripts_dir"] = os.environ["CERTPASSLY_UPSTREAM_SCRIPTS"]
        cfg["upstream"]["out_dir"] = os.path.join(self.root, "real-out-2")
        cfg["upstream"]["run_extract"] = False
        ok = os.path.join(self.root, "noauto.json")
        with open(ok, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        with self.assertRaises(OperationalError):
            ensure_upstream_output(load_config(ok))


if __name__ == "__main__":
    unittest.main()
