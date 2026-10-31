"""A turn in a checkout where a rebase, merge or cherry-pick stopped on its conflicts runs on
this host.

git keeps a stopped one in the checkout's own git directory, which no parcel carries:
the turn a review sent to a machine to finish one found none in its fresh clone, and its
`git rebase --continue` failed there round after round.  Offline: a temporary repository and the
run's checkout of it, a linked worktree, and stand-ins for the machine, which is asked only where
nothing stopped.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, helper, machine_turn

WHO = ("-c", "user.name=acme", "-c", "user.email=acme@example.com", "-c", "commit.gpgsign=false")


def git(cwd, *args, check=True):
    subprocess.run(["git", "-C", str(cwd), *WHO, *args], check=check, capture_output=True,
                   env={**os.environ, "GIT_EDITOR": "true"})


class AStoppedRebaseTurnsHere(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="stopped-rebase-")
        self.addCleanup(tmp.cleanup)
        # a newline in the repository's path, which git's line-per-path answers would split
        self.root, repo = Path(tmp.name), Path(tmp.name, "acme\nrepo")
        self.checkout = self.root / "fix-api"
        git(self.root, "init", "-q", "-b", "main", str(repo))
        for where, text in ((repo, "v1\n"), (None, "fix\n"), (repo, "main\n")):
            if where is None:
                git(repo, "worktree", "add", "-q", "-b", "fix-api", str(self.checkout))
                where = self.checkout
            (where / "widget.txt").write_text(text)
            git(where, "add", "-A")
            git(where, "commit", "-q", "-m", text)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "_read_toml",
                                         return_value={"turns_on_machines": True}))
        stack.enter_context(patch.object(config, "manifest", return_value={
            "worker": {"sessions": ["~/.acme/{id}*"]}}))
        stack.enter_context(patch.object(machine_turn, "_program",
                                         return_value=("acme/1.2.3/acme", {})))
        stack.enter_context(patch.object(machine_turn, "_lend", return_value=["login"]))
        self.start = stack.enter_context(patch.object(helper, "start", return_value=(None, "")))

    def asks_a_machine(self):
        """Was a machine asked for room for a turn in the run's checkout?"""
        machine_turn.call({"harness": "acme", "provider": "acme"}, ["run"], self.checkout,
                          tempfile.mkdtemp(dir=self.root), {"HOME": str(self.root)}, (), None,
                          lambda *_a, **_kw: (0, "", False))
        return self.start.called

    def test_a_checkout_whose_rebase_stopped_runs_its_turn_here(self):
        git(self.checkout, "rebase", "main", check=False)
        self.assertFalse(self.asks_a_machine())

    def test_a_checkout_whose_merge_stopped_runs_its_turn_here(self):
        git(self.checkout, "merge", "main", check=False)
        self.assertFalse(self.asks_a_machine())

    def test_a_checkout_whose_cherry_pick_stopped_runs_its_turn_here(self):
        git(self.checkout, "cherry-pick", "main", check=False)
        self.assertFalse(self.asks_a_machine())

    def test_a_checkout_whose_cherry_picks_stopped_with_no_commit_runs_its_turn_here(self):
        # git keeps a range's picks in its sequencer; `--no-commit` leaves no CHERRY_PICK_HEAD
        git(self.checkout, "cherry-pick", "--no-commit", "HEAD..main", check=False)
        self.assertFalse(self.asks_a_machine())

    def test_a_checkout_with_nothing_stopped_still_asks_a_machine(self):
        self.assertTrue(self.asks_a_machine())


if __name__ == "__main__":
    unittest.main()
