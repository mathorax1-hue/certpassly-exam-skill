"""Public synthetic tests: stage orchestrator logic (dry-run, resume,
start-from validation, stop-at-first-failure, checkpoint writing) and the
fail-closed SOURCE GUARD for --resume / --start-from (director final
correction, 2026-11-13): neither flag may bypass the source PDF SHA-256 /
identity / integrity checks.

The stage execution is faked via monkeypatching run_stage so the orchestration
logic itself is testable on a stdlib-only environment; the fake is
contract-accurate: a passing audit_source "stage" writes the same
source-audit.json record the real stage-0 audit leaves behind (the checkpoint
writer embeds its verdict). The REAL end-to-end pipeline (real stages,
including the guard against tampered/missing PDFs and stale checkpoints) is
exercised by the adversarial suite and the private integration runs.
"""
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from certpassly.phase1 import run_all

from phase1_fixture import build_fixture


def _write_cfg(root):
    cfg = build_fixture(root)
    cfg_path = os.path.join(root, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)
    return cfg_path


class RunAllTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="phase1-runall-")
        self.cfg_path = _write_cfg(self.root)
        self.ckpt = os.path.join(self.root, "run-checkpoint.json")
        self.pdf = os.path.join(self.root, "synthetic.pdf")
        self.pdf_sha = hashlib.sha256(open(self.pdf, "rb").read()).hexdigest()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self, *extra):
        argv = ["--config", self.cfg_path,
                "--upstream-scripts", self.root, "--skip-adversarial", *extra]
        return run_all.run_cli(argv)

    # ---- contract-accurate stage mock -------------------------------------

    def _fake_stages(self, codes=None, ran=None):
        """Fake run_stage that mimics the real stages' observable effects:
        records exit codes, and a PASSING audit_source writes the
        source-audit.json record the real stage-0 audit leaves next to the
        config (the checkpoint writer embeds its verdict for the guard)."""
        codes = iter(codes) if codes is not None else None

        def fake(name, args, log):
            code = next(codes, 0) if codes is not None else 0
            if name == "audit_source" and code == 0:
                with open(os.path.join(self.root, "source-audit.json"),
                          "w", encoding="utf-8") as f:
                    json.dump({"verdict": "AUDIT_COMPLETE",
                               "pdf": {"sha256": self.pdf_sha,
                                       "bytes": os.path.getsize(self.pdf)},
                               "identity_ambiguous": False}, f)
            if ran is not None:
                ran.append(name)
            log.append(dict(stage=name, command=" ".join(args),
                            exit_code=code, tail=""))
            return code
        return fake

    def _pass_run(self, ran=None):
        """One full successful (mocked) run: checkpoint + audit record exist."""
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            return self._run()

    # ---- prior behavior (guarded now) -------------------------------------

    def test_dry_run_executes_nothing_and_exits_zero(self):
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--dry-run")
        rs.assert_not_called()
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(self.ckpt),
                         "dry-run must not write a checkpoint")

    def test_stop_at_first_failure(self):
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages([0, 0, 1])):
            rc = self._run()
        self.assertNotEqual(rc, 0)
        out = json.loads(open(self.ckpt).read())
        ran = [s["stage"] for s in out["stages"] if s.get("exit_code") is not None]
        self.assertEqual(ran, ["audit_source", "build_structured_v1", "build_exports"])
        skipped = [s["stage"] for s in out["stages"] if s.get("exit_code") is None]
        self.assertEqual(skipped, ["make_source_manifest", "validate_structured_v1",
                                   "reconcile", "visual_qa"])
        self.assertEqual(out["overall_exit"], 1)

    def test_audit_is_stage_zero(self):
        """P0-C: the source audit must be planned and run BEFORE any build."""
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages()) as rs:
            self._run()
        first_called = rs.call_args_list[0][0][0]
        self.assertEqual(first_called, "audit_source")
        audit_argv = rs.call_args_list[0][0][1]
        self.assertIn("certpassly.phase1.audit_source", " ".join(audit_argv))
        self.assertIn("--expected-sha256", audit_argv)

    def test_resume_skips_passed_stages(self):
        # first run: audit + build pass, exports fails
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages([0, 0, 1])):
            self._run()
        # second run with --resume: only build_exports onward should run
        ran_again = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran_again)):
            rc = self._run("--resume")
        self.assertEqual(rc, 0)
        self.assertEqual(ran_again, ["build_exports", "make_source_manifest",
                                     "validate_structured_v1", "reconcile",
                                     "visual_qa"])

    def test_resume_all_complete_is_noop(self):
        self._pass_run()
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--resume")
        rs.assert_not_called()
        self.assertEqual(rc, 0)

    def test_start_from_unknown_stage_fails_closed(self):
        rc = self._run("--start-from", "adversarial")  # not planned (no --adversarial-base)
        self.assertEqual(rc, 2)

    def test_resume_ignores_checkpoint_from_other_config(self):
        other = os.path.join(self.root, "other-config.json")
        with open(other, "w") as f:
            json.dump({"paths": {"out_dir": self.root}}, f)
        with open(self.ckpt, "w") as f:
            json.dump({"config": os.path.abspath(other), "overall_exit": 0,
                       "stages": [{"stage": s, "exit_code": 0} for s in run_all.STAGES]}, f)
        ran = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            rc = self._run("--resume")
        self.assertEqual(rc, 0)
        self.assertEqual(ran, run_all.STAGES,
                         "checkpoint from a different config must not skip stages")

    def test_checkpoint_records_engine_label(self):
        self._pass_run()
        out = json.loads(open(self.ckpt).read())
        self.assertEqual(out["engine"], "certpassly.phase1 (public certpassly-exam-skill)")

    # ---- source guard: the checkpoint is a verifiable receipt -------------

    def test_checkpoint_records_source_fingerprint_and_audit(self):
        self._pass_run()
        out = json.loads(open(self.ckpt).read())
        fp = out["source_fingerprint"]
        self.assertEqual(fp["pdf_sha256"], self.pdf_sha)
        self.assertEqual(fp["pdf_bytes"], os.path.getsize(self.pdf))
        self.assertEqual(fp["config_sha256"],
                         hashlib.sha256(open(self.cfg_path, "rb").read()).hexdigest())
        self.assertEqual(out["audit"]["verdict"], "AUDIT_COMPLETE")
        self.assertIs(out["audit"]["identity_ambiguous"], False)
        self.assertEqual(out["audit"]["pdf_sha256"], self.pdf_sha)

    # ---- NEGATIVE: changed / missing source PDF ---------------------------

    def test_resume_refused_when_pdf_changed(self):
        """Tampering with the source PDF after a completed run must make
        --resume refuse (exit 3) BEFORE any stage runs, leaving the checkpoint
        untouched - the old logic skipped the passed audit stage blindly."""
        self._pass_run()
        before = open(self.ckpt, "rb").read()
        with open(self.pdf, "ab") as f:
            f.write(b"tampered-trailer-bytes")
        ran = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            rc = self._run("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        self.assertEqual(ran, [], "no stage may run after a guard refusal")
        self.assertEqual(open(self.ckpt, "rb").read(), before,
                         "a guard refusal must not overwrite the checkpoint")

    def test_resume_refused_when_pdf_missing(self):
        self._pass_run()
        os.unlink(self.pdf)
        ran = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            rc = self._run("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        self.assertEqual(ran, [])

    def test_start_from_refused_when_pdf_changed_or_missing(self):
        self._pass_run()
        with open(self.pdf, "ab") as f:
            f.write(b"tampered-trailer-bytes")
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--start-from", "validate_structured_v1")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()
        # restore, then remove the PDF entirely: same refusal
        with open(self.pdf, "r+b") as f:
            f.truncate(os.path.getsize(self.pdf) - len(b"tampered-trailer-bytes"))
        os.unlink(self.pdf)
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--start-from", "build_structured_v1")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()

    def test_resume_refused_when_config_does_not_pin_the_source(self):
        """A config without source.expected_pdf_sha256 cannot verify integrity
        on resume, so skipping must be refused (fail-closed)."""
        self._pass_run()
        cfg = json.load(open(self.cfg_path))
        del cfg["source"]["expected_pdf_sha256"]
        json.dump(cfg, open(self.cfg_path, "w"), indent=1)
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()

    # ---- NEGATIVE: stale checkpoints ---------------------------------------

    def test_resume_refused_on_stale_checkpoint_pdf_hash(self):
        self._pass_run()
        out = json.loads(open(self.ckpt).read())
        out["source_fingerprint"]["pdf_sha256"] = "f" * 64
        json.dump(out, open(self.ckpt, "w"))
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()

    def test_resume_refused_on_stale_checkpoint_config_edited(self):
        """Editing the config after the run (new expected counts, paths, pins)
        changes config_sha256, so the checkpoint is stale and must not skip."""
        self._pass_run()
        cfg = json.load(open(self.cfg_path))
        cfg["expected"] = {"questions": 999}
        json.dump(cfg, open(self.cfg_path, "w"), indent=1)
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()

    def test_resume_refused_on_stale_checkpoint_upstream_swapped(self):
        """Swapping the pinned upstream scripts tree invalidates the
        checkpoint even though the PDF and config are untouched."""
        self._pass_run()
        with open(os.path.join(self.root, "rogue_extractor.py"), "w") as f:
            f.write("# not the pinned upstream\n")
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()

    def test_resume_refused_on_prefingerprint_checkpoint(self):
        """A same-config checkpoint written by a pre-guard version carries no
        source_fingerprint and must never authorize skipping."""
        self._pass_run()
        out = json.loads(open(self.ckpt).read())
        del out["source_fingerprint"]
        json.dump(out, open(self.ckpt, "w"))
        ran = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            rc = self._run("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        self.assertEqual(ran, [])

    def test_resume_refused_when_audit_summary_invalid(self):
        """A checkpoint whose embedded audit summary does not prove an
        AUDIT_COMPLETE, unambiguous audit of the CURRENT source must refuse."""
        self._pass_run()
        out = json.loads(open(self.ckpt).read())
        out["audit"]["verdict"] = "BLOCKED"
        json.dump(out, open(self.ckpt, "w"))
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()
        # variant: identity ambiguous
        out = json.loads(open(self.ckpt).read())
        out["audit"]["verdict"] = "AUDIT_COMPLETE"
        out["audit"]["identity_ambiguous"] = True
        json.dump(out, open(self.ckpt, "w"))
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()

    def test_resume_refused_when_disk_audit_record_conflicts(self):
        """An on-disk source-audit.json describing a DIFFERENT source PDF is a
        conflict, even when the checkpoint itself is intact."""
        self._pass_run()
        rec = json.load(open(os.path.join(self.root, "source-audit.json")))
        rec["pdf"]["sha256"] = "e" * 64
        json.dump(rec, open(os.path.join(self.root, "source-audit.json"), "w"))
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()

    # ---- --start-from prerequisites ----------------------------------------

    def test_start_from_refused_without_verified_checkpoint(self):
        """--start-from with no prior checkpoint must refuse: it would skip
        the stage-0 audit with nothing proving the source was ever verified."""
        self.assertFalse(os.path.exists(self.ckpt))
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--start-from", "build_exports")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()

    def test_start_from_refused_when_prerequisites_not_passed(self):
        """Starting past stages that did NOT exit 0 in the verified checkpoint
        must refuse; starting AT the first failed stage stays allowed."""
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages([0, 0, 1])):
            self._run()  # audit+build pass, exports fails
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--start-from", "visual_qa")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()
        ran = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            rc = self._run("--start-from", "build_exports")
        self.assertEqual(rc, 0)
        self.assertEqual(ran, ["build_exports", "make_source_manifest",
                               "validate_structured_v1", "reconcile", "visual_qa"])

    def test_start_from_resumes_only_target_stage_when_verified(self):
        """Positive control: over a fully passed, fingerprint-verified
        checkpoint, --start-from runs exactly the requested stage onward."""
        self._pass_run()
        ran = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            rc = self._run("--start-from", "visual_qa")
        self.assertEqual(rc, 0)
        self.assertEqual(ran, ["visual_qa"])

    # ---- guard visibility / dry-run ----------------------------------------

    def test_dry_run_with_resume_reports_guard_refusal(self):
        """Even --dry-run must not PLAN a bypass: the guard verdict is
        evaluated and a refusal exits 3 without side effects."""
        self._pass_run()
        with open(self.pdf, "ab") as f:
            f.write(b"tampered-trailer-bytes")
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--dry-run", "--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
