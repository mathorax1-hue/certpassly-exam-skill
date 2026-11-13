"""Public synthetic tests: stage orchestrator logic (dry-run, resume,
start-from validation, stop-at-first-failure, checkpoint writing), the
fail-closed SOURCE GUARD for --resume / --start-from (director final
correction 1, 2026-11-13: neither flag may bypass the source PDF SHA-256 /
identity / integrity checks), the fail-closed OUTPUT-INVENTORY GUARD
(director final correction 2, 2026-11-13: neither flag may produce a false
successful no-op over deleted or modified generated outputs - question JSON,
asset binaries, validation/reconciliation/QA reports - or over a silently
changed toolkit; a checkpoint that predates inventories cannot authorize
skipping anything) and the EXACT FILE-SET + RECEIPT-PRESERVATION guard
(director final correction 3, 2026-11-13: an UNEXPECTED EXTRA file in the
monitored output roots - injected question JSON, stray answer asset, rogue
upstream output - must refuse with exit 3 instead of a green no-op, while
legitimate later-stage artifacts are tolerated by path because the resume
regenerates them; and a partial resume must preserve the verified skipped
stages' receipts so the checkpoint keeps the COMPLETE stage list and
repeated partial resumes can chain without losing verification).

The stage execution is faked via monkeypatching run_stage so the orchestration
logic itself is testable on a stdlib-only environment; the fake is
contract-accurate: a passing audit_source "stage" writes the same
source-audit.json record the real stage-0 audit leaves behind (the checkpoint
writer embeds its verdict), and the output-writing variant additionally
writes the real-world-shaped output files each stage produces. The REAL
end-to-end pipeline (real stages, including both guards against
tampered/missing PDFs, stale checkpoints and tampered outputs) is exercised
by the adversarial suite and the private integration runs.
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import certpassly
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


class RunAllOutputInventoryTests(RunAllTests):
    """Director final correction 2: --resume / --start-from may never produce
    a false successful no-op over deleted or modified GENERATED OUTPUTS. The
    stage fake below is contract-accurate about WHAT each stage writes, so
    the checkpoint records real inventories and the guard has real files to
    verify."""

    STAGE_FILES = {
        "build_structured_v1": [
            ("structured/v1/questions/q001.json",
             '{"question_id": "q001", "note": "synthetic stage output"}\n'),
            ("structured/v1/questions/q002.json",
             '{"question_id": "q002", "note": "synthetic stage output"}\n'),
            # the real builder extracts image binaries into assets/: the fake
            # writes one so asset tampering is caught as an OUTPUT violation
            ("structured/v1/assets/synthetic-answer-reference-image.png",
             b"synthetic-extracted-answer-reference-image-bytes"),
        ],
        "build_exports": [
            ("structured/v1/export/site-format-v1-draft/export-blockers.json",
             '{"rows": 5, "note": "synthetic stage output"}\n'),
        ],
        "make_source_manifest": [
            ("structured/v1/source-manifest.json",
             '{"note": "synthetic stage output"}\n'),
        ],
        "validate_structured_v1": [
            ("structured/v1/extraction-report.json",
             '{"checks": "62/62 synthetic", "note": "stage output"}\n'),
        ],
        "reconcile": [
            ("structured/v1/reconciliation.json",
             '{"checks": "26/26 synthetic", "note": "stage output"}\n'),
        ],
        "visual_qa": [
            ("structured/v1/qa/visual-qa-report.json",
             '{"machine_visibility": {"failed": false}, "note": "stage output"}\n'),
        ],
    }

    def _fake_stages(self, codes=None, ran=None, write_outputs=True):
        """Contract-accurate fake: a passing audit_source writes the
        source-audit.json record, and every other passing stage writes its
        real-world-shaped output files under the fixture root."""
        codes = iter(codes) if codes is not None else None

        def fake(name, args, log):
            code = next(codes, 0) if codes is not None else 0
            if code == 0:
                if name == "audit_source":
                    with open(os.path.join(self.root, "source-audit.json"),
                              "w", encoding="utf-8") as f:
                        json.dump({"verdict": "AUDIT_COMPLETE",
                                   "pdf": {"sha256": self.pdf_sha,
                                           "bytes": os.path.getsize(self.pdf)},
                                   "identity_ambiguous": False}, f)
                elif write_outputs:
                    for rel, content in self.STAGE_FILES.get(name, []):
                        p = os.path.join(self.root, rel)
                        os.makedirs(os.path.dirname(p), exist_ok=True)
                        if isinstance(content, bytes):
                            with open(p, "wb") as f:
                                f.write(content)
                        else:
                            with open(p, "w", encoding="utf-8") as f:
                                f.write(content)
            if ran is not None:
                ran.append(name)
            log.append(dict(stage=name, command=" ".join(args),
                            exit_code=code, tail=""))
            return code
        return fake

    def _pass_run(self, ran=None):
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            return self._run()

    def _refuse_capture(self, *extra):
        """Run with stderr captured; return (rc, stderr_text)."""
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = self._run(*extra)
        return rc, buf.getvalue()

    # ---- checkpoint records what each stage actually wrote ----------------

    def test_checkpoint_records_output_inventories_and_baseline(self):
        self._pass_run()
        out = json.loads(open(self.ckpt).read())
        self.assertEqual(out["inventory_version"], 1)
        base = {e["path"]: e["sha256"] for e in out["input_baseline"]}
        # the monitored pipeline inputs are pinned in the baseline
        split = os.path.join(self.root, "upstream-out", "extracted", "split.json")
        self.assertIn(split, base)
        self.assertEqual(base[split],
                         hashlib.sha256(open(split, "rb").read()).hexdigest())
        stages = {s["stage"]: s for s in out["stages"]}
        self.assertIn("outputs", stages["build_structured_v1"])
        wrote = {e["path"] for e in stages["build_structured_v1"]["outputs"]}
        self.assertIn(os.path.join(self.root, "structured/v1/questions/q001.json"), wrote)
        # every recorded sha matches the actual file bytes
        for e in stages["build_structured_v1"]["outputs"]:
            self.assertEqual(
                e["sha256"], hashlib.sha256(open(e["path"], "rb").read()).hexdigest())
        # toolkit fingerprint: content hash of the installed package, not a label
        fp = out["source_fingerprint"]
        self.assertIn("toolkit_tree_sha256", fp)
        self.assertEqual(fp["toolkit_version"], certpassly.__version__)
        self.assertEqual(fp["toolkit_tree_sha256"],
                         run_all.toolkit_fingerprint()["toolkit_tree_sha256"])

    # ---- NEGATIVE: deleted / edited generated outputs ---------------------

    def test_resume_refused_when_question_json_deleted(self):
        """Deleting a generated question record after a completed run must
        make --resume refuse (exit 3) naming the file and its stage - the old
        logic returned a green no-op without opening any output file."""
        self._pass_run()
        before = open(self.ckpt, "rb").read()
        q1 = os.path.join(self.root, "structured/v1/questions/q001.json")
        os.unlink(q1)
        ran = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            rc, err = self._refuse_capture("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        self.assertEqual(ran, [], "no stage may run after an inventory refusal")
        self.assertIn("output_inventory_mismatch", err)
        self.assertIn("q001.json", err)
        self.assertIn("build_structured_v1", err)
        self.assertEqual(open(self.ckpt, "rb").read(), before,
                         "an inventory refusal must not overwrite the checkpoint")

    def test_resume_refused_when_question_json_edited(self):
        self._pass_run()
        q2 = os.path.join(self.root, "structured/v1/questions/q002.json")
        with open(q2, "w", encoding="utf-8") as f:
            f.write('{"question_id": "q002", "tampered": true}\n')
        with mock.patch.object(run_all, "run_stage") as rs:
            rc, err = self._refuse_capture("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()
        self.assertIn("output_inventory_mismatch", err)
        self.assertIn("q002.json", err)

    def test_resume_refused_when_asset_bytes_swapped(self):
        """A swapped answer-reference image binary (same name, different
        bytes) must refuse the resume."""
        self._pass_run()
        victim = "synthetic-answer-reference-image.png"
        p = os.path.join(self.root, "structured/v1/assets", victim)
        with open(p, "wb") as f:
            f.write(b"swapped-image-bytes-not-the-extracted-binary")
        with mock.patch.object(run_all, "run_stage") as rs:
            rc, err = self._refuse_capture("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()
        self.assertIn("output_inventory_mismatch", err)
        self.assertIn(victim, err)
        self.assertIn("build_structured_v1", err)

    def test_resume_refused_when_validation_or_reconciliation_report_deleted(self):
        self._pass_run()
        for rel in ("structured/v1/extraction-report.json",
                    "structured/v1/reconciliation.json"):
            p = os.path.join(self.root, rel)
            self.assertTrue(os.path.exists(p))
            os.unlink(p)
            with mock.patch.object(run_all, "run_stage") as rs:
                rc, err = self._refuse_capture("--resume")
            self.assertEqual(rc, run_all.GUARD_EXIT, rel)
            rs.assert_not_called()
            self.assertIn("output_inventory_mismatch", err)
            self.assertIn(os.path.basename(rel), err)

    def test_start_from_refused_when_skipped_output_modified(self):
        """--start-from must not skip stages whose recorded outputs were
        tampered with, even when the source PDF is intact."""
        self._pass_run()
        blockers = os.path.join(
            self.root, "structured/v1/export/site-format-v1-draft/export-blockers.json")
        with open(blockers, "w", encoding="utf-8") as f:
            f.write('{"rows": 0, "tampered": true}\n')
        with mock.patch.object(run_all, "run_stage") as rs:
            rc, err = self._refuse_capture("--start-from", "validate_structured_v1")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()
        self.assertIn("export-blockers.json", err)
        self.assertIn("build_exports", err)

    def test_start_from_allows_when_only_later_stage_output_modified(self):
        """Precision control: only the SKIPPED stages' outputs gate the
        bypass. Tampering an output of a stage that will re-run anyway (here
        reconcile's report, starting at validate) does not refuse - the
        re-run regenerates it."""
        self._pass_run()
        os.unlink(os.path.join(self.root, "structured/v1/reconciliation.json"))
        ran = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            rc = self._run("--start-from", "validate_structured_v1")
        self.assertEqual(rc, 0)
        self.assertEqual(ran, ["validate_structured_v1", "reconcile", "visual_qa"])
        self.assertTrue(os.path.exists(
            os.path.join(self.root, "structured/v1/reconciliation.json")))

    # ---- NEGATIVE: tampered inputs and silently changed toolkit ------------

    def test_resume_refused_when_input_baseline_modified(self):
        """A modified pipeline INPUT (the pinned upstream split) is an
        integrity violation even though no stage output changed."""
        self._pass_run()
        split = os.path.join(self.root, "upstream-out", "extracted", "split.json")
        with open(split, "w", encoding="utf-8") as f:
            json.dump({"tampered": True}, f)
        with mock.patch.object(run_all, "run_stage") as rs:
            rc, err = self._refuse_capture("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()
        self.assertIn("input_baseline_mismatch", err)

    def test_resume_refused_when_toolkit_code_changed(self):
        """REAL negative: silently changing installed toolkit code while the
        version label stays identical must invalidate the checkpoint (the
        engine component of the fingerprint is a content hash, not a label)."""
        self._pass_run()
        probe = os.path.join(os.path.dirname(os.path.abspath(certpassly.__file__)),
                             "phase1", "p1common.py")
        original = open(probe, "rb").read()
        version_before = certpassly.__version__
        try:
            with open(probe, "ab") as f:  # comment-only change: code still valid
                f.write(b"\n# toolkit-drift probe (synthetic negative test)\n")
            self.assertEqual(certpassly.__version__, version_before,
                             "the version label must stay unchanged for this probe")
            with mock.patch.object(run_all, "run_stage") as rs:
                rc, err = self._refuse_capture("--resume")
            self.assertEqual(rc, run_all.GUARD_EXIT)
            rs.assert_not_called()
            self.assertIn("toolkit_tree_sha256", err)
        finally:
            with open(probe, "wb") as f:
                f.write(original)
        self.assertEqual(open(probe, "rb").read(), original,
                         "the probe must restore the toolkit file byte-exactly")
        # restored toolkit: the same checkpoint resumes cleanly again
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--resume")
        self.assertEqual(rc, 0)
        rs.assert_not_called()

    # ---- NEGATIVE: checkpoints that predate inventories -------------------

    def test_resume_degrades_to_full_run_when_checkpoint_lacks_inventories(self):
        """An old-format checkpoint (no per-stage inventories, no baseline)
        cannot authorize skipping: --resume rebuilds EVERYTHING from stage 0
        with a loud notice - never a green no-op."""
        self._pass_run()
        out = json.loads(open(self.ckpt).read())
        for s in out.get("stages", []):
            s.pop("outputs", None)
        out.pop("input_baseline", None)
        json.dump(out, open(self.ckpt, "w"))
        # --start-from on the same stale receipt: refuse outright
        with mock.patch.object(run_all, "run_stage") as rs:
            rc, err = self._refuse_capture("--start-from", "reconcile")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()
        self.assertIn("predates output-inventory verification", err)
        # --resume: explicit full rebuild, all stages re-run
        ran = []
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with mock.patch.object(run_all, "run_stage",
                                   side_effect=self._fake_stages(ran=ran)):
                rc = self._run("--resume")
        self.assertEqual(rc, 0)
        self.assertEqual(ran, run_all.STAGES,
                         "a checkpoint without inventories must skip nothing")
        self.assertIn("cannot verify this checkpoint's artifacts", buf.getvalue())

    # ---- dry-run visibility -------------------------------------------------

    def test_dry_run_with_resume_reports_output_refusal(self):
        """Even --dry-run must surface an output-inventory refusal."""
        self._pass_run()
        os.unlink(os.path.join(self.root, "structured/v1/questions/q001.json"))
        with mock.patch.object(run_all, "run_stage") as rs:
            rc, err = self._refuse_capture("--dry-run", "--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()
        self.assertIn("output_inventory_mismatch", err)

    # ---- positive control ---------------------------------------------------

    def test_resume_noop_verifies_every_recorded_output(self):
        """Positive control: with every recorded artifact intact, --resume is
        a VERIFIED no-op (and the message says so)."""
        self._pass_run()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with mock.patch.object(run_all, "run_stage") as rs:
                rc = self._run("--resume")
        self.assertEqual(rc, 0)
        rs.assert_not_called()
        self.assertIn("every recorded output verified", buf.getvalue())


class RunAllExactInventoryTests(RunAllOutputInventoryTests):
    """Director final correction 3 (2026-11-13), two closely related
    checkpoint-integrity behaviors:

    P0 - the output inventory is an EXACT FILE-SET receipt: before --resume
    may no-op or any stage may be skipped, every file present in the
    monitored output roots must be attributable to the verified input
    baseline, to a skipped stage's recorded outputs (SHA-verified), to a
    prior-run recorded stage not planned now, or to a planned stage this run
    regenerates anyway (path-tolerated). An injected questions/q999.json, a
    stray answer asset or a rogue file in the pinned upstream output refuses
    with exit 3 - never a green no-op, and no untracked answer image can
    silently feed downstream consumers.

    P1 - partial resumes PRESERVE the verified skipped-stage receipts: the
    new checkpoint carries the COMPLETE ordered stage list (skipped stages
    marked skipped_this_run with their recorded inventories, executed stages
    fresh), each stage exactly once, so repeated partial resumes chain and
    later resumes keep full traceability - with no false green.
    """

    def _fake_stages(self, codes=None, ran=None, write_outputs=True,
                     fail_writes=None):
        """Contract-accurate fake (extends the correction-2 fake): a FAILING
        stage may still have written partial output before exiting non-zero
        (fail_writes) - exactly the real-world mid-run failure shape the
        exact-set guard must refuse to skip over."""
        codes = iter(codes) if codes is not None else None

        def fake(name, args, log):
            code = next(codes, 0) if codes is not None else 0
            if code == 0:
                if name == "audit_source":
                    with open(os.path.join(self.root, "source-audit.json"),
                              "w", encoding="utf-8") as f:
                        json.dump({"verdict": "AUDIT_COMPLETE",
                                   "pdf": {"sha256": self.pdf_sha,
                                           "bytes": os.path.getsize(self.pdf)},
                                   "identity_ambiguous": False}, f)
                elif write_outputs:
                    for rel, content in self.STAGE_FILES.get(name, []):
                        p = os.path.join(self.root, rel)
                        os.makedirs(os.path.dirname(p), exist_ok=True)
                        if isinstance(content, bytes):
                            with open(p, "wb") as f:
                                f.write(content)
                        else:
                            with open(p, "w", encoding="utf-8") as f:
                                f.write(content)
            elif fail_writes and name in fail_writes:
                for rel, content in fail_writes[name]:
                    p = os.path.join(self.root, rel)
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(content)
            if ran is not None:
                ran.append(name)
            log.append(dict(stage=name, command=" ".join(args),
                            exit_code=code, tail=""))
            return code
        return fake

    # ---- NEGATIVE (P0): unexpected EXTRA files refuse the resume ----------

    def test_resume_refused_when_extra_question_json_injected(self):
        """The director's exact repro: after a fully successful run, inject
        structured/v1/questions/q999.json WITHOUT touching any recorded file.
        The old guard only compared recorded paths, so every expected SHA
        still matched and --resume returned a green no-op over an unknown
        file set; the exact file-set inventory must refuse (exit 3)."""
        self._pass_run()
        before = open(self.ckpt, "rb").read()
        q999 = os.path.join(self.root, "structured/v1/questions/q999.json")
        with open(q999, "w", encoding="utf-8") as f:
            json.dump({"question_id": "q999", "injected": True}, f)
        ran = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            rc, err = self._refuse_capture("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        self.assertEqual(ran, [], "no stage may run after an exact-set refusal")
        self.assertIn("unexpected_output_files", err)
        self.assertIn("q999.json", err)
        self.assertEqual(open(self.ckpt, "rb").read(), before,
                         "an exact-set refusal must not overwrite the checkpoint")

    def test_resume_refused_when_extra_answer_asset_injected(self):
        """A stray ANSWER-IMAGE binary placed in assets/ after the verified
        run must refuse the resume: untracked answer bytes can never be
        tolerated in the monitored roots nor silently feed downstream
        consumers (public/site output included)."""
        self._pass_run()
        stray = os.path.join(self.root, "structured/v1/assets",
                             "untracked-answer.jpg")
        with open(stray, "wb") as f:
            f.write(b"untracked-answer-image-bytes-never-extracted")
        with mock.patch.object(run_all, "run_stage") as rs:
            rc, err = self._refuse_capture("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()
        self.assertIn("unexpected_output_files", err)
        self.assertIn("untracked-answer.jpg", err)

    def test_resume_refused_when_extra_file_in_upstream_out(self):
        """An unexpected file in the PINNED UPSTREAM split output is an
        integrity violation of a monitored pipeline input root: refuse."""
        self._pass_run()
        rogue = os.path.join(self.root, "upstream-out", "extracted",
                             "rogue-split.json")
        with open(rogue, "w", encoding="utf-8") as f:
            json.dump({"rogue": True}, f)
        with mock.patch.object(run_all, "run_stage") as rs:
            rc, err = self._refuse_capture("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()
        self.assertIn("unexpected_output_files", err)
        self.assertIn("rogue-split.json", err)

    def test_start_from_refused_when_untracked_extra_injected(self):
        """Partial resumes are gated too: --start-from reconcile with an
        injected untracked question record must refuse, not skip the earlier
        stages over an unknown file set."""
        self._pass_run()
        q999 = os.path.join(self.root, "structured/v1/questions/q999.json")
        with open(q999, "w", encoding="utf-8") as f:
            json.dump({"question_id": "q999", "injected": True}, f)
        with mock.patch.object(run_all, "run_stage") as rs:
            rc, err = self._refuse_capture("--start-from", "reconcile")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()
        self.assertIn("unexpected_output_files", err)
        self.assertIn("q999.json", err)

    def test_resume_refused_after_failed_stage_left_unrecorded_partial_output(self):
        """Documented fail-closed behavior: a stage that failed mid-run after
        writing partial output leaves files that NO verified stage recorded.
        --resume must refuse (exit 3) rather than skip over them - the
        operator re-runs from stage 0 so every artifact is rebuilt and
        re-verified (unrecordable partial output is never trusted)."""
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(
                                   codes=[0, 0, 1],
                                   fail_writes={"build_exports":
                                                self.STAGE_FILES["build_exports"]})):
            rc = self._run()
        self.assertEqual(rc, 1)
        ran = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            rc, err = self._refuse_capture("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        self.assertEqual(ran, [])
        self.assertIn("unexpected_output_files", err)
        self.assertIn("export-blockers.json", err)

    # ---- POSITIVE (P0): legitimate files never refuse ----------------------

    def test_start_from_allows_legitimate_later_stage_outputs(self):
        """Positive control: after a fully verified run, the later stages'
        recorded artifacts may remain on disk across a partial resume - they
        are tolerated by PATH (attributable to stages this run regenerates)
        and rewritten, so a lawful partial resume never false-positives."""
        self._pass_run()
        ran = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            rc = self._run("--start-from", "reconcile")
        self.assertEqual(rc, 0)
        self.assertEqual(ran, ["reconcile", "visual_qa"])
        # the later-stage artifacts were regenerated in place
        for rel in ("structured/v1/reconciliation.json",
                    "structured/v1/qa/visual-qa-report.json"):
            self.assertTrue(os.path.exists(os.path.join(self.root, rel)))

    def test_start_from_allows_when_later_stage_rewrote_baseline_file(self):
        """Precision regression: make_source_manifest legitimately rewrites
        source-manifest.json, which also existed in the input baseline (the
        synthetic fixture pre-creates it). Starting AT that stage must not be
        refused for the stale baseline hash: the file is attributable to a
        stage this run regenerates. (The pre-correction guard falsely refused
        this exact shape as input_baseline_mismatch.)"""
        self._pass_run()
        sm = os.path.join(self.root, "structured/v1/source-manifest.json")
        self.assertEqual(json.load(open(sm)).get("note"),
                         "synthetic stage output",
                         "precondition: the stage (not the fixture) wrote the file")
        ran = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            rc = self._run("--start-from", "make_source_manifest")
        self.assertEqual(rc, 0)
        self.assertEqual(ran, ["make_source_manifest", "validate_structured_v1",
                               "reconcile", "visual_qa"])

    def test_resume_verifies_adversarial_report_from_prior_plan(self):
        """A prior run that also ran the adversarial stage leaves its recorded
        report on disk; a later --resume WITHOUT --adversarial-base must fold
        the non-planned stage's outputs into the verified set (no false
        'unexpected extra' positive) - and a tampered report must refuse."""
        self._pass_run()
        adv = os.path.join(self.root, "structured/v1/qa/adversarial-tests.json")
        os.makedirs(os.path.dirname(adv), exist_ok=True)
        blob = json.dumps({"suite": "synthetic", "passed": 1, "total": 1,
                           "scenario": "adversarial report from a prior plan"},
                          indent=1).encode("utf-8")
        with open(adv, "wb") as f:
            f.write(blob)
        out = json.loads(open(self.ckpt).read())
        out["stages"].append(dict(
            stage="adversarial", command="synthetic adversarial stage",
            exit_code=0, tail="",
            outputs=[dict(path=adv, sha256=hashlib.sha256(blob).hexdigest(),
                          bytes=len(blob))]))
        json.dump(out, open(self.ckpt, "w"))
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--resume")
        self.assertEqual(rc, 0)
        rs.assert_not_called()  # verified no-op despite the extra planned-only-
        # in-the-prior-run artifact on disk
        # tampering that recorded report still refuses
        with open(adv, "w", encoding="utf-8") as f:
            f.write('{"tampered": true}')
        with mock.patch.object(run_all, "run_stage") as rs:
            rc, err = self._refuse_capture("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        self.assertIn("output_inventory_mismatch", err)

    # ---- POSITIVE (P1): receipts preserved, complete stage list ------------

    def test_start_from_preserves_complete_stage_list(self):
        """After a partial resume the checkpoint must carry the COMPLETE
        ordered stage list: skipped stages keep their exit status and output
        inventories (marked skipped_this_run), executed stages are fresh,
        each stage appears exactly once, and every recorded inventory SHA
        still matches the actual bytes on disk."""
        self._pass_run()
        c1 = {s["stage"]: s for s in json.loads(open(self.ckpt).read())["stages"]}
        ran = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran)):
            rc = self._run("--start-from", "reconcile")
        self.assertEqual(rc, 0)
        self.assertEqual(ran, ["reconcile", "visual_qa"])
        c2 = json.loads(open(self.ckpt).read())
        self.assertEqual([s["stage"] for s in c2["stages"]], run_all.STAGES,
                         "the new checkpoint must list every planned stage, in order")
        self.assertEqual(len(c2["stages"]),
                         len({s["stage"] for s in c2["stages"]}),
                         "no stage may be double-counted")
        by = {s["stage"]: s for s in c2["stages"]}
        for name in run_all.STAGES[:5]:  # audit_source .. validate_structured_v1
            self.assertTrue(by[name].get("skipped_this_run"), name)
            self.assertEqual(by[name].get("exit_code"), 0, name)
            self.assertEqual(by[name].get("outputs"), c1[name].get("outputs"),
                             f"{name}: the verified receipt must be preserved")
        for name in ("reconcile", "visual_qa"):
            self.assertNotIn("skipped_this_run", by[name], name)
            self.assertEqual(by[name].get("exit_code"), 0, name)
            self.assertIsInstance(by[name].get("outputs"), list, name)
        for s in c2["stages"]:  # every recorded sha matches the real files
            for e in s.get("outputs") or []:
                self.assertEqual(
                    e["sha256"],
                    hashlib.sha256(open(e["path"], "rb").read()).hexdigest(),
                    e["path"])

    def test_repeated_partial_resume_chains_and_final_noop(self):
        """Repeated partial resumes must CHAIN on the preserved receipts:
        --start-from reconcile, then --start-from visual_qa (authorized only
        because the first partial resume kept the earlier stages' receipts -
        the pre-correction checkpoint dropped them and refused here), then a
        final --resume as a verified green no-op over the complete list."""
        self._pass_run()
        ran1 = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran1)):
            rc = self._run("--start-from", "reconcile")
        self.assertEqual(rc, 0)
        self.assertEqual(ran1, ["reconcile", "visual_qa"])
        ran2 = []
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages(ran=ran2)):
            rc = self._run("--start-from", "visual_qa")
        self.assertEqual(rc, 0)
        self.assertEqual(ran2, ["visual_qa"])
        with mock.patch.object(run_all, "run_stage") as rs:
            rc = self._run("--resume")
        self.assertEqual(rc, 0)
        rs.assert_not_called()  # verified no-op over the complete checkpoint
        c3 = json.loads(open(self.ckpt).read())
        self.assertEqual([s["stage"] for s in c3["stages"]], run_all.STAGES)
        self.assertEqual(c3["overall_exit"], 0)

    def test_partial_resume_checkpoint_still_gates_tampering(self):
        """No false green from the merged checkpoint: after a partial resume,
        tampering with a PRESERVED (carried) stage's output must still refuse
        the next --resume - receipt preservation never weakens verification."""
        self._pass_run()
        with mock.patch.object(run_all, "run_stage",
                               side_effect=self._fake_stages()):
            self._run("--start-from", "reconcile")
        q1 = os.path.join(self.root, "structured/v1/questions/q001.json")
        with open(q1, "w", encoding="utf-8") as f:
            f.write('{"question_id": "q001", "tampered": true}\n')
        with mock.patch.object(run_all, "run_stage") as rs:
            rc, err = self._refuse_capture("--resume")
        self.assertEqual(rc, run_all.GUARD_EXIT)
        rs.assert_not_called()
        self.assertIn("output_inventory_mismatch", err)
        self.assertIn("q001.json", err)
        self.assertIn("build_structured_v1", err)


if __name__ == "__main__":
    unittest.main()
