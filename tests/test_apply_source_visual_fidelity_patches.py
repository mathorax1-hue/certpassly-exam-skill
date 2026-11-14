import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"apply_source_visual_fidelity_patches.py"
spec=importlib.util.spec_from_file_location("source_visual_patch",SCRIPT)
tool=importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

class VisualPatches(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.media=root/"media";self.v2=root/"v2"
        self.media.mkdir();self.v2.mkdir()
        self.raw=b"\xff\xd8\xffsynthetic source"
        (self.media/"q001-answer-area.jpg").write_bytes(self.raw)
        self.source={"filename":"q001-answer-area.jpg","sha256":hashlib.sha256(self.raw).hexdigest()}
        self.doc={"question_key":"q001","version":1,"type":"inline_dropdown",
                  "learner":{"stem":{"format":"html","text":"<p>Original [blank1]</p>"},
                             "interaction":{"prompt_with_slots":"Original {{blank1}}",
                               "slots":[{"id":"blank1","input":"dropdown","choices":[
                                   {"id":"c1","text":"[ Alpha"},{"id":"c2","text":"[ Beta"}]}]}},
                  "answer":{"answer_key":{"slots":{"blank1":"c1"}},"explanation":{
                       "core":"legacy","per_option":{"blank1.c1":"One","blank1.c2":"Two"}}},
                  "meta":{"flags":[]}}
        (self.v2/"q001.v1.json").write_text(json.dumps(self.doc))
    def patch(self,kind,**kwargs):
        return {"records":[{"question_key":"q001","source_images":[self.source],
            "kind":kind,**kwargs}]}
    def test_prompt_does_not_touch_answer(self):
        ledger=self.patch("prompt_and_stem",prompt="Complete {{blank1}}",stem="<p>Complete [blank1]</p>")
        report=tool.apply(ledger,self.media,self.v2)
        actual=json.loads((self.v2/"q001.v1.json").read_text())
        self.assertEqual(actual["answer"],self.doc["answer"])
        self.assertFalse(report["records"][0]["answer_structural_id_remapped"])
    def test_single_choice_menu_remaps_existing_key_only(self):
        ledger=self.patch("menu_to_single_choice",stem="<p>Which native menu entry?</p>",
            options=["Alpha","Beta","Gamma"],expected_old_keyed_label="[ Alpha",new_keyed_option_id="a")
        report=tool.apply(ledger,self.media,self.v2)
        actual=json.loads((self.v2/"q001.v1.json").read_text())
        self.assertEqual(actual["type"],"single_choice")
        self.assertEqual(actual["answer"]["answer_key"],{"correct_option_ids":["a"]})
        self.assertEqual(actual["answer"]["explanation"]["per_option"],{"a":"One","b":"Two"})
        self.assertTrue(report["records"][0]["answer_structural_id_remapped"])
        self.assertFalse(report["no_answer_research"] is False)
    def test_wrong_source_hash_blocks(self):
        self.source["sha256"]="0"*64
        with self.assertRaises(ValueError):
            tool.apply(self.patch("prompt_and_stem",prompt="Now {{blank1}}",stem="<p>Now [blank1]</p>"),self.media,self.v2)
    def test_mismatched_menu_key_blocks(self):
        with self.assertRaises(ValueError):
            tool.apply(self.patch("menu_to_single_choice",stem="<p>Select</p>",
             options=["Alpha","Beta"],expected_old_keyed_label="[ Beta",new_keyed_option_id="a"),self.media,self.v2)
    def test_unsafe_html_blocks(self):
        with self.assertRaises(ValueError):
            tool.apply(self.patch("prompt_and_stem",prompt="Now {{blank1}}",stem="<p>Hello</p><script>bad()</script>"),self.media,self.v2)
    def test_invalid_slot_blocks(self):
        with self.assertRaises(ValueError):
            tool.apply(self.patch("prompt_and_stem",prompt="Now {{wrong}}",stem="<p>Now</p>"),self.media,self.v2)

if __name__=="__main__":
    unittest.main()
