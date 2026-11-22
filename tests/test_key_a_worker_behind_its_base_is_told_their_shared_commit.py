"""A worker whose branch does not hold the run's base is told the commit the two share.

A `--no-worktree` run on a local branch behind main, or a `from:` branch whose merge of main
before round 1 was aborted on conflict, starts on a checkout without the base the run records.
A worker that squashed onto that base made a commit holding the old branch on top of main's tip,
whose landing took out of main whatever main merged since the branch forked.  Its prompt names
the commit the branch forks from instead, as it stands when each prompt is written, and a squash
onto that takes nothing out.

Black-box: the program `AK_BIN` names runs a task through tests/fixtures/akbin.py, against
gitrig.py's origin, fakegh.py's GitHub and fakeadapter.py's harnesses.  main is one change,
`other.txt`, ahead of an older local branch, and the executor squashes onto the base its
prompt's `Branch:` line names.
"""

from pathlib import Path
import json
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

BASE = re.compile(r"^Branch: \S+ \(based on ([^,)]*)", re.MULTILINE)
SQUASH = {"final": "## Summary\nwrote retry.txt", "hand_in": [["done"]], "sh": """\
printf 'hello\\n' >retry.txt && git add -A && git commit -qm 'add retry.txt'
base=$(sed -n 's/^Branch: [^ ]* (based on \\([^,)]*\\).*/\\1/p' "$1")
git reset -q --soft "$base" && git commit -qm 'add retry.txt'
"""}


class AWorkerBehindItsBaseIsToldTheirSharedCommit(unittest.TestCase):
    def run_behind(self, branch, moved, first, *, no_worktree=False):
        """Run the task with main's `moved` change made after the branch `older`, holding
        `branch`, forked from it, and the executor's `first` turn.  Any later turn leaves the
        work alone: in a `from:` run it can only be the fixer of the conflict with main.  Sets
        the rig, the fork, main's tip, the run's exit and the base each executor turn was told."""
        home = Home()
        self.addCleanup(home.close)
        self.rig = Rig(home, "widgets", files={"notes.txt": "line 1\n"})
        GitHub(home).grant(self.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        self.fork = self.rig.head()
        self.rig.branch("older", branch, push=False)
        self.tip = self.rig.commit({"other.txt": "landed meanwhile\n", **moved}, "another change")
        fakes = fakeadapter.install(home, claude=[first, "blocked"], codex="pass")
        if no_worktree:
            self.rig.git("checkout", "-q", "older")
        task = taskfile.write(home, self.rig.path, front=None if no_worktree else {"from": "older"})
        self.done = home.ak("run", str(task), *["--no-worktree"] * no_worktree, timeout=600)
        self.said = self.done.out + self.done.err
        self.state = json.loads((taskfile.only_run(home) / "run.json").read_text())
        self.told = [BASE.search(Path(call["argv"][3]).read_text())[1] for call in fakes["claude"].runs()]

    def test_no_worktree_on_an_older_branch_lands_keeping_main(self):
        self.run_behind({"api.py": "x = 2\n"}, {}, SQUASH, no_worktree=True)
        self.assertEqual(self.told, [self.fork], self.said)
        self.assertTrue(self.state.get("merged"), self.said)
        self.assertLessEqual({"api.py", "retry.txt", "other.txt"}, set(self.rig.files()))

    def test_from_a_branch_conflicting_with_main_does_not_take_main_out(self):
        self.run_behind({"notes.txt": "line one\n"}, {"notes.txt": "line 1 of main\n"}, SQUASH)
        self.assertEqual(self.told[0], self.fork, self.said)
        self.assertFalse(self.state.get("merged"), self.said)
        self.assertIn("other.txt", self.rig.files())

    def test_a_retry_after_the_worker_rebased_names_the_new_fork(self):
        # killed by a signal, the turn starts again at once on a checkout it moved onto main
        self.run_behind({"api.py": "x = 2\n"}, {}, {"sh": "git rebase -q origin/main", "exit": -9},
                        no_worktree=True)
        self.assertEqual(self.told, [self.fork, self.tip], self.said)


if __name__ == "__main__":
    unittest.main()
