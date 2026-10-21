"""The answer key's task file is the orchestrator's template, filled in, and its run is found.

A run test states its task in a few words and reads what the run it started left; both hold
only if tests/fixtures/taskfile.py writes the shape ak reads and finds the run by its
directory.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig


class TaskFile(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def test_a_task_holds_the_templates_parts_in_order_and_leaves_out_empty_ones(self):
        repo = self.home.path / "code/acme"
        task = taskfile.write(self.home, repo, "Fix the API", goal="1. It answers.",
                              constraints=["Touch only api.py."], front={
                                  "base": "main", "files": ["api.py", "tests/"]},
                              done_when=["test -f api.py", "make check  # once"],
                              body="Notes.\n")
        self.assertEqual(task, self.home.root / "tasks/fix-the-api.md")
        self.assertEqual(task.read_text(), f"---\nrepo: {repo}\nbase: main\nfiles: api.py\n"
                         "files: tests/\n---\n# Fix the API\n\n## Goal\n1. It answers.\n\n"
                         "## Constraints\n- Touch only api.py.\n\n## Done when\n```bash\n"
                         "test -f api.py\nmake check  # once\n```\nNotes.\n")
        bare = taskfile.write(self.home, None, "Scratch", done_when=(), name="bare")
        self.assertEqual(bare.read_text(), f"# Scratch\n\n## Goal\n{taskfile.GOAL}\n")

    def test_runs_are_the_directories_under_runs_and_the_one_run_must_be_alone(self):
        self.assertRaisesRegex(AssertionError, r"found \[\]", taskfile.only_run, self.home)
        for name in ("20261020-1200-beta", "20261020-0900-acme", ".hidden/x"):
            (self.home.path / ".agentkit/runs" / name).mkdir(parents=True)
        self.home.write(".agentkit/runs/.slots.lock", "")
        self.assertEqual([path.name for path in taskfile.runs(self.home)],
                         ["20261020-0900-acme", "20261020-1200-beta"])
        self.assertRaisesRegex(AssertionError, "0900-acme", taskfile.only_run, self.home)

    def test_the_run_a_task_started_is_found_holding_that_task(self):
        task = taskfile.write(self.home, Rig(self.home).path)
        self.home.ak("run", str(task), "--no-merge")    # no harness here: it ends unstaffed
        self.assertEqual((taskfile.only_run(self.home) / "task.md").read_text(),
                         task.read_text())


if __name__ == "__main__":
    unittest.main()
