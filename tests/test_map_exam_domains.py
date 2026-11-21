"""Domain mapping uses a saved official list only. No silent guessing."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "map_exam_domains.py"
spec = importlib.util.spec_from_file_location("map_exam_domains", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def site_doc():
    return {
        "exam": {"exam_code": "SYN-100"},
        "questions": [
            {
                "question_key": "q001",
                "domain": "Unassigned",
                "learner": {"stem": "How do you configure cluster networking policies?", "choices": []},
            },
            {
                "question_key": "q002",
                "domain": "Unassigned",
                "learner": {"stem": "What is a storage class used for?", "choices": []},
            },
        ],
    }


class DomainMapTests(unittest.TestCase):
    def test_flags_all_when_no_official_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            site = tmp_path / "SYN-100.site-format.v2.json"
            site.write_text(json.dumps(site_doc()), encoding="utf-8")
            raw = tmp_path / "raw"
            raw.mkdir()
            out = tmp_path / "domains.json"
            rc = tool.main(["--site-file", str(site), "--raw-dir", str(raw), "--output", str(out)])
            self.assertEqual(rc, 2)
            report = json.loads(out.read_text())
            self.assertEqual(report["status"], "domain_unmapped")
            self.assertEqual(report["unmapped_count"], 2)
            self.assertTrue(report["promotion_blocker"])
            self.assertFalse(report["official_domain_list_saved"])
            saved = json.loads(site.read_text())
            self.assertEqual(saved["questions"][0]["domain"], "Unassigned")

    def test_maps_from_official_list_with_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            site = tmp_path / "SYN-100.site-format.v2.json"
            site.write_text(json.dumps(site_doc()), encoding="utf-8")
            official = tmp_path / "official"
            official.mkdir()
            (official / "domains.csv").write_text(
                "domain_key,domain_name,keywords\n"
                "net,Cluster Networking,networking policies kube-proxy\n"
                "sto,Storage,persistent volume storage class\n",
                encoding="utf-8",
            )
            (official / "receipt.json").write_text(json.dumps({
                "url": "https://vendor.example/exam-guide",
                "sha256": "a" * 64,
                "quote": "Cluster Networking 25 percent. Storage 15 percent.",
            }), encoding="utf-8")
            out = tmp_path / "domains.json"
            rc = tool.main(["--site-file", str(site), "--raw-dir", str(tmp_path), "--output", str(out)])
            self.assertEqual(rc, 0)
            report = json.loads(out.read_text())
            self.assertEqual(report["status"], "mapped")
            self.assertEqual(report["mapped_count"], 2)
            self.assertEqual(report["unmapped_count"], 0)
            saved = json.loads(site.read_text())
            self.assertEqual(saved["questions"][0]["domain"], "Cluster Networking")
            self.assertEqual(saved["questions"][1]["domain"], "Storage")

    def test_does_not_use_list_without_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            site = tmp_path / "SYN-100.site-format.v2.json"
            site.write_text(json.dumps(site_doc()), encoding="utf-8")
            official = tmp_path / "official"
            official.mkdir()
            (official / "domains.csv").write_text(
                "domain_key,domain_name\nnet,Cluster Networking\n",
                encoding="utf-8",
            )
            out = tmp_path / "domains.json"
            rc = tool.main(["--site-file", str(site), "--raw-dir", str(tmp_path), "--output", str(out)])
            self.assertEqual(rc, 2)
            report = json.loads(out.read_text())
            self.assertFalse(report["official_domain_list_saved"])
            saved = json.loads(site.read_text())
            self.assertEqual(saved["questions"][0]["domain"], "Unassigned")


if __name__ == "__main__":
    unittest.main()
