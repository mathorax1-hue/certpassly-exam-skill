"""Public synthetic tests: stage orchestrator logic (dry-run, resume,
start-from validation, stop-at-first-failure, checkpoint writing).

The stage execution is faked via monkeypatching run_stage so the orchestration
logic itself is testable on a stdlib-only environment; the REAL end-to-end
pipeline (real stages) is exercised by the adversarial suite and the private
integration runs.
"""
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

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self, *extra):
        argv = ["--config", self.cfg_path,
                "--upstream-scripts", self.root, "--skip-adversarial", *extra]
        return run_all.run_cli(argv)

    def test_dry_run_executes_nothing_and_exits_zero(self):
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--dry-run")
        rs.assert_not_called()
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(self.ckpt),
                         "dry-run must not write a checkpoint")

    def test_stop_at_first_failure(self):
        codes = iter([0, 0, 1])  # audit passes, build passes, exports fails

        def fake_stage(name, args, log):
            code = next(codes, 0)
            log.append(dict(stage=name, command=" ".join(args), exit_code=code, tail=""))
            return code

        with mock.patch.object(run_all, "run_stage", side_effect=fake_stage):
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
        with mock.patch.object(run_all, "run_stage") as rs:
            rs.side_effect = lambda name, args, log: (
                log.append(dict(stage=name, command=" ".join(args), exit_code=0, tail="")) or 0)
            self._run()
        first_called = rs.call_args_list[0][0][0]
        self.assertEqual(first_called, "audit_source")
        audit_argv = rs.call_args_list[0][0][1]
        self.assertIn("certpassly.phase1.audit_source", " ".join(audit_argv))
        self.assertIn("--expected-sha256", audit_argv)

    def test_resume_skips_passed_stages(self):
        # first run: audit + build pass, exports fails
        codes = iter([0, 0, 1])

        def fake_stage(name, args, log):
            code = next(codes, 0)
            log.append(dict(stage=name, command=" ".join(args), exit_code=code, tail=""))
            return code

        with mock.patch.object(run_all, "run_stage", side_effect=fake_stage):
            self._run()
        # second run with --resume: only build_exports onward should run
        ran_again = []

        def fake_stage2(name, args, log):
            ran_again.append(name)
            log.append(dict(stage=name, command=" ".join(args), exit_code=0, tail=""))
            return 0

        with mock.patch.object(run_all, "run_stage", side_effect=fake_stage2):
            rc = self._run("--resume")
        self.assertEqual(rc, 0)
        self.assertEqual(ran_again, ["build_exports", "make_source_manifest",
                                     "validate_structured_v1", "reconcile", "visual_qa"])

    def test_resume_all_complete_is_noop(self):
        def fake_stage(name, args, log):
            log.append(dict(stage=name, command=" ".join(args), exit_code=0, tail=""))
            return 0

        with mock.patch.object(run_all, "run_stage", side_effect=fake_stage):
            self._run()
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

        def fake_stage(name, args, log):
            ran.append(name)
            log.append(dict(stage=name, command=" ".join(args), exit_code=0, tail=""))
            return 0

        with mock.patch.object(run_all, "run_stage", side_effect=fake_stage):
            rc = self._run("--resume")
        self.assertEqual(rc, 0)
        self.assertEqual(ran, run_all.STAGES,
                         "checkpoint from a different config must not skip stages")

    def test_checkpoint_records_engine_label(self):
        def fake_stage(name, args, log):
            log.append(dict(stage=name, command=" ".join(args), exit_code=0, tail=""))
            return 0

        with mock.patch.object(run_all, "run_stage", side_effect=fake_stage):
            self._run()
        out = json.loads(open(self.ckpt).read())
        self.assertEqual(out["engine"], "certpassly.phase1 (public certpassly-exam-skill)")


if __name__ == "__main__":
    unittest.main()
