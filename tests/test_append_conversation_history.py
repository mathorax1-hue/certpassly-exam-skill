"""Synthetic private-master history tests; never include real conversation or owner exams."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "append_conversation_history.py"
spec = importlib.util.spec_from_file_location("append_conversation_history", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def source():
    return {"archive_metadata": {"master_library_path": "/synthetic/private/master.json"},
            "archive_update_history": [{"old": True}],
            "single_file_evidence_archive": {"embedded_zip_base64": "SYNTHETIC-BYTES"},
            "conversation_chronology": [{"event_id": "earlier", "summary": "keep"}]}


def batch():
    return {"batch_source": "synthetic session 001",
            "events": [{"id": "20261112.turn-001", "role": "user",
                        "origin": "visible_chat", "source_reference": "synthetic-visible-turn-001",
                        "verbatim": True, "text": "Please preserve this synthetic history."},
                       {"id": "20261112.turn-002", "role": "assistant",
                        "origin": "manual_summary", "source_reference": "synthetic-summary",
                        "verbatim": False, "text": "Assistant described a hypothetical workflow."}]}


class ConversationAppendTests(unittest.TestCase):
    def test_preserves_existing_embedded_data_and_appends(self):
        master, n = tool.update_master(source(), batch())
        self.assertEqual(n, 2)
        self.assertEqual(master["single_file_evidence_archive"], source()["single_file_evidence_archive"])
        self.assertEqual(master["conversation_chronology"], source()["conversation_chronology"])
        self.assertEqual(len(master["conversation_events_incremental"]), 2)
        self.assertTrue(master["archive_update_history"][-1]["not_a_complete_global_chat_export"])

    def test_idempotent_same_batch_and_reject_changed_existing_event(self):
        first, _ = tool.update_master(source(), batch())
        second, n = tool.update_master(first, batch())
        self.assertEqual(n, 0)
        self.assertEqual(second, first)
        changed = batch()
        changed["events"][0]["text"] = "changed"
        with self.assertRaises(ValueError):
            tool.update_master(first, changed)

    def test_duplicate_event_ids_rejected(self):
        b = batch()
        b["events"][1]["id"] = b["events"][0]["id"]
        with self.assertRaises(ValueError):
            tool.update_master(source(), b)

    def test_no_fake_verbatim_claims(self):
        b = batch()
        b["events"][1]["verbatim"] = True
        with self.assertRaises(ValueError):
            tool.update_master(source(), b)

    def test_no_release_approval_or_secrets(self):
        for alteration in ({"released": True}, {"human_verified": True},
                           {"text": "github_pat_" + "a" * 24}):
            b = batch()
            b["events"][0].update(alteration)
            with self.subTest(alteration=list(alteration)), self.assertRaises(ValueError):
                tool.update_master(source(), b)

    def test_missing_provenance_or_bad_role(self):
        for alteration in ({"source_reference": ""}, {"role": "unknown"}):
            b = batch()
            b["events"][0].update(alteration)
            with self.subTest(alteration=alteration), self.assertRaises(ValueError):
                tool.update_master(source(), b)

    def test_default_is_preview_and_apply_replaces_same_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            master = root / "master.json"
            events = root / "events.json"
            master.write_text(json.dumps(source()))
            events.write_text(json.dumps(batch()))
            args = [sys.executable, str(SCRIPT), "--private-master", str(master),
                    "--event-batch", str(events)]
            original = master.read_bytes()
            preview = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual(json.loads(preview.stdout)["status"], "preview")
            self.assertEqual(master.read_bytes(), original)
            applied = subprocess.run(args + ["--apply"], capture_output=True, text=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(json.loads(applied.stdout)["status"], "updated")
            self.assertEqual(len(json.loads(master.read_text())["conversation_events_incremental"]), 2)
            self.assertEqual(len(list(root.glob("*.json"))), 2)
            twice = subprocess.run(args + ["--apply"], capture_output=True, text=True)
            self.assertEqual(json.loads(twice.stdout)["status"], "unchanged")

    def test_malformed_master_kept_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            master = root / "master.json"
            events = root / "events.json"
            master.write_text('{"archive_metadata": {}}')
            broken = batch()
            broken["events"][0]["origin"] = "invented"
            events.write_text(json.dumps(broken))
            original = master.read_bytes()
            p = subprocess.run([sys.executable, str(SCRIPT), "--private-master", str(master),
                                "--event-batch", str(events), "--apply"],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 2)
            self.assertEqual(master.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
