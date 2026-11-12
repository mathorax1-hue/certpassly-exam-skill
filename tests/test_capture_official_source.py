"""Synthetic tests for official-source capture; no network, real exam or review claims."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "capture_official_source.py"
spec = importlib.util.spec_from_file_location("capture_official_source", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
HOSTS = ["learn.microsoft.com"]
URL = "https://learn.microsoft.com/en-us/training/example"
BLOB = b"<html><head><title>Secret</title></head><body><p>Sample official statement</p><script>ignore me</script></body></html>"


class CaptureSourceTest(unittest.TestCase):
    def test_approved_host_subdomain_and_exact_credential_block(self):
        self.assertEqual(tool.validate_url(URL, HOSTS), URL)
        self.assertEqual(tool.validate_url("https://a.learn.microsoft.com/a", HOSTS),
                         "https://a.learn.microsoft.com/a")
        for bad in ("http://learn.microsoft.com/a", "https://learn.microsoft.com.evil.test/a",
                    "https://example.test/a", "https://user:pass@learn.microsoft.com/a",
                    "https://127.0.0.1/a", "https://learn.microsoft.com:8443/a"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tool.validate_url(bad, HOSTS)

    def test_visible_quote_matches_and_hashes_exact_bytes(self):
        receipt = tool.receipt_from_bytes(URL, BLOB, "Sample official statement", HOSTS)
        self.assertEqual(receipt["sha256"], hashlib.sha256(BLOB).hexdigest())
        self.assertTrue(receipt["quote_present_in_saved_content"])
        self.assertFalse(receipt["human_review_approved"])
        self.assertFalse(receipt["answer_correctness_approved"])

    def test_script_or_head_quote_not_accepted(self):
        for quote in ("ignore me", "Secret", "This text is absent"):
            with self.subTest(quote=quote), self.assertRaises(ValueError):
                tool.receipt_from_bytes(URL, BLOB, quote, HOSTS)

    def test_whitespace_normalization(self):
        quote = "Sample official statement"
        blob = b"<p>Sample \n official    statement</p>"
        self.assertTrue(tool.receipt_from_bytes(URL, blob, quote, HOSTS)["quote_present_in_saved_content"])

    def test_wrong_type_size_and_missing_quote(self):
        with self.assertRaises(ValueError):
            tool.receipt_from_bytes(URL, BLOB, "ok", HOSTS, content_type="image/png")
        with self.assertRaises(ValueError):
            tool.receipt_from_bytes(URL, b"", "ok", HOSTS)
        with self.assertRaises(ValueError):
            tool.receipt_from_bytes(URL, BLOB, "", HOSTS)

    def test_prevent_overwrite_and_directory_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "private"
            receipt = tool.receipt_from_bytes(URL, BLOB, "Sample official statement", HOSTS)
            p = tool.save_private_capture(base, "synthetic001", BLOB, receipt)
            saved = json.loads(p.read_text())
            self.assertEqual(saved["saved_content_path"], "synthetic001.html")
            self.assertEqual((base / saved["saved_content_path"]).read_bytes(), BLOB)
            with self.assertRaises(ValueError):
                tool.save_private_capture(base, "synthetic001", BLOB, receipt)
            with self.assertRaises(ValueError):
                tool.save_private_capture(base, "../traversal", BLOB, receipt)

    def test_offline_mode_does_not_claim_live_download(self):
        receipt = tool.receipt_from_bytes(URL, BLOB, "Sample official statement", HOSTS,
                                          mode="local_file_unverified_origin")
        self.assertEqual(receipt["capture_mode"], "local_file_unverified_origin")

    def test_redirect_handler_rejects_untrusted_host(self):
        redirect = tool.SafeRedirects(HOSTS)
        with self.assertRaises(ValueError):
            redirect.redirect_request(None, None, 302, "redirect", {},
                                      "https://learn.microsoft.com.attacker.test")

    def test_reject_excessively_long_quote(self):
        with self.assertRaises(ValueError):
            tool.receipt_from_bytes(URL, BLOB, "x" * 251, HOSTS)


if __name__ == "__main__":
    unittest.main()
