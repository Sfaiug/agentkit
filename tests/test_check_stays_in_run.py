"""A task whose done-when moves into the checkout its run starts from is refused at launch.

Each done-when line runs in the run's own checkout; a line that changes into the checkout
`repo:` names (`cd ~/code/acme && ...`, by its absolute path, `pushd`, `git -C` on it) checks
the owner's checkout instead of the run's change, so `ak run` and a job refuse it before any
run starts (`task.launch_refusal`).  Naming the checkout otherwise, a longer name that only
starts the same way, and a task naming no repository are left alone.  Offline: a temporary HOME.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import task


class CheckStaysInRun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-check-in-run-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        (self.home / "code" / "acme").mkdir(parents=True)
        patcher = patch.dict(os.environ, {"HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def refusal(self, *cmds, repo="~/code/acme"):
        return task.launch_refusal({"repo": repo}, list(cmds))

    def test_a_line_naming_the_checkout_is_refused_in_every_spelling(self):
        for line in ("cd ~/code/acme && pytest -q", f"cd {self.home}/code/acme && pytest -q",
                     "git -C ~/code/acme diff --quiet", "cd $HOME/code/acme/tests && make",
                     "true && pushd '~/code/acme' && make"):
            with self.subTest(line=line):
                said = self.refusal("pytest -q", line)
                self.assertIn(repr(line), said)
                self.assertIn("runs in the run's own checkout", said)
        self.assertIsNotNone(self.refusal("cd ~/code/acme && make", repo=f"{self.home}/code/acme"))

    def test_other_mentions_of_the_checkout_and_longer_names_are_left_alone(self):
        self.assertIsNone(self.refusal("pytest -q", "cd tests && make", "cd ~/code/acme-tools",
                                       "ln -sfn ~/code/acme/.venv .venv",
                                       "! grep -rn '~/code/acme/models.toml' README.md"))
        self.assertIsNone(self.refusal("cd ~/code/acme && make", repo="none"))
        self.assertIsNone(task.launch_refusal({}, ["cd ~/code/acme && make"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
