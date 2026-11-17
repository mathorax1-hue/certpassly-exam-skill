"""Synthetic, answer-free regression tests for the independent V2 gate."""
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from scripts.verify_site_v2_release_gate import verify, HTML, main

class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d=Path(self.tmp.name)
        self.source=self.d/"source.pdf"
        self.source.write_bytes(b"SYNTHETIC SOURCE CONTENT ONLY")
        self.proof=self.d/"proof.json"
        self.proof.write_text('{"synthetic":true}')
        self.exam={"exam":{"exam_code":"SYN-001"},"questions":[{
            "question_key":"synthetic-q1","version":1,"type":"single_choice",
            "learner":{"stem":[{"type":"paragraph","content":[{"text":"Synthetic prompt"}]}]},
            "answer":{"answer_key":[1],"status":"owner_key","scoring_excluded":False,"reviewer_needed":False}
        }]}
        self.schema={"$schema":"https://json-schema.org/draft/2020-12/schema",
            "type":"object","required":["exam","questions"],"properties":{"exam":{"type":"object"},
            "questions":{"type":"array","minItems":1}}}
        self.registry={"types":{"single_choice":{"publishable":True}}}
        proof_sha=hashlib.sha256(self.proof.read_bytes()).hexdigest()
        self.evidence={"source_sha256":hashlib.sha256(self.source.read_bytes()).hexdigest(),"source_question_count":1,
            "questions":{"synthetic-q1":{"source_verified":True,"interaction_verified":True,
              "answer_mapping_verified":True,"visual_verified":True,"held":False,
              "proof":{kind:{"path":"proof.json","sha256":proof_sha}
                       for kind in ("source","interaction","answer_mapping","visual")}}}}
    def run_gate(self):
        for name,data in [("exam",self.exam),("schema",self.schema),("registry",self.registry),("evidence",self.evidence)]:
            (self.d/(name+".json")).write_text(json.dumps(data))
        return verify(*(self.d/(name+".json") for name in ("exam","schema","registry","evidence")),self.source,self.d)
    def test_synthetic_pass_is_candidate_only_not_final_release(self):
        result = self.run_gate()
        self.assertTrue(result["candidate_validation_eligible"])
        self.assertFalse(result["final_exam_release_eligible"])
        self.assertEqual(result["release_authority"], "phase6_candidate_validation_only")
        self.assertNotIn("release_eligible", result)
    def test_cli_exit_code_tracks_candidate_validation_not_final_release(self):
        self.run_gate()
        report = self.d / "report.json"
        argv = [
            "verify_site_v2_release_gate.py",
            "--exam", str(self.d / "exam.json"),
            "--schema", str(self.d / "schema.json"),
            "--registry", str(self.d / "registry.json"),
            "--evidence", str(self.d / "evidence.json"),
            "--source-pdf", str(self.source),
            "--proof-root", str(self.d),
            "--report", str(report),
        ]
        output = io.StringIO()
        with patch("sys.argv", argv), redirect_stdout(output):
            self.assertEqual(main(), 0)
        result = json.loads(report.read_text())
        self.assertTrue(result["candidate_validation_eligible"])
        self.assertFalse(result["final_exam_release_eligible"])
        self.assertNotIn("release_eligible", result)

        self.evidence["questions"]["synthetic-q1"]["held"] = True
        self.run_gate()
        with patch("sys.argv", argv), redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 1)

    def test_html_rejected(self):
        self.exam["questions"][0]["learner"]["stem"][0]["content"][0]["text"]="<b>unsafe</b>"
        self.assertIn("html_or_script",[x["code"] for x in self.run_gate()["issues"]])
    def test_answer_leak_rejected(self):
        self.exam["questions"][0]["learner"]["correct_option_ids"]=[1]
        self.assertIn("answer_leak",[x["code"] for x in self.run_gate()["issues"]])
    def test_held_rejected(self):
        self.evidence["questions"]["synthetic-q1"]["held"] = True
        result = self.run_gate()
        self.assertIn("question_held", [x["code"] for x in result["issues"]])
        self.assertFalse(result["candidate_validation_eligible"])
        self.assertFalse(result["final_exam_release_eligible"])
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
    def test_source_pdf_hash_mismatch_rejected(self):
        self.source.write_bytes(b"CHANGED SOURCE")
        self.assertIn("source_sha256_mismatch",[x["code"] for x in self.run_gate()["issues"]])
    def test_proof_file_corruption_rejected(self):
        self.proof.write_text("CORRUPTED")
        self.assertIn("proof_sha256_mismatch",[x["code"] for x in self.run_gate()["issues"]])
    def test_proof_file_missing_rejected(self):
        self.proof.unlink()
        self.assertIn("proof_file_missing_or_unsafe",[x["code"] for x in self.run_gate()["issues"]])
    def test_proof_path_traversal_rejected(self):
        self.evidence["questions"]["synthetic-q1"]["proof"]["source"]["path"]="../outside"
        self.assertIn("proof_file_missing_or_unsafe",[x["code"] for x in self.run_gate()["issues"]])
    def test_no_raw_answers_in_report(self):
        result=self.run_gate()
        self.assertNotIn("synthetic prompt",json.dumps(result).lower())
        self.assertNotIn("answer_key",json.dumps(result))
if __name__=="__main__":unittest.main()
