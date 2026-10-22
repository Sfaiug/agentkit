"""A repository's `cleanup:` line runs once, in a run's checkout, before ak takes the checkout.

A project's tools can leave things outside a checkout that no removal of it reaches, a database or
a cluster, so its AGENTS.md front matter names one shell line that undoes them.  ak runs it in
the checkout while it is still there, with the repository's ~/.agentkit/env/<repo>.env, and keeps
what it printed in the run's cleanup.log, beside a line in the run's log.txt: before
`ak run clean` takes the checkout and keeps its branch, and before `ak run stop` takes both.  A
second removal never runs it again, and a line that fails never keeps a checkout from going.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from tests/fixtures/gitrig.py, against runs recorded as ak leaves them.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.gitrig import Rig

# Where it ran, on which branch and with which secret, then what a person reads in its log.
LINE = ('echo "$(pwd) $(git rev-parse --abbrev-ref HEAD) $ACME_SECRET" >> "$HOME/cleaned.txt"; '
        'echo dropped the acme database')
FAILING = "echo the acme cluster is not there; exit 3"


def agents_md(cleanup):
    return f"---\nusers: none\ncleanup: {cleanup}\n---\n# widgets\n"


class RepoCleanup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", files={"AGENTS.md": agents_md(LINE)})
        cls.home.write(".agentkit/env/widgets.env", "ACME_SECRET=s3cret\n")

    def ended(self, run_id, branch, state="fail"):
        """A run ak left with its checkout on a branch of its own: its directory and checkout."""
        worktree = self.home.path / ".agentkit/wt" / run_id
        if branch not in self.rig.branches(remote=False):
            self.rig.git("branch", branch, "main")
        self.rig.git("worktree", "add", "-q", str(worktree), branch)
        self.home.write(f".agentkit/runs/{run_id}/run.json", {
            "run_id": run_id, "state": state, "title": "Fix api", "repo": str(self.rig.path),
            "worktree": str(worktree), "branch": branch})
        return self.home.path / ".agentkit/runs" / run_id, worktree

    def marks(self, worktree):
        """Each time the line ran in that checkout: the branch and the secret it saw."""
        try:
            lines = (self.home.path / "cleaned.txt").read_text().splitlines()
        except FileNotFoundError:
            return []
        return [line.removeprefix(f"{worktree} ") for line in lines
                if line.startswith(f"{worktree} ")]

    def ak(self, *args):
        done = self.home.ak(*args)
        self.assertEqual(done.code, 0, f"ak {' '.join(args)}: {done.out}{done.err}")
        return done

    def logged(self, run_dir, line, outcome):
        log = (run_dir / "log.txt").read_text()
        self.assertTrue([row for row in log.splitlines()
                         if f"repo cleanup: {line} {outcome}" in row], log)

    def test_clean_runs_it_once_in_the_checkout_with_the_repos_secrets_and_keeps_the_branch(self):
        run_dir, worktree = self.ended("20261020-0900-fix-api", "ak/fix-api")
        self.ak("run", "clean", run_dir.name)
        self.assertEqual(self.marks(worktree), ["ak/fix-api s3cret"])
        cleanup = (run_dir / "cleanup.log").read_text()
        self.assertTrue(cleanup.startswith(f"$ {LINE}\n"), cleanup)
        self.assertIn("dropped the acme database\n", cleanup)
        self.logged(run_dir, LINE, "exited 0")
        self.assertFalse(worktree.exists())
        self.assertNotIn(str(worktree), self.rig.git("worktree", "list", "--porcelain"))
        self.assertIn("ak/fix-api", self.rig.branches(remote=False))
        self.ak("run", "clean", run_dir.name)
        self.assertEqual(self.marks(worktree), ["ak/fix-api s3cret"])

    def test_a_stop_runs_it_before_taking_checkout_and_branch_and_a_clean_after_runs_nothing(self):
        # An errored run is one the tick would retry: stopping it is the owner's off-switch.
        run_dir, worktree = self.ended("20261020-0910-fix-ui", "ak/fix-ui", state="error")
        self.ak("run", "stop", run_dir.name)
        self.assertEqual(self.marks(worktree), ["ak/fix-ui s3cret"])
        self.logged(run_dir, LINE, "exited 0")
        self.assertFalse(worktree.exists())
        self.assertNotIn("ak/fix-ui", self.rig.branches(remote=False))
        self.assertEqual(json.loads((run_dir / "run.json").read_text())["state"], "stopped")
        self.ak("run", "clean", run_dir.name)
        self.assertEqual(self.marks(worktree), ["ak/fix-ui s3cret"])

    def test_a_line_that_fails_still_lets_the_checkout_go(self):
        # The line is the checkout's own: this branch declares one that fails.
        self.rig.branch("ak/fix-db", {"AGENTS.md": agents_md(FAILING)}, push=False)
        run_dir, worktree = self.ended("20261020-0920-fix-db", "ak/fix-db")
        self.ak("run", "clean", run_dir.name)
        self.assertIn("the acme cluster is not there\n", (run_dir / "cleanup.log").read_text())
        self.logged(run_dir, FAILING, "exited 3")
        self.assertFalse(worktree.exists())
        self.assertIn("ak/fix-db", self.rig.branches(remote=False))
        self.assertEqual(json.loads((run_dir / "run.json").read_text())["state"], "fail")


if __name__ == "__main__":
    unittest.main()
