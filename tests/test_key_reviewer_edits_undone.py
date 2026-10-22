"""A reviewer's edits never reach the work: ak undoes them and keeps them as the round's patch.

A reviewer judges the work and never changes it, so a review cannot pass what it wrote itself.
A review turn that edits a tracked file and leaves a new one behind anyway has every change
undone once it ends: the branch, the checkout the next round builds on and what is delivered
carry only the executor's work.  Nothing a model wrote is lost either: the log names what was
undone and where it was saved, round-N/reviewer-changes.patch, a patch that applies to the
reviewed work.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py, with scripted harnesses from
fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

# The executor's step `work` commits retry.txt holding "hello\n"; the reviewer changes it.
EDIT = {"sh": "echo 'reviewer was here' >> retry.txt && echo 'a note' > notes.txt",
        "final": "Looks fine.", "hand_in": [["done"]]}


class ReviewerEditsUndone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex=EDIT)
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file")
        cls.done = cls.home.ak("run", str(task), "--no-merge", timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())
        cls.worktree = cls.home.path / ".agentkit/wt" / cls.run_dir.name
        cls.patch = cls.run_dir / "round-1/reviewer-changes.patch"

    def git(self, where, *args):
        done = self.home.run("git", "-C", str(where), *args)
        self.assertEqual(done.code, 0, done.err)
        return done.out

    def test_the_review_still_passes_and_the_log_says_what_was_undone_and_where_it_is(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(self.state["verdict"], "PASS")
        self.assertEqual([run["role"] for run in self.fakes["codex"].runs()], ["reviewer"])
        line = f"WARN undid reviewer changes: notes.txt, retry.txt; saved {self.patch}"
        log = (self.run_dir / "log.txt").read_text().splitlines()
        self.assertTrue([row for row in log if row.endswith(line)], log)

    def test_the_branch_and_its_checkout_carry_only_the_executor_s_work(self):
        self.assertEqual((self.worktree / "retry.txt").read_text(), "hello\n")
        self.assertFalse((self.worktree / "notes.txt").exists())
        self.assertEqual(self.git(self.worktree, "status", "--porcelain"), "")
        self.assertEqual(self.git(self.rig.path, "show", "ak/add-retry-file:retry.txt"), "hello\n")
        self.assertEqual(self.git(self.rig.path, "diff", "--name-only", "main",
                                  "ak/add-retry-file").split(), ["retry.txt"])

    def test_the_patch_holds_the_reviewer_s_changes_and_applies_to_the_reviewed_work(self):
        text = self.patch.read_text()
        for added in ("+reviewer was here", "+a note"):
            self.assertIn(added, text.splitlines())
        check = self.home.run("git", "-C", str(self.worktree), "apply", "--check",
                              str(self.patch))
        self.assertEqual(check.code, 0, check.err)


if __name__ == "__main__":
    unittest.main()
