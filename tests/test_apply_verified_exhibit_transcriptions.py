import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "apply_verified_exhibit_transcriptions.py"
spec = importlib.util.spec_from_file_location("apply_verified_exhibit_transcriptions", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

class ExhibitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.media=root/"media"
        self.v2=root/"v2"
        self.media.mkdir()
        self.v2.mkdir()
        self.raw=b"\xff\xd8\xff" + b"synthetic fixture"
        (self.media/"q001-exhibit.jpg").write_bytes(self.raw)
        self.ledger={"records":[{"question_key":"q001","source_filename":"q001-exhibit.jpg",
          "source_sha256":hashlib.sha256(self.raw).hexdigest(),
          "html":"<p>Exhibit context without an answer.</p>"}]}
        self.doc={"schema_version":"question.v2","question_key":"q001","version":1,
           "learner":{"stem":{"format":"html","text":"<p>Question</p>"},"interaction":{}},
           "answer":{"answer_key":{"choice":"a"}}}
        (self.v2/"q001.v1.json").write_text(json.dumps(self.doc))
    def test_success_does_not_touch_answer_or_add_media(self):
        r=tool.apply(self.ledger,self.media,self.v2)
        doc=json.loads((self.v2/"q001.v1.json").read_text())
        self.assertEqual(r["patched"],1)
        self.assertEqual(doc["answer"],self.doc["answer"])
        self.assertNotIn("media",doc["learner"])
        self.assertIn("Exhibit context",doc["learner"]["stem"]["text"])
        self.assertFalse(r["entire_question_source_fidelity_approved"])
    def test_hash_mismatch_fails_closed(self):
        self.ledger["records"][0]["source_sha256"]="0"*64
        with self.assertRaises(ValueError):
            tool.apply(self.ledger,self.media,self.v2)
    def test_html_script_rejected(self):
        self.ledger["records"][0]["html"]="<p>Normal</p><script>alert(1)</script>"
        with self.assertRaises(ValueError):
            tool.apply(self.ledger,self.media,self.v2)
    def test_wrong_source_key_rejected(self):
        self.ledger["records"][0]["question_key"]="q002"
        with self.assertRaises(ValueError):
            tool.apply(self.ledger,self.media,self.v2)
    def test_prevalidation_transactional(self):
        bad=dict(self.ledger["records"][0],question_key="q002",source_filename="q002-exhibit.jpg")
        self.ledger["records"].append(bad)
        with self.assertRaises(ValueError):
            tool.apply(self.ledger,self.media,self.v2)
        self.assertEqual(json.loads((self.v2/"q001.v1.json").read_text()),self.doc)

if __name__=="__main__":
    unittest.main()
