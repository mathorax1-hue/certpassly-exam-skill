"""Public synthetic tests: read-only source audit against a real synthetic PDF.
Requires the pdf extra (PyMuPDF); skips cleanly on stdlib-only CI."""
import json
import os
import shutil
import tempfile
import unittest

try:
    import fitz
    HAVE_FITZ = True
except ImportError:
    HAVE_FITZ = False

from certpassly.phase1 import audit_source


@unittest.skipUnless(HAVE_FITZ, "PyMuPDF (pdf extra) not installed")
class AuditSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="phase1-audit-")
        cls.pdf = os.path.join(cls.root, "synthetic.pdf")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((60, 80), ["QUESTION 1", "Synthetic stem",
                                    "A. one", "B. two", "Correct Answer: A",
                                    "Section: (none)", "Explanation",
                                    "Explanation/Reference:"])
        doc.save(cls.pdf)
        doc.close()
        import hashlib
        cls.sha = hashlib.sha256(open(cls.pdf, "rb").read()).hexdigest()
        cls.size = os.path.getsize(cls.pdf)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def _run(self, *extra):
        out = os.path.join(self.root, "audit.json")
        argv = ["--pdf", self.pdf, "--out", out, *extra]
        rc = audit_source.run_audit(argv)
        return rc, json.loads(open(out).read())

    def test_audit_complete_with_matching_hash(self):
        rc, rep = self._run("--expected-sha256", self.sha, "--expected-bytes", str(self.size))
        self.assertEqual(rc, 0)
        self.assertEqual(rep["verdict"], "AUDIT_COMPLETE")
        self.assertEqual(rep["pdf"]["sha256"], self.sha)
        self.assertEqual(rep["markers"]["count"], 1)

    def test_hash_mismatch_blocks_fail_closed(self):
        rc, rep = self._run("--expected-sha256", "0" * 64)
        self.assertEqual(rc, 2)
        self.assertEqual(rep["verdict"], "BLOCKED")
        self.assertTrue(any("sha256 mismatch" in b for b in rep["blocked_reasons"]))

    def test_bytes_mismatch_blocks(self):
        rc, rep = self._run("--expected-bytes", "999999")
        self.assertEqual(rc, 2)
        self.assertEqual(rep["verdict"], "BLOCKED")

    def test_tool_label_override(self):
        rc, rep = self._run("--tool-label", "certpassly.phase1.audit_source @ abc123")
        self.assertEqual(rc, 0)
        self.assertEqual(rep["tool"], "certpassly.phase1.audit_source @ abc123")

    def test_tool_label_legacy_default(self):
        rc, rep = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(rep["tool"], "tools/phase1-extraction/audit_source.py")

    def test_encrypted_pdf_blocks(self):
        enc = os.path.join(self.root, "encrypted.pdf")
        doc = fitz.open(self.pdf)
        doc.save(enc, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="synthetic-owner",
                 user_pw="synthetic-user")
        doc.close()
        out = os.path.join(self.root, "audit-enc.json")
        rc = audit_source.run_audit(["--pdf", enc, "--out", out])
        self.assertEqual(rc, 2)
        rep = json.loads(open(out).read())
        self.assertEqual(rep["verdict"], "BLOCKED")
        self.assertTrue(any("encrypt" in b.lower() for b in rep["blocked_reasons"]))

    def test_audit_never_writes_the_pdf(self):
        import hashlib
        before = hashlib.sha256(open(self.pdf, "rb").read()).hexdigest()
        self._run()
        after = hashlib.sha256(open(self.pdf, "rb").read()).hexdigest()
        self.assertEqual(before, after, "read-only audit must not modify the PDF")


if __name__ == "__main__":
    unittest.main()
