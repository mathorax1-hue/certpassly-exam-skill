#!/usr/bin/env python3
"""Leak-check tests. Assertions never include owner question text."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_log_leak as C


STEM = "Based on the exhibit, which syntax publishes only RTT facts?"
CHOICE = "publish: output uses the task result field only"


def _site(path: Path) -> None:
    doc = {
        "questions": [
            {
                "question_key": "q003",
                "type": "image_based_choice",
                "learner": {
                    "stem": [{"type": "paragraph", "content": [{"text": STEM}]}],
                    "choices": [[{"type": "paragraph", "content": [{"text": CHOICE}]}]],
                    "media": [{"url": "/storage/EXAM/media/p-2_1.png", "alt": "a long enough alt string here"}],
                },
            }
        ]
    }
    path.write_text(json.dumps(doc), encoding="utf-8")


class LeakCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.site = self.dir / "exam.site-format.v2.json"
        _site(self.site)

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_log_passes(self):
        log = self.dir / "clean.log"
        log.write_text("exam_code=DEMO exported_question_count=1 held_count=0\n", encoding="utf-8")
        self.assertEqual(C.main(["--log", str(log), "--site-file", str(self.site)]), 0)

    def test_stem_in_log_fails_without_printing_it(self):
        log = self.dir / "dirty.log"
        log.write_text("pipeline said: %s\n" % STEM, encoding="utf-8")
        out = self.dir / "report.json"
        code = C.main(["--log", str(log), "--site-file", str(self.site), "--output", str(out)])
        self.assertEqual(code, 2)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "fail")
        self.assertGreater(report["phrase_hits"], 0)
        dumped = out.read_text(encoding="utf-8") + log.name
        self.assertNotIn(STEM, dumped)

    def test_secret_prefix_fails(self):
        log = self.dir / "secret.log"
        log.write_text("Authorization: Bearer " + ("a" * 24) + "\n", encoding="utf-8")
        self.assertEqual(C.main(["--log", str(log), "--site-file", str(self.site)]), 2)

    def test_collects_media_file_name(self):
        phrases = C.collect_phrases(self.site, None, None)
        self.assertTrue(any(p.endswith("p-2_1.png") or "p-2_1.png" == p for p in phrases) or any("alt string" in p for p in phrases))


if __name__ == "__main__":
    unittest.main()
