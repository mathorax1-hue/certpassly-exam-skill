"""Media-prep privacy negative/adversarial tests (matrix C; 15 scenarios).

Every scenario builds a SYNTHETIC draft ZIP from the synthetic workspace and
asserts the privacy gate REFUSES it (exit-3 class) with the exact reason and
NO leak. Per the operator order, image-perceptual scans alone never prove
correctness: the gate is allowlist + provenance based.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(__file__))
from media_prep_fixture import HAS_IMAGE_DEPS, build_full_workspace  # noqa: E402

if HAS_IMAGE_DEPS:
    from PIL import Image
    from certpassly.media_prep import imageio
    from certpassly.media_prep.errors import PrivacyViolationError
    from certpassly.media_prep.privacy_gate import (build_allowlist, enforce,
                                                    load_manifest,
                                                    reviewer_only_shas,
                                                    verify_package)
    from certpassly.media_prep import cli as mp_cli


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            if isinstance(data, str):
                data = data.encode("utf-8")
            z.writestr(name, data)


def _png_reencoded(data, quality=70):
    """Re-encode image bytes as JPEG (bytes change; pixels ~same)."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


@unittest.skipUnless(HAS_IMAGE_DEPS, "image extras not installed")
class PrivacyMatrixTests(unittest.TestCase):
    """15 adversarial package scenarios - each must be REFUSED with a reason."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="mp-priv-")
        cls.facts = build_full_workspace(os.path.join(cls.root, "ws"))
        # run prepare through the real CLI to get a genuine manifest
        rc = mp_cli.main(["prepare", "--config", cls.facts["config"]])
        cls.prepare_rc = rc  # blocked questions exist -> rc 2 is expected
        cls.manifest_path = os.path.join(cls.root, "ws", "prepared", "image-manifest.json")
        cls.clean_dir = os.path.join(cls.root, "ws", "prepared", "clean")
        cls.private_dir = os.path.join(cls.root, "ws", "prepared", "private", "reviewer-only")
        cls.manifest = load_manifest(cls.manifest_path)
        cls.allow = build_allowlist(cls.manifest)
        cls.review_shas = reviewer_only_shas(cls.manifest)

        # a clean baseline package: only allowlisted images + text that
        # references them
        cls.good_members = {}
        for f in sorted(os.listdir(cls.clean_dir)):
            with open(os.path.join(cls.clean_dir, f), "rb") as fh:
                cls.good_members[f"media/{f}"] = fh.read()
        qrow = next(e for e in cls.manifest["questions"]
                    if e.get("clean_candidate") and e["is_learner_eligible"]
                    and e["clean_candidate"].get("file"))
        cls.qfile = qrow["clean_candidate"]["file"]
        cls.qsha = qrow["clean_candidate"]["sha256"]
        cls.good_members["import/questions.json"] = json.dumps({
            "questions": [{"id": qrow["question_id"],
                           "content": {"image_url": f"media/{cls.qfile}"}}]})
        cls.good_members["import/question_media_assets.csv"] = (
            "question_version_key,path,kind,mime_type,sha256\n"
            f"qv-001,media/{cls.qfile},exhibit,image/png,{cls.qsha}\n")
        cls.good_members["simulator/simulator_settings.json"] = json.dumps({
            "exam_key": "SYNTHETIC-DEMO", "scoring_excluded_question_keys": []})
        cls.good_zip = os.path.join(cls.root, "good.zip")
        _zip(cls.good_zip, cls.good_members)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def _refused_any(self, members, name, expected_reasons):
        path = os.path.join(self.root, name)
        _zip(path, members)
        report = verify_package(self.manifest_path, path)
        self.assertFalse(report["passed"], f"{name} must be refused")
        reasons = {p["reason"] for p in report["problems"]}
        self.assertTrue(expected_reasons & reasons,
                        f"{name}: expected one of {expected_reasons}, got {reasons}")
        with self.assertRaises(PrivacyViolationError):
            enforce(report)
        return report

    def _refused(self, members, name, expected_reason):
        path = os.path.join(self.root, name)
        _zip(path, members)
        report = verify_package(self.manifest_path, path)
        self.assertFalse(report["passed"], f"{name} must be refused")
        reasons = {p["reason"] for p in report["problems"]}
        self.assertIn(expected_reason, reasons,
                      f"{name}: expected {expected_reason}, got {reasons}")
        with self.assertRaises(PrivacyViolationError):
            enforce(report)
        return report

    # -- baseline ------------------------------------------------------------

    def test_c00_clean_package_passes(self):
        report = verify_package(self.manifest_path, self.good_zip)
        self.assertTrue(report["passed"], report["problems"])
        self.assertEqual(report["flags"], [])
        enforce(report)  # must not raise

    # -- the 15 negative scenarios -------------------------------------------

    def test_c01_marked_screenshot_swapped_into_exhibit(self):
        """A reviewer-only marked image shipped under a clean member name."""
        m = dict(self.good_members)
        m[f"media/{self.qfile}"] = open(
            os.path.join(self.private_dir, "p-002_2.png"), "rb").read()
        # the known-marked SHA check fires first (stronger than the manifest
        # mismatch); both are valid refusals for this attack
        report = self._refused_any(m, "c01.zip",
                                   {"SHA_MISMATCH_VS_MANIFEST",
                                    "REVIEWER_ONLY_BINARY_IN_PACKAGE"})
        self.assertIn("REVIEWER_ONLY_BINARY_IN_PACKAGE",
                      {p["reason"] for p in report["problems"]})

    def test_c02_same_marked_sha_renamed(self):
        """The marked binary renamed to an unrelated .png name (same SHA)."""
        m = dict(self.good_members)
        m["media/exhibit-pretty.png"] = open(
            os.path.join(self.private_dir, "p-002_2.png"), "rb").read()
        self._refused(m, "c02.zip", "REVIEWER_ONLY_BINARY_IN_PACKAGE")

    def test_c03_reencoded_marked_falsely_labeled_clean(self):
        """A re-encoded (bytes-changed) marked screenshot under a new name:
        not on the allowlist -> refused by PROVENANCE (allowlist issuance),
        exactly the boundary the order demands (perceptual hashes only alert)."""
        m = dict(self.good_members)
        marked = open(os.path.join(self.private_dir, "p-003_1.png"), "rb").read()
        m["media/exhibit-reencoded.png"] = _png_reencoded(marked)
        self._refused(m, "c03.zip", "UNALLOWED_IMAGE_MEMBER")

    def test_c04_manipulated_manifest_sha(self):
        """Editing any manifest entry (eligibility flip) breaks entries_sha256."""
        import copy
        m2 = copy.deepcopy(self.manifest)
        for e in m2["questions"]:
            if e["question_id"] == "q003":
                e["is_learner_eligible"] = True
        tampered = os.path.join(self.root, "tampered-manifest.json")
        with open(tampered, "w", encoding="utf-8") as f:
            json.dump(m2, f)
        with self.assertRaises(PrivacyViolationError):
            load_manifest(tampered)

    def test_c05_private_answer_binary_by_unrelated_path(self):
        """A reviewer-only image under an arbitrary deep path (same bytes)."""
        m = dict(self.good_members)
        m["assets/deep/nested/fineprint.png"] = open(
            os.path.join(self.private_dir, "p-011_1.png"), "rb").read()
        self._refused(m, "c05.zip", "REVIEWER_ONLY_BINARY_IN_PACKAGE")

    def test_c06_nested_zip_leak(self):
        """A nested ZIP inside the package is rejected outright (no recursive
        smuggling surface)."""
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as z:
            z.writestr("leak.png", open(
                os.path.join(self.private_dir, "p-002_2.png"), "rb").read())
        m = dict(self.good_members)
        m["media/bundle.zip"] = inner.getvalue()
        self._refused(m, "c06.zip", "NESTED_ZIP_REJECTED")

    def test_c07_path_traversal_member(self):
        """../ traversal member names are refused."""
        m = dict(self.good_members)
        m["../../etc/leak.png"] = b"\x89PNG\r\n\x1a\ntraversal"
        self._refused(m, "c07.zip", "PATH_TRAVERSAL_OR_ABSOLUTE")

    def test_c07b_symlink_member(self):
        """A symlink ZIP member is refused before its target is read."""
        m = dict(self.good_members)
        path = os.path.join(self.root, "c07b.zip")
        target = os.path.join(self.private_dir, "p-002_2.png")
        with zipfile.ZipFile(path, "w") as z:
            for k, v in self.good_members.items():
                z.writestr(k, v)
            info = zipfile.ZipInfo("media/link.png")
            info.create_system = 3  # unix
            info.external_attr = (0o120777 << 16)  # symlink mode
            z.writestr(info, target.encode())
        report = verify_package(self.manifest_path, path)
        reasons = {p["reason"] for p in report["problems"]}
        self.assertIn("SYMLINK_MEMBER", reasons)

    def test_c08_external_url(self):
        """An external image URL in learner-visible JSON is refused."""
        m = dict(self.good_members)
        m["import/questions.json"] = json.dumps({
            "questions": [{"id": "q002",
                           "content": {"image_url": "https://cdn.example.net/x.png"}}]})
        self._refused(m, "c08.zip", "EXTERNAL_URL")

    def test_c09_unknown_checksum_image(self):
        """A brand-new image (not allowlisted, not known-marked) is refused."""
        m = dict(self.good_members)
        m["media/unknown.png"] = png_fresh()
        self._refused(m, "c09.zip", "UNALLOWED_IMAGE_MEMBER")

    def test_c10_scoring_key_fails_gate_and_cli(self):
        """P0 CORRECTION CONTRACT: a learner-visible JSON with
        correct_option_ids makes report['passed'] FALSE for DIRECT library
        callers (not just a flag), enforce() raises, and the CLI exits 3."""
        m = dict(self.good_members)
        m["import/questions.json"] = json.dumps({
            "questions": [{"id": "q002", "correct_option_ids": ["a"],
                           "content": {"image_url": f"media/{self.qfile}"}}]})
        path = os.path.join(self.root, "c10.zip")
        _zip(path, m)
        report = verify_package(self.manifest_path, path)
        # the direct library contract: a key-bearing payload can NEVER pass
        self.assertFalse(report["passed"],
                         "P0 correction: scoring flags must fail report['passed']")
        flags = {f["flag"] for f in report["flags"]}
        self.assertIn("SITE_SCORING_ARCHITECTURE_REVIEW_REQUIRED", flags)
        with self.assertRaises(PrivacyViolationError):
            enforce(report)
        rc = mp_cli.main(["verify-package", "--config", self.facts["config"],
                          "--package", path])
        self.assertEqual(rc, 3)

    def test_c11_missing_image_with_sidecar_reference(self):
        """The allowlisted image is missing from the ZIP while the sidecar CSV
        still references it -> MISSING_CLEAN_IMAGE (plus ref refusal)."""
        m = {k: v for k, v in self.good_members.items()
             if k != f"media/{self.qfile}"}
        self._refused(m, "c11.zip", "MISSING_CLEAN_IMAGE")

    def test_c12_duplicate_asset_identity(self):
        """The same allowlisted basename at two paths -> duplicate identity."""
        m = dict(self.good_members)
        m[f"other/dir/{self.qfile}"] = self.good_members[f"media/{self.qfile}"]
        self._refused(m, "c12.zip", "DUPLICATE_ASSET_IDENTITY")

    def test_c13_raw_media_src_shipped(self):
        """An upstream media/src file (e.g. the marked exhibit) is caught by
        its SHA even though the name differs from the private copy."""
        m = dict(self.good_members)
        src_dir = os.path.join(self.facts["out_dir"], "media", "src")
        m["media/p-002_2.png"] = open(os.path.join(src_dir, "p-002_2.png"), "rb").read()
        self._refused(m, "c13.zip", "REVIEWER_ONLY_BINARY_IN_PACKAGE")

    def test_c14_publish_flag_rejected_in_draft(self):
        """is_published=true in any learner-visible file is refused in drafts."""
        m = dict(self.good_members)
        m["import/exams.json"] = '{"exam": {"is_published": true}}'
        self._refused(m, "c14.zip", "PUBLISH_FLAG_IN_DRAFT")

    def test_c15_legitimate_asset_dedup_allowed(self):
        """The same exhibit bytes under two DIFFERENT allowlisted names (asset
        reuse across questions) is legitimate and must NOT be refused."""
        m = dict(self.good_members)
        dup_entries = [e for e in self.manifest["questions"]
                       if e.get("clean_candidate") and e["is_learner_eligible"]
                       and e["clean_candidate"].get("file")]
        by_sha = {}
        for e in dup_entries:
            by_sha.setdefault(e["clean_candidate"]["sha256"], []).append(
                e["clean_candidate"]["file"])
        reusable = [files for files in by_sha.values() if len(files) >= 2]
        if not reusable:  # pragma: no cover - fixture guarantees a dup
            self.skipTest("fixture lacks a deduplicated asset")
        for files in reusable:
            for f in files:
                if f"media/{f}" not in m:
                    m[f"media/{f}"] = open(os.path.join(self.clean_dir, f), "rb").read()
        path = os.path.join(self.root, "c15.zip")
        _zip(path, m)
        report = verify_package(self.manifest_path, path)
        self.assertTrue(report["passed"], report["problems"])

    # -- 2026-11-14 P0 correction: trust-model hardening scenarios ---------

    def _regenerate_integrity(self, m):
        from certpassly.media_prep.manifest import (entries_hash,
                                                    package_integrity_hash)
        m["integrity"]["entries_sha256"] = entries_hash(m["questions"])
        m["integrity"]["package_integrity_sha256"] = package_integrity_hash(m)
        return m

    def test_c16_leaky_whole_page_render_in_regenerated_manifest(self):
        """THE q074 ATTACK: a whole-page render that visibly contains answer
        lines, wrapped in a FULLY REGENERATED manifest (every hash correctly
        recomputed, allowlist SHAs updated). Content re-verification against
        the pinned source must refuse it."""
        import copy
        from certpassly.media_prep import imageio
        from certpassly.media_prep.renderer import render_crop
        pdf = os.path.join(os.path.dirname(self.facts["config"]),
                           "synthetic-exam.pdf")
        leaky = render_crop(pdf, 15, (0, 0, 612, 792), dpi=120, annots=False)
        leaky_sha = imageio.sha256_bytes(leaky["png_bytes"])

        attack = copy.deepcopy(self.manifest)
        e15 = next(e for e in attack["questions"] if e["question_id"] == "q015")
        e15["clean_candidate"]["sha256"] = leaky_sha
        e15["clean_candidate"]["bytes"] = len(leaky["png_bytes"])
        e15["clean_candidate"]["render"]["clip"] = [0, 0, 792, 612]
        e15["clean_candidate"]["render"]["clip_unrotated"] = [0, 0, 612, 792]
        self._regenerate_integrity(attack)
        apath = os.path.join(self.root, "attack-manifest.json")
        json.dump(attack, open(apath, "w"), indent=1)

        members = {k: v for k, v in self.good_members.items()
                   if k != "import/questions.json"}
        members[f"media/{e15['clean_candidate']['file']}"] = leaky["png_bytes"]
        path = os.path.join(self.root, "c16.zip")
        _zip(path, members)
        # verify against the ATTACK manifest (all its hashes are correct) -
        # only content re-verification can catch the leak
        report = verify_package(apath, path, source_pdf=pdf)
        self.assertFalse(report["passed"],
                         "regenerated manifest + leaky whole-page render must "
                         "be refused by content re-verification")
        reasons = {p["reason"] for p in report["problems"]}
        self.assertTrue(reasons & {"ANSWER_TEXT_IN_RENDER",
                                   "QUESTION_CROP_UNVERIFIED"},
                        f"expected a crop/answer refusal, got {reasons}")
        with self.assertRaises(PrivacyViolationError):
            enforce(report)

    def test_c17_partial_edit_with_entries_hash_only_recompute(self):
        """Adversary fixes the legacy entries hash but not the package
        digest: the package_integrity_sha256 mismatch must refuse (the
        reviewer_only_assets / counts / exam identity are covered too)."""
        import copy
        from certpassly.media_prep.manifest import entries_hash
        t = copy.deepcopy(self.manifest)
        t["reviewer_only_assets"] = []  # smuggle: empty the reviewer list
        t["integrity"]["entries_sha256"] = entries_hash(t["questions"])
        tpath = os.path.join(self.root, "c17-manifest.json")
        json.dump(t, open(tpath, "w"), indent=1)
        with self.assertRaises(PrivacyViolationError):
            load_manifest(tpath)

    def test_c18_manifest_without_package_integrity_refused(self):
        """A legacy manifest (entries hash only, no package digest) is
        refused when require_package_integrity is on (the default)."""
        import copy
        t = copy.deepcopy(self.manifest)
        del t["integrity"]["package_integrity_sha256"]
        tpath = os.path.join(self.root, "c18-manifest.json")
        json.dump(t, open(tpath, "w"), indent=1)
        with self.assertRaises(PrivacyViolationError):
            load_manifest(tpath)
        m2 = load_manifest(tpath, require_package_integrity=False)
        self.assertEqual(m2["schema_version"], "image-manifest-v1")

    def test_c19_hmac_receipt_enforcement(self):
        """require_receipt=true: a valid HMAC receipt (key from OUTSIDE the
        package) passes; a wrong key and a missing receipt are both refused."""
        import copy
        from certpassly.media_prep.manifest import package_integrity_hash, receipt_hmac
        key = b"test-receipt-key-0123456789"
        m = copy.deepcopy(self.manifest)
        m["integrity"]["receipt_sha256_hmac"] = receipt_hmac(
            key, package_integrity_hash(m))
        m["integrity"]["receipt_key_id"] = "env:CERTPASSLY_MANIFEST_KEY"
        mpath = os.path.join(self.root, "c19-manifest.json")
        json.dump(m, open(mpath, "w"), indent=1)
        path = os.path.join(self.root, "c19.zip")
        _zip(path, self.good_members)

        old = os.environ.get("CERTPASSLY_MANIFEST_KEY")
        try:
            os.environ["CERTPASSLY_MANIFEST_KEY"] = key.decode()
            rep = verify_package(mpath, path, require_receipt=True)
            self.assertTrue(rep["passed"], rep["problems"])
            os.environ["CERTPASSLY_MANIFEST_KEY"] = "wrong-key"
            rep = verify_package(mpath, path, require_receipt=True)
            self.assertFalse(rep["passed"])
            self.assertIn("RECEIPT_HMAC_MISMATCH",
                          {p["reason"] for p in rep["problems"]})
            rep = verify_package(self.manifest_path, path, require_receipt=True)
            self.assertFalse(rep["passed"])
            self.assertIn("RECEIPT_MISSING",
                          {p["reason"] for p in rep["problems"]})
        finally:
            if old is None:
                os.environ.pop("CERTPASSLY_MANIFEST_KEY", None)
            else:
                os.environ["CERTPASSLY_MANIFEST_KEY"] = old

    def test_c20_source_receipt_binding(self):
        """privacy.source_receipt binds the manifest's source PDF identity to
        an independently pinned exam manifest; a mismatch is refused."""
        good = {"pdf_files": [{"name": "x.pdf",
                               "sha256": self.manifest["source_pdf_sha256"],
                               "bytes": self.manifest["source_pdf_bytes"]}]}
        bad = {"pdf_files": [{"name": "y.pdf", "sha256": "f" * 64, "bytes": 1}]}
        gp = os.path.join(self.root, "good-receipt.json")
        bp = os.path.join(self.root, "bad-receipt.json")
        json.dump(good, open(gp, "w"))
        json.dump(bad, open(bp, "w"))
        path = os.path.join(self.root, "c20.zip")
        _zip(path, self.good_members)
        rep = verify_package(self.manifest_path, path, source_receipt=gp)
        self.assertTrue(rep["passed"], rep["problems"])
        rep = verify_package(self.manifest_path, path, source_receipt=bp)
        self.assertFalse(rep["passed"])
        self.assertIn("SOURCE_RECEIPT_MISMATCH",
                      {p["reason"] for p in rep["problems"]})


def png_fresh():
    """A brand-new synthetic PNG (unknown SHA)."""
    import hashlib
    from PIL import ImageDraw
    img = Image.new("RGB", (400, 200), (250, 20, 20))
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 390, 190], outline=(0, 0, 0), width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    unittest.main()
