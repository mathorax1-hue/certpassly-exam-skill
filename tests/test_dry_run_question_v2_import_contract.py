import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

S = Path(__file__).resolve().parents[1] / "scripts" / "dry_run_question_v2_import_contract.py"
spec = importlib.util.spec_from_file_location("dry_run_question_v2_import_contract", S)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def valid():
    return {"schema_version": "question.v2", "question_key": "q001",
            "version": 1, "type": "single_choice",
            "learner": {"stem": {"format": "html", "text": "<p>Sample</p>"},
                        "interaction": {"options": [
                            {"id": "a", "text": "One"},
                            {"id": "b", "text": "Two"}], "choose_n": 1}},
            "answer": {"answer_key": {"correct_option_ids": ["a"]}},
            "meta": {"record_status": "draft"}}

class ImportProjectionTests(unittest.TestCase):
    def test_answer_is_server_only_and_digest_only(self):
        projected = mod.project(valid())
        self.assertEqual(projected["secret_leaks"], [])
        self.assertIn("server_answer_sha256", projected)
        self.assertNotIn("answer", projected)
        self.assertNotIn("public_view", projected)
        self.assertEqual(projected["idempotency_key"], "q001:v1")

    def test_fail_on_answer_key_in_learner(self):
        d = valid()
        d["learner"]["answer_key"] = {"correct": "a"}
        p = mod.project(d)
        self.assertIn("learner.answer_key", p["secret_leaks"])

    def test_dry_run_quarantines_source_flag_and_no_website_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "q001.v1.json").write_text(json.dumps(valid()), encoding="utf-8")
            r = mod.inspect(folder, ["q001"], expected=1)
            self.assertTrue(r["projection_pass"])
            self.assertEqual(r["source_blocked"], 1)
            self.assertEqual(r["non_source_blocked"], 0)
            self.assertFalse(r["website_import_tested"])

if __name__ == "__main__":
    unittest.main()
