import json
import sys
import tempfile
import unittest
from pathlib import Path

from certpassly.checkpoints import Checkpoints
from certpassly.pipeline import PlanError, inside, load_plan, run_plan


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "input.txt").write_text("version 1", encoding="utf-8")
        self.plan = self.root / "plan.json"
        self.state = self.root / ".certpassly"
        self.data = {"schema_version": 1, "stages": [
            {"name": "copy", "command": ["{python}", "-c",
             "from pathlib import Path; Path('output.txt').write_text(Path('input.txt').read_text())"],
             "inputs": ["input.txt"], "outputs": ["output.txt"], "needs": [], "timeout_seconds": 30},
            {"name": "copy2", "command": ["{python}", "-c",
             "from pathlib import Path; Path('output2.txt').write_text(Path('output.txt').read_text())"],
             "inputs": ["output.txt"], "outputs": ["output2.txt"], "needs": ["copy"], "timeout_seconds": 30}
        ]}
        self.save()

    def save(self):
        self.plan.write_text(json.dumps(self.data), encoding="utf-8")

    def test_first_run_and_cache(self):
        self.assertEqual([x["action"] for x in run_plan(self.root, self.plan, self.state)],
                         ["executed", "executed"])
        self.assertEqual([x["action"] for x in run_plan(self.root, self.plan, self.state)],
                         ["cached", "cached"])

    def test_changes_invalidate_dependent_stages(self):
        run_plan(self.root, self.plan, self.state)
        (self.root / "input.txt").write_text("version 2", encoding="utf-8")
        res = run_plan(self.root, self.plan, self.state)
        self.assertEqual([x["action"] for x in res], ["executed", "executed"])
        self.assertEqual((self.root / "output2.txt").read_text(), "version 2")

    def test_tampered_output_rebuilds(self):
        run_plan(self.root, self.plan, self.state)
        (self.root / "output.txt").write_text("tampered")
        res = run_plan(self.root, self.plan, self.state)
        self.assertEqual(res[0]["action"], "executed")
        self.assertEqual((self.root / "output.txt").read_text(), "version 1")

    def test_failure_then_repair_resumes(self):
        self.data["stages"][1]["command"] = ["{python}", "-c", "import sys; sys.exit(4)"]
        self.save()
        res = run_plan(self.root, self.plan, self.state)
        self.assertEqual([x["action"] for x in res], ["executed", "failed"])
        self.data["stages"][1]["command"] = ["{python}", "-c",
            "from pathlib import Path; Path('output2.txt').write_text(Path('output.txt').read_text())"]
        self.save()
        res = run_plan(self.root, self.plan, self.state)
        self.assertEqual([x["action"] for x in res], ["cached", "executed"])

    def test_no_double_stage_names(self):
        self.data["stages"].append(self.data["stages"][0])
        self.save()
        with self.assertRaises(PlanError):
            load_plan(self.root, self.plan)

    def test_no_path_traversal(self):
        with self.assertRaises(PlanError):
            inside(self.root, "../private.pdf")
        with self.assertRaises(PlanError):
            inside(self.root, "/tmp/private.pdf")

    def test_external_plan_blocked(self):
        with tempfile.TemporaryDirectory() as outer:
            with self.assertRaises(PlanError):
                load_plan(self.root, Path(outer) / "plan.json")

    def test_dry_run_does_not_execute_commands(self):
        res = run_plan(self.root, self.plan, self.state, dry_run=True)
        self.assertEqual(res[0]["action"], "would_run")
        self.assertFalse((self.root / "output.txt").exists())

    def test_state_has_no_private_source_text(self):
        run_plan(self.root, self.plan, self.state)
        with Checkpoints(self.state / "checkpoints.sqlite3") as cp:
            self.assertEqual(len(cp.list()), 2)
            self.assertNotIn("version 1", json.dumps(cp.list()))


if __name__ == "__main__":
    unittest.main()
