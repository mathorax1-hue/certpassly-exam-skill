#!/usr/bin/env python3
"""Fingerprint and update-diff tests. Fixtures are synthetic and labelled TEST-UPDATE-B."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import question_fingerprint as Q

# Synthetic stems only. Never owner or production exam text.
STEM_A = "TEST-UPDATE-B fixture stem alpha one"
STEM_B = "TEST-UPDATE-B fixture stem bravo two"
STEM_C = "TEST-UPDATE-B fixture stem charlie three"
STEM_D = "TEST-UPDATE-B fixture stem delta four"
CHOICE_1 = "TEST-UPDATE-B choice one label"
CHOICE_2 = "TEST-UPDATE-B choice two label"
CHOICE_3 = "TEST-UPDATE-B choice three label"
CHOICE_2B = "TEST-UPDATE-B choice two revised"


def site_question(key, stem, choices, answer_key, qtype="single_choice"):
    return {
        "question_key": key,
        "type": qtype,
        "learner": {
            "stem": [{"type": "paragraph", "content": [{"text": stem}]}],
            "choices": [[{"type": "paragraph", "content": [{"text": c}]}] for c in choices],
        },
        "answer": {"answer_key": answer_key},
    }


def write_site(path: Path, questions: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"questions": questions}, indent=2) + "\n", encoding="utf-8")


class FingerprintTests(unittest.TestCase):
    def test_normalize_collapses_case_and_space(self):
        self.assertEqual(Q.normalize_text("  Foo\nBAR  "), "foo bar")

    def test_same_payload_same_hash(self):
        p1 = Q.fingerprint_payload(STEM_A, [CHOICE_1, CHOICE_2], ["0"], "single_choice")
        p2 = Q.fingerprint_payload("  " + STEM_A.upper() + "  ", [CHOICE_1, CHOICE_2], ["0"], "single_choice")
        self.assertEqual(Q.fingerprints_from_payload(p1)[0], Q.fingerprints_from_payload(p2)[0])

    def test_choice_or_answer_change_changes_full_not_stem(self):
        a = Q.fingerprint_payload(STEM_A, [CHOICE_1, CHOICE_2], ["0"], "single_choice")
        b = Q.fingerprint_payload(STEM_A, [CHOICE_1, CHOICE_2B], ["1"], "single_choice")
        fa, sa = Q.fingerprints_from_payload(a)
        fb, sb = Q.fingerprints_from_payload(b)
        self.assertEqual(sa, sb)
        self.assertNotEqual(fa, fb)

    def test_choice_reorder_is_changed(self):
        a = Q.fingerprint_payload(STEM_A, [CHOICE_1, CHOICE_2], ["0"], "single_choice")
        b = Q.fingerprint_payload(STEM_A, [CHOICE_2, CHOICE_1], ["1"], "single_choice")
        self.assertNotEqual(Q.fingerprints_from_payload(a)[0], Q.fingerprints_from_payload(b)[0])


class DiffTests(unittest.TestCase):
    def setUp(self):
        qa = Q.item_from_site_question(site_question("q001", STEM_A, [CHOICE_1, CHOICE_2], [0]))
        qb = Q.item_from_site_question(site_question("q002", STEM_B, [CHOICE_1, CHOICE_2], [1]))
        qc = Q.item_from_site_question(site_question("q003", STEM_C, [CHOICE_1, CHOICE_2], [0]))
        self.prev = [qa, qb, qc]

    def test_changed_new_retired_and_same(self):
        # Keep A same, change B (same stem, revised choice), drop C (retire), add D (new).
        incoming = [
            Q.item_from_site_question(site_question("q001", STEM_A, [CHOICE_1, CHOICE_2], [0])),
            Q.item_from_site_question(site_question("q002", STEM_B, [CHOICE_1, CHOICE_2B], [1])),
            Q.item_from_site_question(site_question("q003", STEM_D, [CHOICE_1, CHOICE_3], [0])),
        ]
        result = Q.diff_items(self.prev, incoming)
        by_id = {r["question_id"]: r for r in result["items"]}
        self.assertEqual(result["counts"]["same"], 1)
        self.assertEqual(result["counts"]["changed"], 1)
        self.assertEqual(result["counts"]["new"], 1)
        self.assertEqual(result["counts"]["retired"], 1)
        self.assertEqual(by_id["q001"]["status"], "same")
        self.assertEqual(by_id["q002"]["status"], "changed")
        self.assertEqual(by_id["q003"]["status"], "retired")
        new_rows = [r for r in result["items"] if r["status"] == "new"]
        self.assertEqual(len(new_rows), 1)
        self.assertEqual(new_rows[0]["question_id"], "q004")
        self.assertNotEqual(new_rows[0]["question_id"], "q003")

    def test_does_not_reuse_retired_id(self):
        retired = dict(self.prev[2])
        retired["status"] = "retired"
        previous = [self.prev[0], self.prev[1], retired]
        incoming = [
            Q.item_from_site_question(site_question("q010", STEM_D, [CHOICE_1, CHOICE_3], [0])),
            Q.item_from_site_question(site_question("q011", STEM_A, [CHOICE_1, CHOICE_2], [0])),
        ]
        result = Q.diff_items(previous, incoming)
        new_rows = [r for r in result["items"] if r["status"] == "new"]
        self.assertEqual(new_rows[0]["question_id"], "q010")
        self.assertTrue(any(r["question_id"] == "q003" and r["status"] == "retired" for r in result["items"]))
        self.assertNotEqual(new_rows[0]["question_id"], "q003")

    def test_duplicate_fingerprint_kept_once(self):
        item = Q.item_from_site_question(site_question("q001", STEM_A, [CHOICE_1, CHOICE_2], [0]))
        dup = Q.item_from_site_question(site_question("q099", STEM_A, [CHOICE_1, CHOICE_2], [0]))
        result = Q.diff_items([], [item, dup])
        self.assertEqual(result["counts"]["new"], 1)
        self.assertEqual(result["counts"]["duplicate"], 1)
        self.assertEqual(len([r for r in result["items"] if r["status"] == "new"]), 1)

    def test_changed_keeps_old_id(self):
        incoming = [Q.item_from_site_question(site_question("tmp7", STEM_A, [CHOICE_1, CHOICE_2B], [1]))]
        result = Q.diff_items([self.prev[0]], incoming)
        self.assertEqual(result["items"][0]["question_id"], "q001")
        self.assertEqual(result["items"][0]["incoming_id"], "tmp7")
        self.assertEqual(result["items"][0]["status"], "changed")


class ProcessRunTests(unittest.TestCase):
    def test_process_run_writes_leak_safe_report_and_index(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        run_dir = root / "run"
        raw = root / "TEST-UPDATE-B"
        raw.mkdir()
        # Prior index: A, B, C
        prev_items = [
            Q.item_from_site_question(site_question("q001", STEM_A, [CHOICE_1, CHOICE_2], [0])),
            Q.item_from_site_question(site_question("q002", STEM_B, [CHOICE_1, CHOICE_2], [1])),
            Q.item_from_site_question(site_question("q003", STEM_C, [CHOICE_1, CHOICE_2], [0])),
        ]
        Q.write_index(raw / "questions-index.json", "TEST-UPDATE-B", {"items": [
            {**it, "status": "same"} for it in prev_items
        ]})
        # Modified copy of the site file: A same, B changed, C dropped, D new, plus a duplicate of A.
        write_site(run_dir / "TEST-UPDATE-B.site-format.v2.json", [
            site_question("q001", STEM_A, [CHOICE_1, CHOICE_2], [0]),
            site_question("q002", STEM_B, [CHOICE_1, CHOICE_2B], [1]),
            site_question("q003", STEM_D, [CHOICE_1, CHOICE_3], [0]),
            site_question("q004", STEM_A, [CHOICE_1, CHOICE_2], [0]),
        ])
        result = Q.process_run("TEST-UPDATE-B", run_dir, raw, run_dir / "phase-reports")
        self.assertEqual(result["counts"]["same"], 1)
        self.assertEqual(result["counts"]["changed"], 1)
        self.assertEqual(result["counts"]["new"], 1)
        self.assertEqual(result["counts"]["retired"], 1)
        self.assertEqual(result["counts"]["duplicate"], 1)
        report = json.loads((run_dir / "phase-reports" / "change-report.json").read_text(encoding="utf-8"))
        md = (run_dir / "phase-reports" / "change-report.md").read_text(encoding="utf-8")
        blob = json.dumps(report) + md
        for text in (STEM_A, STEM_B, STEM_C, STEM_D, CHOICE_1, CHOICE_2, CHOICE_2B, CHOICE_3):
            self.assertNotIn(text, blob)
        statuses = {row["question_id"]: row["status"] for row in report["items"]}
        self.assertEqual(statuses["q001"], "same")
        self.assertEqual(statuses["q002"], "changed")
        self.assertEqual(statuses["q003"], "retired")
        self.assertEqual(statuses["q004"], "new")



class IdentityStabilityTests(unittest.TestCase):
    def test_letter_answer_matches_zero_based_index(self):
        letter = Q.fingerprint_payload(STEM_A, [CHOICE_1, CHOICE_2], Q.normalize_answer("A"))
        index = Q.fingerprint_payload(STEM_A, [CHOICE_1, CHOICE_2], Q.normalize_answer([0]))
        self.assertEqual(Q.fingerprints_from_payload(letter)[0], Q.fingerprints_from_payload(index)[0])
        self.assertEqual(Q.canonical_answer_token("D"), "3")
        self.assertEqual(Q.canonical_answer_token("d"), "3")

    def test_empty_index_keeps_incoming_ids_including_held_gap(self):
        # Site keys skip q002 (held). If the held extracted item is loaded last,
        # its incoming ID must stay q002, not be appended as q003.
        incoming = [
            Q.item_from_site_question(site_question("q001", STEM_A, [CHOICE_1, CHOICE_2], [0])),
            Q.item_from_site_question(site_question("q003", STEM_C, [CHOICE_1, CHOICE_2], [0])),
        ]
        held = Q.item_from_site_question(site_question("q002", STEM_B, [CHOICE_1, CHOICE_2], [1]))
        held["export_status"] = "held"
        incoming[0]["export_status"] = "exported"
        incoming[1]["export_status"] = "exported"
        incoming.append(held)
        result = Q.diff_items([], incoming)
        by_in = {r["incoming_id"]: r for r in result["items"]}
        self.assertEqual(by_in["q001"]["question_id"], "q001")
        self.assertEqual(by_in["q002"]["question_id"], "q002")
        self.assertEqual(by_in["q003"]["question_id"], "q003")
        self.assertEqual(by_in["q002"]["export_status"], "held")
        self.assertEqual(result["counts"]["new"], 3)
        self.assertEqual(result["counts"]["retired"], 0)

    def test_held_to_exported_same_content_is_same(self):
        prev = Q.item_from_site_question(site_question("q048", STEM_A, [CHOICE_1, CHOICE_2], ["A"]))
        prev["export_status"] = "held"
        incoming = Q.item_from_site_question(site_question("q048", STEM_A, [CHOICE_1, CHOICE_2], [0]))
        incoming["export_status"] = "exported"
        result = Q.diff_items([prev], [incoming])
        self.assertEqual(result["counts"]["same"], 1)
        self.assertEqual(result["counts"]["changed"], 0)
        self.assertEqual(result["counts"]["new"], 0)
        self.assertEqual(result["counts"]["retired"], 0)
        self.assertEqual(result["counts"]["export_status_changed"], 1)
        row = result["items"][0]
        self.assertEqual(row["question_id"], "q048")
        self.assertEqual(row["status"], "same")
        self.assertEqual(row["export_status"], "exported")
        self.assertEqual(row["previous_export_status"], "held")

    def test_extracted_loader_ignores_site_stem_and_remapped_key(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        run = Path(tmp.name)
        # Extracted PDF content for q048. The JSON key was wrongly remapped to q080.
        extracted = run / "extracted" / "items"
        extracted.mkdir(parents=True)
        (extracted / "q048.json").write_text(json.dumps({
            "question_key": "q080",
            "stem": STEM_A,
            "options": {"a": CHOICE_1, "b": CHOICE_2},
            "answer_raw": "A",
        }), encoding="utf-8")
        # Site export has a type-builder stem and numeric answer for a different wrapping.
        site = {
            "questions": [
                site_question("q048", "TEST-UPDATE-B scenario wrapper only", [CHOICE_1, CHOICE_2], [0], "scenario_standalone"),
            ]
        }
        (run / "TEST-UPDATE-B.site-format.v2.json").write_text(json.dumps(site), encoding="utf-8")
        (run / "export").mkdir(parents=True)
        (run / "export" / "cannot-convert.json").write_text("[]", encoding="utf-8")
        items = Q.load_items_from_run(run, "TEST-UPDATE-B")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["question_id"], "q048")
        self.assertEqual(items[0]["export_status"], "exported")
        # Identity comes from the extracted stem, not the site wrapper.
        extracted_item = Q.item_from_extracted({
            "question_key": "q048",
            "stem": STEM_A,
            "options": {"a": CHOICE_1, "b": CHOICE_2},
            "answer_raw": "A",
        })
        self.assertEqual(items[0]["fingerprint"], extracted_item["fingerprint"])
        self.assertNotEqual(items[0]["stem_fingerprint"], Q.item_from_site_question(site["questions"][0])["stem_fingerprint"])


    def test_export_status_prefers_file_stem_over_remapped_held_key(self):
        # After a bad remap, file q048.json may contain question_key q080 while
        # cannot-convert lists q080. The file stem is the identity.
        held = {"q080"}
        site = {"q001", "q048"}
        self.assertEqual(Q.export_status_for("q048", "q080", held, site), "exported")
        self.assertEqual(Q.export_status_for("q080", "q079", held, site), "held")
        self.assertEqual(Q.export_status_for("q263", "q262", set(), {"q262", "q264"}), "exported")

    def test_site_type_change_does_not_retire_when_extracted_matches(self):
        prev = Q.item_from_extracted({
            "question_key": "q264",
            "stem": STEM_D,
            "options": {"a": CHOICE_1, "b": CHOICE_2, "c": CHOICE_3, "d": CHOICE_2B},
            "answer_raw": "A",
        })
        prev["export_status"] = "exported"
        incoming = Q.item_from_extracted({
            "question_key": "q264",
            "stem": STEM_D,
            "options": {"a": CHOICE_1, "b": CHOICE_2, "c": CHOICE_3, "d": CHOICE_2B},
            "answer_raw": "A",
            "type": "scenario_standalone",
        })
        incoming["export_status"] = "exported"
        result = Q.diff_items([prev], [incoming])
        self.assertEqual(result["counts"]["same"], 1)
        self.assertEqual(result["counts"]["new"], 0)
        self.assertEqual(result["counts"]["retired"], 0)
        self.assertEqual(result["items"][0]["question_id"], "q264")



if __name__ == "__main__":
    unittest.main()
