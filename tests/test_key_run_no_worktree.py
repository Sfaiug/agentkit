"""`ak run --no-worktree` works in the repository's own checkout, on the branch it has out.

Without it a run cuts a checkout of its own under ~/.agentkit/wt; with it the executor works in
the clone the task names, on whatever branch is checked out there, and its commits land on that
branch, the base branch untouched.  With --no-merge nothing is pushed.  The checkout is the
person's own, so `ak run clean` has nothing to remove: the clone and the work stay, and the
repository's `cleanup:` line does not run.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, on a project from gitrig.py, a config from akconfig.py,
a task from taskfile.py and scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

AGENTS = '---\ncleanup: pwd >>"$HOME/cleaned"\n---\n# widgets\n'


class NoWorktree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", files={"AGENTS.md": AGENTS})
        cls.started = cls.rig.branch("fix-api", {"api.py": "x = 2\n"})
        cls.rig.git("checkout", "-q", "fix-api")
        cls.main = cls.rig.head("main", remote=False)
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), "--no-worktree", "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.clean = cls.home.ak("run", "clean", cls.run_dir.name)

    def test_the_run_passes_working_in_the_clone_on_its_checked_out_branch(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual({key: self.state.get(key) for key in (
            "state", "verdict", "worktree", "branch", "no_merge")}, {
            "state": "pass", "verdict": "PASS", "worktree": str(self.rig.path),
            "branch": "fix-api", "no_merge": True})
        wt = self.home.path / ".agentkit/wt"
        self.assertEqual(list(wt.iterdir()) if wt.is_dir() else [], [])

    def test_its_commit_lands_on_that_branch_and_main_is_untouched(self):
        self.assertEqual(self.rig.git("rev-parse", "--abbrev-ref", "HEAD"), "fix-api")
        self.assertEqual(self.rig.git("rev-parse", "fix-api^"), self.started)
        self.assertEqual(self.rig.git("show", "fix-api:retry.txt"), "hello")
        self.assertEqual(self.rig.head("main", remote=False), self.main)

    def test_nothing_is_pushed(self):
        self.assertEqual(self.rig.head("fix-api"), self.started)
        self.assertEqual(self.rig.head("main"), self.main)
        self.assertEqual(self.rig.branches(), ["fix-api", "main"])

    def test_clean_removes_nothing_and_runs_no_cleanup(self):
        self.assertEqual(self.clean.code, 0, self.clean.out + self.clean.err)
        self.assertIn("nothing to remove", self.clean.out)
        self.assertTrue((self.rig.path / "retry.txt").is_file())
        self.assertEqual(self.rig.git("rev-parse", "--abbrev-ref", "HEAD"), "fix-api")
        self.assertFalse((self.home.path / "cleaned").exists())


if __name__ == "__main__":
    unittest.main()
