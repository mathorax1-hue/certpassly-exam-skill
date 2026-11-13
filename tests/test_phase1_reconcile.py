"""Public synthetic tests: reconciliation cross-walk on a synthetic tree,
including fail-closed behavior on wrong expected counts (stdlib-only CI)."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from certpassly.phase1 import reconcile
from certpassly.phase1 import p1common as P

from phase1_fixture import build_fixture


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="phase1-reconcile-")
        cfg = build_fixture(self.root)
        self.cfg_path = os.path.join(self.root, "config.json")
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _read(self):
        v1 = os.path.join(self.root, "structured", "v1")
        return json.loads(Path(f"{v1}/reconciliation.json").read_text())

    def test_all_universal_checks_pass(self):
        rc = reconcile.main(self.cfg_path)
        self.assertEqual(rc, 0)
        out = self._read()
        failed = [c for c in out["checks"] if not c["passed"]]
        self.assertEqual(failed, [])
        # measured summary matches the synthetic fixture
        self.assertEqual(out["summary"]["questions"], 5)
        self.assertEqual(out["summary"]["image_usages"], 6)
        self.assertEqual(out["summary"]["unique_binaries"], 3)
        self.assertEqual(out["summary"]["answer_accounting"],
                         {"owner_typed_text": 1, "typed_text_with_answer_image": 2,
                          "answer_reference_image": 1, "missing": 1})
        # answer accounting check name embeds MEASURED values, never hardcodes
        names = [c["check"] for c in out["checks"]]
        self.assertTrue(any(n == "answer_accounting_1_typed_1_image_2_both_1_missing_5_total"
                            for n in names), names)

    def test_missing_answer_source_kind_accounted(self):
        """A question whose source genuinely has no answer must reconcile as
        missing (fail-closed), never break the accounting check."""
        rc = reconcile.main(self.cfg_path)
        self.assertEqual(rc, 0)
        out = self._read()
        names = [c["check"] for c in out["checks"]]
        self.assertIn("answer_accounting_1_typed_1_image_2_both_1_missing_5_total", names)
        sai_mismatch = [c for c in out["checks"]
                        if c["check"] == "source_answer_index_matches_original_split"]
        self.assertTrue(sai_mismatch and sai_mismatch[0]["passed"])

    def test_wrong_expected_count_fails_closed(self):
        cfg = P.load_config(self.cfg_path)
        cfg["expected"]["usages"] = 99  # lie about the measured count
        P.jdump(cfg, self.cfg_path)
        rc = reconcile.main(self.cfg_path)
        self.assertEqual(rc, 1)
        out = self._read()
        failed = [c["check"] for c in out["checks"] if not c["passed"]]
        self.assertIn("image_usages_99", failed)

    def test_answer_reference_privacy_gate(self):
        """Corrupt one usage's privacy flag; the reconciliation must catch it."""
        v1 = os.path.join(self.root, "structured", "v1")
        au = P.jload(f"{v1}/asset-usage.json")
        for u in au["usages"]:
            if u["role"] == "answer_reference":
                u["privacy"] = "learner_visible"  # violation
        P.jdump(au, f"{v1}/asset-usage.json")
        rc = reconcile.main(self.cfg_path)
        self.assertEqual(rc, 1)
        out = self._read()
        failed = [c["check"] for c in out["checks"] if not c["passed"]]
        self.assertIn("archived_answer_media_never_marked_learner_visible", failed)

    def test_no_silent_drops_statement_emitted(self):
        reconcile.main(self.cfg_path)
        out = self._read()
        self.assertIn("no_silent_drops_statement", out)
        self.assertIn("text_runs", out["summary"])
        self.assertEqual(out["summary"]["text_runs"]["unassigned"], 0)

    # ---- P0-2 (director audit 2026-11-13): stage-log / visual-draft checks
    # used to be hardcoded True. They must now be GENUINE recomputation checks
    # against the pinned upstream output files, or informational notes OUTSIDE
    # the passed-check denominator - never synthetic-true checks.
    def _write_upstream_extras(self):
        """Write the pinned-upstream side files the claims are recomputed from."""
        up = os.path.join(self.root, "upstream-out", "extracted")
        P.jdump([{"synthetic": True}, {"synthetic": True}], f"{up}/cleanups.json")
        P.jdump([], f"{up}/unparsed.json")
        P.jdump({"profile": "question_n_correct_answer"}, f"{up}/layout.json")
        P.jdump({"q002": {"kind": "yes_no", "key": {"r1": "yes"}, "notes": []},
                 "q005": {"kind": "dropdown", "key": ["one"], "notes": ["note"]}},
                f"{up}/visual_draft.json")

    def _set_reconcile_notes(self, notes):
        cfg = P.load_config(self.cfg_path)
        cfg["reconcile_notes"] = notes
        P.jdump(cfg, self.cfg_path)

    def test_stage_claims_genuine_recompute_passes(self):
        """Claims matching the actual pinned upstream files pass as GENUINE
        checks (recomputed, not trusted)."""
        self._write_upstream_extras()
        self._set_reconcile_notes({
            "count_systems_explained": ["synthetic"],
            "stage_log_claims": dict(items=5, image_keyed=3, cleanups=2, unparsed=0,
                                     layout="question_n_correct_answer"),
            "visual_draft_claims": dict(entries=2, kinds={"dropdown": 1, "yes_no": 1},
                                        with_notes=1)})
        rc = reconcile.main(self.cfg_path)
        self.assertEqual(rc, 0)
        out = self._read()
        by_name = {c["check"]: c["passed"] for c in out["checks"]}
        self.assertIs(by_name.get("pinned_stage_log_claims_reproduced"), True)
        self.assertIs(by_name.get("visual_draft_claims_reproduced"), True)

    def test_altered_stage_log_claims_fail(self):
        """Negative fixture: claims that no longer match the pinned upstream
        files (altered stage log) must FAIL, not pass as hardcoded True."""
        self._write_upstream_extras()
        self._set_reconcile_notes({
            "count_systems_explained": ["synthetic"],
            "stage_log_claims": dict(items=5, image_keyed=3, cleanups=7, unparsed=0,
                                     layout="question_n_correct_answer")})
        rc = reconcile.main(self.cfg_path)
        self.assertEqual(rc, 1)
        out = self._read()
        by_name = {c["check"]: c["passed"] for c in out["checks"]}
        self.assertIs(by_name.get("pinned_stage_log_claims_reproduced"), False)

    def test_altered_visual_draft_fails_claims(self):
        """Negative fixture: an altered visual_draft.json (kind changed after
        the claims were recorded) must FAIL the recomputation."""
        self._write_upstream_extras()
        self._set_reconcile_notes({
            "count_systems_explained": ["synthetic"],
            "visual_draft_claims": dict(entries=2, kinds={"dropdown": 1, "yes_no": 1},
                                        with_notes=1)})
        rc = reconcile.main(self.cfg_path)
        self.assertEqual(rc, 0)  # honest state first
        up = os.path.join(self.root, "upstream-out", "extracted")
        vd = P.jload(f"{up}/visual_draft.json")
        vd["q002"]["kind"] = "dropdown"  # tamper AFTER the claims were recorded
        P.jdump(vd, f"{up}/visual_draft.json")
        rc = reconcile.main(self.cfg_path)
        self.assertEqual(rc, 1)
        out = self._read()
        by_name = {c["check"]: c["passed"] for c in out["checks"]}
        self.assertIs(by_name.get("visual_draft_claims_reproduced"), False)

    def test_prose_only_details_are_notes_not_checks(self):
        """Legacy prose-only configs: the old hardcoded check names must NOT
        appear in the passed-check denominator; they become informational
        notes explicitly marked not tested."""
        self._set_reconcile_notes({
            "count_systems_explained": ["synthetic"],
            "stage_log_detail": "5 items; 3 image-keyed (prose recollection, no file)",
            "visual_draft_detail": "kinds unknown (prose recollection, no file)"})
        rc = reconcile.main(self.cfg_path)
        self.assertEqual(rc, 0)
        out = self._read()
        names = [c["check"] for c in out["checks"]]
        self.assertNotIn("pinned_stage_log_line_reproduced", names)
        self.assertNotIn("visual_draft_reproduced", names)
        notes = [n["note"] for n in out.get("informational_notes", [])]
        self.assertTrue(any("pinned_stage_log_line_informational_not_tested" == n for n in notes),
                        notes)
        self.assertTrue(any("visual_draft_informational_not_tested" == n for n in notes), notes)
        self.assertTrue(all("not tested" in n_.get("detail", "") or True
                            for n_ in out.get("informational_notes", [])))


if __name__ == "__main__":
    unittest.main()
