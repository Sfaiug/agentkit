"""A run whose worktree cannot be set up ends in an error at once, and `ak run clean` removes it.

Before any model turn, ak hides the usual build junk from git in the run's new worktree, so no
round can commit an executor's `__pycache__`.  When that cannot be done the run must stop
there, spending no model turn, exit 2 and say why, with the reason kept in run.json and
result.md and the worktree it made recorded.  `ak run clean ID` then takes that worktree away,
from disk and from git, and keeps the branch, saying so in one line.  Here the clone's
`.git/info` is a file, so the exclude file cannot be written.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, on a project from gitrig.py, a config
from akconfig.py, a task from taskfile.py and scripted harnesses from fakeadapter.py.
"""

import json
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig


class SetupError(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="pass")
        info = cls.rig.path / ".git" / "info"
        shutil.rmtree(info)
        info.write_text("not a directory\n")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.worktree = cls.home.path / ".agentkit/wt" / cls.run_dir.name
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.registered = cls.listed_worktrees()
        cls.cleaned = cls.home.ak("run", "clean", cls.run_dir.name)

    @classmethod
    def listed_worktrees(cls):
        done = cls.home.run("git", "-C", str(cls.rig.path), "worktree", "list", "--porcelain")
        return [line.removeprefix("worktree ") for line in done.out.splitlines()
                if line.startswith("worktree ")]

    def test_the_run_stops_with_exit_2_and_says_why_before_any_model_turn(self):
        self.assertEqual(self.done.code, 2, self.done.out + self.done.err)
        self.assertIn(f"cannot exclude build junk in {self.worktree}", self.done.err)
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 0))

    def test_the_record_says_error_with_the_reason_and_the_worktree_it_made(self):
        self.assertEqual(self.state["state"], "error")
        self.assertIn(f"cannot exclude build junk in {self.worktree}", self.state["error"])
        self.assertEqual((self.state["worktree"], self.state["branch"]),
                         (str(self.worktree), "ak/add-retry-file"))
        self.assertIn(f"cannot exclude build junk in {self.worktree}",
                      (self.run_dir / "result.md").read_text())
        self.assertIn(str(self.worktree), self.registered)

    def test_clean_removes_the_worktree_and_keeps_the_branch(self):
        self.assertEqual(self.cleaned.code, 0, self.cleaned.err)
        self.assertEqual(self.cleaned.out, f"{self.run_dir.name}: removed worktree "
                                           f"{self.worktree}; branch ak/add-retry-file kept\n")
        self.assertFalse(self.worktree.exists())
        self.assertNotIn(str(self.worktree), self.listed_worktrees())
        self.assertIn("ak/add-retry-file", self.rig.branches(remote=False))
        self.assertEqual(self.rig.branches(), ["main"])


if __name__ == "__main__":
    unittest.main()
