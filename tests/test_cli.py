import contextlib
import io
import unittest
from pathlib import Path

from certpassly.cli import main


class CLITests(unittest.TestCase):
    def test_doctor_json(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = main(["doctor", "--json"])
        self.assertEqual(code, 0)
        self.assertIn('"python"', out.getvalue())

    def test_verify_strict_rejects_pending(self):
        fixture = Path(__file__).parent / "fixtures" / "pending-review.json"
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = main(["verify-evidence", "--input", str(fixture), "--strict"])
        self.assertEqual(code, 2)
        self.assertIn('"status": "blocked"', out.getvalue())


if __name__ == "__main__":
    unittest.main()
