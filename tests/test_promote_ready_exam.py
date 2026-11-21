"""Synthetic tests for ready-exams promotion. Auto promotion stays off."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "promote_ready_exam.py"
spec = importlib.util.spec_from_file_location("promote_ready_exam", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

COMMIT = "a" * 40


def write_gates(tmp: Path, *, held=False, content="passed", imported="passed", domain="mapped", import_sha="auto") -> dict:
    site = tmp / "SYN-100.site-format.v2.json"
    site.write_text(json.dumps({"exam": {"exam_code": "SYN-100"}, "questions": []}), encoding="utf-8")
    work = {
        "held": [{"question_key": "x", "reasons": ["ocr"]}] if held else [],
        "answer_not_found": [],
        "missing_exam_facts": [],
    }
    (tmp / "worklist.json").write_text(json.dumps(work), encoding="utf-8")
    (tmp / "content.json").write_text(json.dumps({"status": content}), encoding="utf-8")
    import hashlib
    sha = hashlib.sha256(site.read_bytes()).hexdigest() if import_sha == "auto" else import_sha
    (tmp / "import.json").write_text(json.dumps({
        "status": imported,
        "rejected": [],
        "site_file_sha256": sha,
    }), encoding="utf-8")
    unmapped = 0 if domain == "mapped" else 1
    (tmp / "domains.json").write_text(json.dumps({
        "status": domain,
        "unmapped_count": unmapped,
        "promotion_blocker": domain != "mapped",
    }), encoding="utf-8")
    ready = tmp / "ready"
    ready.mkdir()
    return {
        "site": site,
        "work": tmp / "worklist.json",
        "content": tmp / "content.json",
        "imported": tmp / "import.json",
        "domains": tmp / "domains.json",
        "ready": ready,
        "out": tmp / "promo.json",
    }


class PromoteTests(unittest.TestCase):
    def _args(self, paths, promote=False):
        return [
            "--exam", "SYN-100",
            "--site-file", str(paths["site"]),
            "--ready-root", str(paths["ready"]),
            "--raw-commit", COMMIT,
            "--worklist", str(paths["work"]),
            "--content-gate", str(paths["content"]),
            "--import-gate", str(paths["imported"]),
            "--domain-gate", str(paths["domains"]),
            "--output", str(paths["out"]),
        ] + (["--promote"] if promote else [])

    def test_refuses_without_promote_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_gates(Path(tmp))
            rc = tool.main(self._args(paths, promote=False))
            self.assertEqual(rc, 2)
            data = json.loads(paths["out"].read_text())
            self.assertEqual(data["status"], "not_promoted")
            self.assertFalse((paths["ready"] / "exams" / "SYN-100").exists())
            self.assertTrue(any("promote flag" in b for b in data["blockers"]))

    def test_blocks_when_any_gate_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_gates(Path(tmp), held=True, content="blocked_needs_content", imported="failed")
            rc = tool.main(self._args(paths, promote=True))
            self.assertEqual(rc, 2)
            data = json.loads(paths["out"].read_text())
            self.assertGreaterEqual(len(data["blockers"]), 3)
            self.assertFalse(data["published"])

    def test_blocks_when_import_sha_does_not_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_gates(Path(tmp), import_sha="b" * 64)
            rc = tool.main(self._args(paths, promote=True))
            self.assertEqual(rc, 2)
            data = json.loads(paths["out"].read_text())
            self.assertTrue(any("sha256" in b for b in data["blockers"]))
            self.assertFalse((paths["ready"] / "exams" / "SYN-100").exists())

    def test_blocks_when_domains_are_unmapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_gates(Path(tmp), domain="domain_unmapped")
            rc = tool.main(self._args(paths, promote=True))
            self.assertEqual(rc, 2)
            data = json.loads(paths["out"].read_text())
            self.assertTrue(any("domain mapping" in b for b in data["blockers"]))

    def test_writes_provenance_when_all_gates_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_gates(Path(tmp))
            rc = tool.main(self._args(paths, promote=True))
            self.assertEqual(rc, 0)
            dest = paths["ready"] / "exams" / "SYN-100"
            self.assertTrue((dest / "SYN-100.site-format.v2.json").is_file())
            prov = json.loads((dest / "provenance.json").read_text())
            self.assertEqual(prov["raw_exam_commit"], COMMIT)
            self.assertFalse(prov["published"])
            self.assertIn(COMMIT, (dest / "PROVENANCE.md").read_text())


if __name__ == "__main__":
    unittest.main()
