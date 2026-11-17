"""The walk for a red target's first red commit checks the oldest commit of its window first:
red there, the red is older than the window and one check ends the walk; green there, halving
names the first red commit as before.

Offline: a local Git history, with each check faked by the commit it runs on.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import history, land

TESTS = ["t/bad.sh"]


class TheWalkAsksTheOldestFirst(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scratch = self.root / "scratch"
        environ = patch.dict(os.environ, {"HOME": str(self.root), "GIT_CONFIG_NOSYSTEM": "1"})
        environ.start()
        self.addCleanup(environ.stop)
        self.git("init", "-q", str(self.scratch))
        for n in range(6):
            self.git("-C", str(self.scratch), "-c", "user.name=acme", "-c",
                     "user.email=acme@example.invalid", "commit", "-q", "--allow-empty",
                     "-m", f"acme-{n}")
        self.commits = self.git("-C", str(self.scratch), "rev-list", "--reverse", "HEAD").split()
        self.checked, self.said = [], []

    def git(self, *args):
        return subprocess.run(["git", *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def walk(self, first_red):
        """Walk from the tip with every commit from `first_red` on failing TESTS twice, each
        earlier one passing them: the commits checked, in order."""
        red = set(self.commits[first_red:])

        def check(directory, state, scratch, cmds, log_path, log, *, exits, **_kw):
            sha = self.git("-C", str(scratch), "rev-parse", "HEAD")
            self.checked.append(sha)
            exits.append([1, 1] if sha in red else [0])
            return sha not in red, "", {"tests": TESTS} if sha in red else {}

        with (patch.object(land, "_check", side_effect=check),
              patch.object(history, "blame_merge", return_value="acme-run") as blame):
            land._blame_tip(self.root, {}, self.scratch, self.commits[-1], "sh suite.sh", "2/2",
                            TESTS, self.said.append)
        self.assertEqual(self.git("-C", str(self.scratch), "rev-parse", "HEAD"), self.commits[-1])
        return blame

    def test_a_red_on_every_commit_ends_the_walk_at_the_oldest_in_one_check(self):
        blame = self.walk(0)
        self.assertEqual(self.checked, [self.commits[0]])
        self.assertEqual(self.said, [f"red before {self.commits[0][:12]}: nobody is blamed"])
        blame.assert_not_called()

    def test_a_green_oldest_halves_to_the_first_red_commit(self):
        blame = self.walk(3)
        self.assertEqual(self.checked[0], self.commits[0])
        self.assertEqual(self.checked[-1], self.commits[3])
        blame.assert_called_once_with(self.commits[3], "tip", log=self.said.append)
        self.assertEqual(self.said, [f"{self.commits[3][:12]} first turned the target red: "
                                     "acme-run"])


if __name__ == "__main__":
    unittest.main()
