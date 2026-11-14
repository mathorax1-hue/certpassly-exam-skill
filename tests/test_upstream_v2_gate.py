"""Synthetic tests for the fail-closed upstream V2 report gate."""
import unittest
from scripts.audit_upstream_question_v2 import summarize_checks, gate_decision


class V2GateTests(unittest.TestCase):
    def test_pass_only_when_all_checks_pass(self):
        checks = [{"id": "type_registry", "status": "pass", "detail": "30/30"}]
        self.assertEqual(gate_decision(checks), "PASS_CONTRACT_ONLY")

    def test_unverified_prevents_merge_approval(self):
        checks = [{"id": "browser", "status": "unverified", "detail": "not tested"}]
        self.assertEqual(gate_decision(checks), "BLOCKED_UNVERIFIED")

    def test_finding_prevents_merge_approval(self):
        checks = [
            {"id": "browser", "status": "unverified", "detail": "not tested"},
            {"id": "learner_leak", "status": "fail", "detail": "confirmed"}
        ]
        self.assertEqual(gate_decision(checks), "BLOCKED_FAIL")
        self.assertEqual(summarize_checks(checks),
                         {"pass": 0, "fail": 1, "unverified": 1})


if __name__ == "__main__":
    unittest.main()
