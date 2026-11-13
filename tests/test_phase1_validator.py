"""Public synthetic tests: the P0-B/P0-C validation gates on a synthetic tree.
Requires jsonschema (phase1 extra); skips cleanly on stdlib-only CI."""
import json
import os
import shutil
import tempfile
import unittest

try:
    import jsonschema  # noqa: F401
    HAVE_JSONSCHEMA = True
except ImportError:
    HAVE_JSONSCHEMA = False

from certpassly.phase1 import build_exports, validate_structured_v1
from certpassly.phase1 import p1common as P

from phase1_fixture import build_fixture


@unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema (phase1 extra) not installed")
class ValidatorGateTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="phase1-validator-")
        cfg = build_fixture(self.root)
        # a real (synthetic) PDF stand-in so the readback checks run
        self.pdf = os.path.join(self.root, "synthetic.pdf")
        with open(self.pdf, "wb") as f:
            f.write(b"%PDF-1.4 synthetic stand-in bytes")
        import hashlib
        sha = hashlib.sha256(open(self.pdf, "rb").read()).hexdigest()
        cfg["paths"]["pdf"] = self.pdf
        cfg["source"]["expected_pdf_sha256"] = sha
        cfg["source"]["expected_bytes"] = os.path.getsize(self.pdf)
        # source-manifest AND every question's provenance must carry the identity
        v1 = cfg["paths"]["out_dir"]
        man = P.jload(f"{v1}/source-manifest.json")
        man["source_pdf"] = {"sha256": sha, "bytes": os.path.getsize(self.pdf),
                             "verified": {"page_count": 1}}
        P.jdump(man, f"{v1}/source-manifest.json")
        qdir = f"{v1}/questions"
        for fn in sorted(os.listdir(qdir)):
            q = P.jload(f"{qdir}/{fn}")
            q["provenance"]["pdf_sha256"] = sha
            P.jdump(q, f"{qdir}/{fn}")
        self.cfg_path = os.path.join(self.root, "config.json")
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)
        build_exports.main(self.cfg_path)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _checks(self):
        v1 = json.load if False else None
        # validate writes extraction-report.json; read the checks from it
        rc = validate_structured_v1.main(self.cfg_path)
        rep = P.jload(os.path.join(self.root, "structured", "v1", "extraction-report.json"))
        return rc, {c["check"]: c["passed"] for c in rep["validation"]["checks"]}

    def test_cross_gate_passes_on_honest_fixture(self):
        rc, checks = self._checks()
        failed = {k: v for k, v in checks.items() if not v}
        self.assertEqual(failed, {}, f"unexpected failures: {failed}")
        self.assertTrue(any(k.startswith("unverified_types_and_keys_export_blocked_")
                            for k in checks), list(checks)[:40])
        self.assertTrue(checks.get("site_export_all_rows_have_reasons"))
        self.assertTrue(checks.get("pdf_present_for_readback") or
                        checks.get("pdf_sha256_readback"))

    def test_missing_pdf_fails_closed(self):
        """P0-C: a missing configured PDF must FAIL validation, not skip."""
        os.unlink(self.pdf)
        rc, checks = self._checks()
        self.assertNotEqual(rc, 0)
        self.assertIs(checks.get("pdf_present_for_readback"), False)

    def test_unverified_type_not_blocked_fails_gate(self):
        """P0-B: corrupt the export blockers (drop q005's reasons) -> the
        cross-gate must fail the validation."""
        v1 = os.path.join(self.root, "structured", "v1")
        ex_b = f"{v1}/export/site-format-v1-draft/export-blockers.json"
        blockers = P.jload(ex_b)
        for b in blockers["items"]:
            if b["question"] == "q005":
                b["cannot_export_without_review"] = []  # simulate the old defect
        P.jdump(blockers, ex_b)
        rc, checks = self._checks()
        self.assertNotEqual(rc, 0)
        self.assertIs(checks.get("site_export_all_rows_have_reasons"), False)

    def test_wrong_expected_answer_kinds_fails(self):
        cfg = P.load_config(self.cfg_path)
        cfg["expected"]["answer_kinds"]["typed_text_with_answer_image"] = 99
        P.jdump(cfg, self.cfg_path)
        rc, checks = self._checks()
        self.assertNotEqual(rc, 0)
        self.assertFalse(checks.get("answer_index_kinds", True))


if __name__ == "__main__":
    unittest.main()
