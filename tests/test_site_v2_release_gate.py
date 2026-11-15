"""Synthetic, answer-free regression tests for the independent V2 gate."""
import json
import tempfile
import unittest
from pathlib import Path
from scripts.verify_site_v2_release_gate import verify, HTML

class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d=Path(self.tmp.name)
        self.exam={"exam":{"exam_code":"SYN-001"},"questions":[{
            "question_key":"synthetic-q1","version":1,"type":"single_choice",
            "learner":{"stem":[{"type":"paragraph","content":[{"text":"Synthetic prompt"}]}]},
            "answer":{"answer_key":[1],"status":"owner_key","scoring_excluded":False,"reviewer_needed":False}
        }]}
        self.schema={"$schema":"https://json-schema.org/draft/2020-12/schema",
            "type":"object","required":["exam","questions"],"properties":{"exam":{"type":"object"},
            "questions":{"type":"array","minItems":1}}}
        self.registry={"types":{"single_choice":{"publishable":True}}}
        self.evidence={"source_sha256":"a"*64,"source_question_count":1,
            "questions":{"synthetic-q1":{"source_verified":True,"interaction_verified":True,
              "answer_mapping_verified":True,"visual_verified":True,"held":False}}}
    def run_gate(self):
        for name,data in [("exam",self.exam),("schema",self.schema),("registry",self.registry),("evidence",self.evidence)]:
            (self.d/(name+".json")).write_text(json.dumps(data))
        return verify(*(self.d/(name+".json") for name in ("exam","schema","registry","evidence")))
    def test_synthetic_pass(self):
        self.assertTrue(self.run_gate()["release_eligible"])
    def test_html_rejected(self):
        self.exam["questions"][0]["learner"]["stem"][0]["content"][0]["text"]="<b>unsafe</b>"
        self.assertIn("html_or_script",[x["code"] for x in self.run_gate()["issues"]])
    def test_answer_leak_rejected(self):
        self.exam["questions"][0]["learner"]["correct_option_ids"]=[1]
        self.assertIn("answer_leak",[x["code"] for x in self.run_gate()["issues"]])
    def test_held_rejected(self):
        self.evidence["questions"]["synthetic-q1"]["held"]=True
        self.assertIn("question_held",[x["code"] for x in self.run_gate()["issues"]])
    def test_count_mismatch_rejected(self):
        self.evidence["source_question_count"]=2
        self.assertIn("source_count_mismatch",[x["code"] for x in self.run_gate()["issues"]])
    def test_unverified_visual_rejected(self):
        self.evidence["questions"]["synthetic-q1"]["visual_verified"]=False
        self.assertIn("visual_not_verified",[x["code"] for x in self.run_gate()["issues"]])
    def test_unpublishable_type_rejected(self):
        self.registry["types"]["single_choice"]["publishable"]=False
        self.assertIn("type_not_publishable",[x["code"] for x in self.run_gate()["issues"]])
    def test_unknown_answer_status_rejected(self):
        self.exam["questions"][0]["answer"]["status"]="as_in_source_file"
        self.assertIn("invalid_answer_status",[x["code"] for x in self.run_gate()["issues"]])
    def test_no_raw_answers_in_report(self):
        result=self.run_gate()
        self.assertNotIn("synthetic prompt",json.dumps(result).lower())
        self.assertNotIn("answer_key",json.dumps(result))
if __name__=="__main__":unittest.main()
