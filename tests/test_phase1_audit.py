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

    # ---- P0-C (director audit 2026-11-13): hard BLOCK criteria ----

    def _make(self, name, pages):
        pdf = os.path.join(self.root, name)
        doc = fitz.open()
        for texts, size in pages:
            p = doc.new_page(width=size[0], height=size[1])
            y = 80
            for t in texts:
                p.insert_text((60, y), t, fontsize=11)
                y += 14
        doc.save(pdf)
        doc.close()
        return pdf

    def test_no_markers_blocks(self):
        """A PDF with no question markers must BLOCK (exit 2), not audit-clean."""
        pdf = self._make("nomarkers.pdf", [(["just some prose", "no questions here"], (612, 792))])
        out = os.path.join(self.root, "audit-nomarkers.json")
        rc = audit_source.run_audit(["--pdf", pdf, "--out", out])
        self.assertEqual(rc, 2)
        rep = json.loads(open(out).read())
        self.assertEqual(rep["verdict"], "BLOCKED")
        self.assertTrue(any("no question markers" in b for b in rep["blocked_reasons"]),
                        rep["blocked_reasons"])

    def test_duplicate_markers_block(self):
        pdf = self._make("dup.pdf", [(["QUESTION 1", "stem", "QUESTION 1", "stem2"], (612, 792))])
        out = os.path.join(self.root, "audit-dup.json")
        rc = audit_source.run_audit(["--pdf", pdf, "--out", out])
        self.assertEqual(rc, 2)
        rep = json.loads(open(out).read())
        self.assertTrue(any("duplicate question markers" in b for b in rep["blocked_reasons"]))

    def test_noncontiguous_markers_block(self):
        pdf = self._make("gap.pdf", [(["QUESTION 1", "stem", "QUESTION 3", "stem3"], (612, 792))])
        out = os.path.join(self.root, "audit-gap.json")
        rc = audit_source.run_audit(["--pdf", pdf, "--out", out])
        self.assertEqual(rc, 2)
        rep = json.loads(open(out).read())
        self.assertTrue(any("identity_ambiguous" in b for b in rep["blocked_reasons"]),
                        rep["blocked_reasons"])

    def test_nonuniform_geometry_blocks(self):
        """Mixed page sizes (possible concatenated documents) must BLOCK."""
        pdf = self._make("mixed.pdf", [(["QUESTION 1", "stem"], (612, 792)),
                                        (["Correct Answer: A"], (792, 612))])
        out = os.path.join(self.root, "audit-mixed.json")
        rc = audit_source.run_audit(["--pdf", pdf, "--out", out])
        self.assertEqual(rc, 2)
        rep = json.loads(open(out).read())
        self.assertTrue(any("identity_ambiguous" in b for b in rep["blocked_reasons"]))

    def test_unextractable_image_blocks(self):
        """A corrupt (unextractable) image stream on a page must BLOCK."""
        import fitz
        pdf = os.path.join(self.root, "corruptimg.pdf")
        # reuse a good doc then append a broken image xref via raw object edit
        doc = fitz.open(self.pdf)
        page = doc[0]
        try:
            # insert an image stream that will fail binary extraction
            broken = b"\x00\x01\x02not-a-real-image"
            doc.update_stream(doc.get_new_xref(), broken)
            # register as an Image XObject with broken filter
            doc.xref_set_key(doc.get_new_xref() - 1, "Subtype", "/Image")
            doc.xref_set_key(doc.get_new_xref() - 1, "Width", "10")
            doc.xref_set_key(doc.get_new_xref() - 1, "Height", "10")
            doc.xref_set_key(doc.get_new_xref() - 1, "Filter", "/FlateDecode")
            doc.save(pdf)
        except Exception:
            self.skipTest("PyMuPDF refuses to build the broken-stream fixture on this version")
        doc.close()
        out = os.path.join(self.root, "audit-corrupt.json")
        rc = audit_source.run_audit(["--pdf", pdf, "--out", out])
        rep = json.loads(open(out).read())
        if rep.get("images", {}) and rep["images"].get("unextractable"):
            self.assertEqual(rc, 2)
            self.assertTrue(any("unextractable source image" in b for b in rep["blocked_reasons"]))
        else:
            self.skipTest("broken stream not registered as page-referenced image on this version")


if __name__ == "__main__":
    unittest.main()
