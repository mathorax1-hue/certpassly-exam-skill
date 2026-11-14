import importlib.util, hashlib, json
from pathlib import Path
import tempfile, unittest
P=Path(__file__).resolve().parents[1]/"scripts"/"audit_source_screenshot_shapes.py"
spec=importlib.util.spec_from_file_location("audit_source_shapes",P)
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)

class ShapeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        p=Path(tmp.name);self.pdf=p/"a.pdf";self.media=p/"media";self.v2=p/"v2"
        self.media.mkdir();self.v2.mkdir()
        self.pdf.write_bytes(b"%PDF-synthetic")
        (self.media/"q001-answer-area.jpg").write_bytes(b"\xff\xd8\xffabc")
        self.exp={"source_pdf_sha256":hashlib.sha256(self.pdf.read_bytes()).hexdigest(),"records":[{
            "question_key":"q001","kind":"inline_dropdown","shape":[2],
            "source_images":["q001-answer-area.jpg"],"required_terms":["Important context"]}]}
        self.doc={"question_key":"q001","type":"inline_dropdown","learner":{
            "stem":{"format":"html","text":"<p>Important context</p>"},
            "interaction":{"slots":[{"id":"blank1","choices":[{"id":"a","text":"A"},{"id":"b","text":"B"}]}]}}}
        (self.v2/"q001.v1.json").write_text(json.dumps(self.doc))
    def test_good_is_scoped_only(self):
        r=tool.inspect(self.exp,self.pdf,self.media,self.v2)
        self.assertTrue(r["scoped_shape_pass"])
        self.assertFalse(r["full_pdf_transcription_verified"])
        self.assertFalse(r["website_import_tested"])
    def test_wrong_image_or_shape_block(self):
        self.exp["records"][0]["shape"]=[3]
        r=tool.inspect(self.exp,self.pdf,self.media,self.v2)
        self.assertFalse(r["scoped_shape_pass"])
        self.assertIn("original_screenshot_shape_mismatch",r["records"][0]["problems"])
    def test_pdf_sha_must_match(self):
        self.exp["source_pdf_sha256"]="0"*64
        with self.assertRaises(ValueError):
            tool.inspect(self.exp,self.pdf,self.media,self.v2)
if __name__=="__main__":unittest.main()
