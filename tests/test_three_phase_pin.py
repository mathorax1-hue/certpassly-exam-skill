"""Confirm the reviewed upstream pin and new technical stages."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from certpassly.upstream import STAGE_NAMES, expected_pin

ROOT = Path(__file__).resolve().parents[1]
PIN = "c8d4400598c225c6a32f029f28ca24429649edd6"


class ThreePhasePinTests(unittest.TestCase):
    def test_reviewed_commit_is_v131(self):
        self.assertEqual(expected_pin(ROOT), PIN)
        data = json.loads((ROOT / "config/repositories.json").read_text(encoding="utf-8"))
        self.assertEqual(data["upstream"]["reviewed_commit"], PIN)
        self.assertEqual(data["upstream"]["reviewed_tag"], "v1.3.1")
        script = (ROOT / "scripts/bootstrap_upstream.sh").read_text(encoding="utf-8")
        self.assertIn(PIN, script)
        self.assertNotIn("13dea6bab662ab1c4bbf87017e912e519907c8bc", script)

    def test_technical_stages_are_known(self):
        for name in ("intake", "extract", "export", "validate_site", "package"):
            self.assertIn(name, STAGE_NAMES)


if __name__ == "__main__":
    unittest.main()
