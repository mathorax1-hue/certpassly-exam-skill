"""B6 end-to-end synthetic private replay: SHA/count/gallery and refusals."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from media_prep_fixture import HAS_IMAGE_DEPS,build_full_workspace

if HAS_IMAGE_DEPS:
    from certpassly.media_prep import cli as mp_cli
    from certpassly.media_prep.config import load_config
    from certpassly.media_prep.replay_audit import (
        run_private_media_replay,_private_target,_safe_clean_file)
    from certpassly.media_prep.errors import OperationalError


@unittest.skipUnless(HAS_IMAGE_DEPS,"requires optional PDF/visual dependencies")
class PrivateMediaReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.mkdtemp(prefix="builder-replay-synthetic-")
        cls.facts=build_full_workspace(os.path.join(cls.tmp,"ws"))
        rc=mp_cli.main(["prepare","--config",cls.facts["config"]])
        assert rc==2, f"synthetic fixture must contain 9 expected blocked cases, got {rc}"
        cls.cfg=load_config(cls.facts["config"])
        cls.manifest=json.loads(Path(cls.cfg["output"]["manifest"]).read_text(encoding="utf-8"))
        cls.inv=json.loads(Path(cls.cfg["output"]["inventory"]).read_text(encoding="utf-8"))
        cls.expected_assets=len(cls.inv["files"])
        cls.image_ids={qid for qid,rec in cls.inv["questions"].items() if rec["usage"]}
        cls.image_ids|={q["question_id"] for q in cls.manifest["questions"]
                        if q["requires_image"]}
        cls.expected_q=len(cls.image_ids)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp,ignore_errors=True)

    def _run(self,**kwargs):
        return run_private_media_replay(
            self.facts["config"],expected_source_assets=self.expected_assets,
            expected_image_questions=self.expected_q,**kwargs)

    def test_private_galleries_and_not_approved_report(self):
        report=self._run()
        self.assertEqual(report["schema_version"],"private-media-replay-v1")
        self.assertEqual(report["gallery_count"],len(self.image_ids))
        self.assertEqual(report["observed_source_assets"],self.expected_assets)
        self.assertEqual(report["observed_image_questions"],self.expected_q)
        self.assertEqual(report["site_ui_status"],"UNTESTED")
        self.assertFalse(report["ready_exams_promotion_allowed"])
        self.assertFalse(report["publication_allowed"])
        self.assertEqual(report["independent_verifier_status"],"PENDING_ZAI_REVIEW")
        self.assertEqual(report["human_approval_status"],"NOT_APPROVED")
        self.assertEqual(report["status"],"BLOCKED")
        folder=Path(self.cfg["output"]["private_dir"])/"builder-replay"
        self.assertTrue((folder/"private-replay-report.json").is_file())
        self.assertEqual(len(list(folder.glob("q*.png"))),len(self.image_ids))
        # No original PDF was modified, and reviewer gallery stays PRIVATE.
        self.assertNotIn(str(folder),str(self.cfg["output"]["clean_dir"]))

    def test_independent_wrong_expected_asset_count_blocks(self):
        report=run_private_media_replay(self.facts["config"],
                         expected_source_assets=self.expected_assets+1,
                         expected_image_questions=self.expected_q,
                         gallery_folder="mismatch")
        self.assertEqual(report["status"],"BLOCKED")
        self.assertIn("SOURCE_ASSET_COUNT_MISMATCH",
                      {e["reason"] for e in report["issues"]})

    def test_missing_original_sha_identity_refuses_before_gallery(self):
        pdf=Path(self.cfg["source"]["pdf"])
        old=pdf.read_bytes()
        try:
            pdf.write_bytes(old+b"TAMPER")
            with self.assertRaises(OperationalError):
                self._run(gallery_folder="must-not-write")
        finally:
            pdf.write_bytes(old)
        self.assertFalse((Path(self.cfg["output"]["private_dir"])/"must-not-write").exists())

    def test_reject_escape_from_private_gallery_root(self):
        with self.assertRaises(OperationalError):
            _private_target(self.cfg,"../public")
        with self.assertRaises(OperationalError):
            _private_target(self.cfg,"../../upstream")

    def test_reject_unsafe_clean_filename_before_read(self):
        root=Path(self.cfg["output"]["clean_dir"])
        for name in ("../leak.png","/tmp/secret.png","C:\\x.png","https://a/b.png"):
            with self.subTest(name=name),self.assertRaises(OperationalError):
                _safe_clean_file(root,name)


if __name__=="__main__":
    unittest.main()
