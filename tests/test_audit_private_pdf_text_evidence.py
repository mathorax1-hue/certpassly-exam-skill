import importlib.util
from pathlib import Path
import unittest

S = Path(__file__).resolve().parents[1] / "scripts" / "audit_private_pdf_text_evidence.py"
spec = importlib.util.spec_from_file_location("audit_private_pdf_text_evidence", S)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class PDFTextEvidenceTests(unittest.TestCase):
    def test_page_references_and_unsourced_replacement(self):
        q = {"question_key": "q001",
             "created_source": "owner_file sha256:xyz QUESTION 1 pages [3, 4]"}
        self.assertEqual(mod.pages_from_source(q), [3, 4])
        replacement = {"questions": [{"question_key": "q002",
            "owner_question_replaced": "q002", "created_source": "SUPERSEDED"}]}
        r = mod.inspect(replacement, ["q002"], Path("/not/an/actual/pdf"))
        self.assertEqual(r["results"][0]["status"], "ORIGINAL_QUESTION_REPLACEMENT")
        self.assertFalse(r["source_fidelity_independently_verified"])

    def test_token_overlap_is_evidence_not_approval(self):
        self.assertTrue("purview" in mod.tokens("Microsoft Purview content"))
        self.assertEqual(mod.tokens("The answer is yes"), {"answer"}.intersection({"the"}) if False else {"answer"})
        content = {"prompt": "Choose", "rows": [{"id": "r1", "text": "Row one"}],
                   "answer_key": {"correct": "do not expose"}}
        joined = " ".join(mod.flatten_content(content))
        self.assertIn("Row one", joined)
        self.assertNotIn("do not expose", joined)

    def test_flagged_missing_question_keeps_block(self):
        r = mod.inspect({"questions": []}, ["q089"], Path("/unused"))
        self.assertEqual(r["results"][0]["status"], "QUESTION_MISSING")
        self.assertEqual(r["status"], "REVIEW_REQUIRED")

if __name__ == "__main__":
    unittest.main()
