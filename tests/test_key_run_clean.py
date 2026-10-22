"""`ak run clean ID` removes a run's checkout, keeps its branch and work, and runs `cleanup:`.

A --no-merge run leaves its checkout under ~/.agentkit/wt for a person to look at, and `ak run
clean` is how it goes.  Nothing of the work goes with it: the run's branch stays in the
repository with its commits, and what was left uncommitted in the checkout is committed onto
that branch first.  Before the checkout goes, the repository's `cleanup:` line (AGENTS.md front
matter) runs once inside it, since only that line can undo what the project's tools made outside
the checkout; a cleanup that fails never stops the removal, and the run's log says how it ended.
A run that does not exist is refused.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, on a project from gitrig.py, a config from akconfig.py, a task
from taskfile.py and scripted harnesses from fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

# It fails, with status 1, after leaving its mark outside the checkout.
AGENTS = '---\ncleanup: pwd >>"$HOME/cleaned"; echo tidy; false\n---\n# widgets\n'


class RunClean(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", files={"AGENTS.md": AGENTS})
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        ran = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        assert ran.code == 0, ran.out + ran.err
        cls.run_dir = taskfile.only_run(cls.home)
        state = json.loads((cls.run_dir / "run.json").read_text())
        cls.worktree, cls.branch = Path(state["worktree"]), state["branch"]
        cls.cleaned = cls.home.path / "cleaned"
        cls.cleaned_by_the_run = cls.cleaned.exists()
        (cls.worktree / "notes.txt").write_text("left uncommitted\n")
        cls.done = cls.home.ak("run", "clean", cls.run_dir.name)
        cls.cleanups = cls.cleaned.read_text().splitlines() if cls.cleaned.exists() else []
        cls.again = cls.home.ak("run", "clean", cls.run_dir.name)

    def test_the_checkout_goes_and_ak_says_which_and_that_the_branch_stays(self):
        self.assertTrue(self.worktree.is_relative_to(self.home.path / ".agentkit/wt"))
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertFalse(self.worktree.exists())
        self.assertNotIn(str(self.worktree), self.rig.git("worktree", "list"))
        for word in (self.run_dir.name, str(self.worktree), self.branch):
            self.assertIn(word, self.done.out)

    def test_the_branch_keeps_the_run_s_commit_and_the_work_left_uncommitted(self):
        self.assertIn(self.branch, self.rig.branches(remote=False))
        self.assertEqual(self.rig.git("show", f"{self.branch}:retry.txt"), "hello")
        self.assertEqual(self.rig.git("show", f"{self.branch}:notes.txt"), "left uncommitted")
        self.assertEqual(self.rig.branches(), ["main"])

    def test_the_cleanup_line_runs_once_in_the_checkout_and_its_failure_stops_nothing(self):
        self.assertFalse(self.cleaned_by_the_run)    # a --no-merge run keeps its checkout
        self.assertEqual(self.cleanups, [str(self.worktree)])
        self.assertIn("tidy", (self.run_dir / "cleanup.log").read_text())
        log = (self.run_dir / "log.txt").read_text()
        self.assertRegex(log, r"(?m)cleanup.*\b1\b")

    def test_cleaning_again_succeeds_and_runs_no_cleanup(self):
        self.assertEqual(self.again.code, 0, self.again.out + self.again.err)
        self.assertEqual(self.cleaned.read_text().splitlines(), [str(self.worktree)])

    def test_a_run_that_does_not_exist_is_refused(self):
        done = self.home.ak("run", "clean", "20260101-0000-no-such-run")
        self.assertNotEqual(done.code, 0)
        self.assertIn("20260101-0000-no-such-run", done.err)


if __name__ == "__main__":
    unittest.main()
