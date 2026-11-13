"""Public synthetic tests: deterministic export adapters and fail-closed answer
privacy (stdlib-only; run on public CI). Uses a 100% synthetic fixture."""
import filecmp
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from certpassly.phase1 import build_exports
from certpassly.phase1 import p1common as P

from phase1_fixture import build_fixture


def _run_and_snapshot(cfg_path, root):
    rc = build_exports.main(cfg_path)
    snap = {}
    for sub in ("upstream-extract-compatible", "site-format-v1-draft"):
        d = Path(cfg_path).parent / "structured" / "v1" / "export" / sub
        for f in sorted(d.rglob("*.json")):
            snap[str(f.relative_to(root))] = f.read_bytes()
    return rc, snap


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="phase1-export-")
        cfg = build_fixture(self.root)
        self.cfg_path = os.path.join(self.root, "config.json")
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_roundtrip_identical_and_outputs_exist(self):
        rc, snap = _run_and_snapshot(self.cfg_path, self.root)
        self.assertEqual(rc, 0)
        v1 = os.path.join(self.root, "structured", "v1")
        self.assertTrue(os.path.isfile(f"{v1}/export/upstream-extract-compatible/split.original.json"))
        self.assertTrue(os.path.isfile(f"{v1}/export/upstream-extract-compatible/roundtrip-check.json"))
        self.assertTrue(os.path.isfile(f"{v1}/export/upstream-extract-compatible/field-mapping.json"))
        self.assertTrue(os.path.isfile(f"{v1}/export/site-format-v1-draft/question-type-draft.json"))
        self.assertTrue(os.path.isfile(f"{v1}/export/site-format-v1-draft/export-blockers.json"))
        rt = json.loads(Path(f"{v1}/export/upstream-extract-compatible/roundtrip-check.json").read_text())
        self.assertEqual(rt["result"], "IDENTICAL")
        self.assertEqual(rt["field_mismatches"], 0)
        self.assertEqual(rt["questions_compared"], 3)

    def test_double_run_determinism(self):
        rc1, snap1 = _run_and_snapshot(self.cfg_path, self.root)
        rc2, snap2 = _run_and_snapshot(self.cfg_path, self.root)
        self.assertEqual((rc1, rc2), (0, 0))
        self.assertEqual(snap1, snap2, "second run must be byte-identical (determinism)")

    def test_answer_privacy_fail_closed(self):
        """Site-format draft must contain no stems, options, answers or media;
        image/combined answers must produce explicit blockers."""
        _run_and_snapshot(self.cfg_path, self.root)
        v1 = os.path.join(self.root, "structured", "v1")
        site = json.loads(Path(f"{v1}/export/site-format-v1-draft/question-type-draft.json").read_text())
        blob = json.dumps(site)
        for forbidden in ("Synthetic stem", "synthetic option", "p-002_002.png", "answer_raw"):
            self.assertNotIn(forbidden, blob,
                             f"learner-facing draft leaked: {forbidden}")
        for q in site["question_types"].values():
            self.assertNotIn("stem", q)
            self.assertNotIn("options", q)
            self.assertNotIn("answer", q)
        blockers = json.loads(Path(f"{v1}/export/site-format-v1-draft/export-blockers.json").read_text())
        self.assertEqual(blockers["blocked_questions"], 3)
        by_q = {b["question"]: b["cannot_export_without_review"] for b in blockers["items"]}
        # q002: image-only answer -> answer gate; q003: typed+image -> answer gate;
        # q002 also in_question_image -> options gate
        self.assertTrue(any("cannot_export_answer_without_review" in r for r in by_q["q002"]))
        self.assertTrue(any("cannot_export_options" in r for r in by_q["q002"]))
        self.assertTrue(any("cannot_export_answer_without_review" in r for r in by_q["q003"]))

    def test_split_original_is_exact_copy(self):
        _run_and_snapshot(self.cfg_path, self.root)
        up = os.path.join(self.root, "upstream-out", "extracted", "split.json")
        copy = os.path.join(self.root, "structured", "v1", "export",
                            "upstream-extract-compatible", "split.original.json")
        self.assertTrue(filecmp.cmp(up, copy, shallow=False))

    def test_regeneration_command_provenance_chain(self):
        _run_and_snapshot(self.cfg_path, self.root)
        v1 = os.path.join(self.root, "structured", "v1")
        fm = json.loads(Path(f"{v1}/export/upstream-extract-compatible/field-mapping.json").read_text())
        # no provenance override and no export_notes override -> legacy default
        self.assertEqual(fm["regeneration_command"],
                         "python3 tools/phase1-extraction/build_exports.py <config.json> "
                         "(tools/phase1-extraction/)")
        # now override via provenance block
        cfg = P.load_config(self.cfg_path)
        cfg["provenance"] = {
            "exports_regeneration_command":
                "python -m certpassly.phase1.build_exports <config.json> (public skill @ deadbee)"}
        P.jdump(cfg, self.cfg_path)
        _run_and_snapshot(self.cfg_path, self.root)
        fm = json.loads(Path(f"{v1}/export/upstream-extract-compatible/field-mapping.json").read_text())
        self.assertIn("public skill @ deadbee", fm["regeneration_command"])


if __name__ == "__main__":
    unittest.main()
