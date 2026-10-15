"""A task whose done-when moves into the checkout its run starts from is refused at launch.

Each done-when line runs in the run's own checkout; a line that changes into the checkout
`repo:` names (`cd ~/code/acme && ...`, by its absolute path, `pushd`, `git -C` on it, behind a
prefix or inside `$(...)`) checks the owner's checkout instead of the run's change, so `ak run`
and a job refuse it before any run starts (`task.launch_refusal`).  Naming the checkout
otherwise (in a comment, a quoted string, a link), a longer name that only starts the same way,
a relative folder, which is the run's own, and a task naming no repository are left alone.
Offline: a temporary HOME.
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
        self.addCleanup(os.chdir, os.getcwd())

    def refusal(self, *cmds, repo="~/code/acme"):
        return task.launch_refusal({"repo": repo}, list(cmds))

    def test_a_line_naming_the_checkout_is_refused_in_every_spelling(self):
        for line in ("cd ~/code/acme && pytest -q", f"cd {self.home}/code/acme && pytest -q",
                     "git -c core.pager=cat -C ~/code/acme diff --quiet",
                     "cd $HOME/code/acme/tests && make", "true && pushd ~/code/acme && make",
                     "cd -- ~/code/acme && make", 'cd "${HOME}/code/acme" && make',
                     'cd "$HOME"/code/acme && make', "(cd ~/code/acme; make) # once",
                     "MARK=1 command cd ~/code/acme && make", "printf a#b; cd ~/code/acme && make",
                     'test "$(cd ~/code/acme && make && echo ok)" = ok', "diff <(cd ~/code/acme) x",
                     "test `cd ~/code/acme && pwd` = x", "cd ~/code/acme/linked/.. && make",
                     "git --git-dir .git -C ~/code/acme diff", "git -C ~/code -C acme diff"):
            with self.subTest(line=line):
                said = self.refusal("pytest -q", line)
                self.assertIn(repr(line), said)
                self.assertIn("runs in the run's own checkout", said)
        self.assertIsNotNone(self.refusal("cd ~/code/acme && make", repo=f"{self.home}/code/acme"))

    def test_other_mentions_of_the_checkout_and_longer_names_are_left_alone(self):
        self.assertIsNone(self.refusal("pytest -q", "cd tests && make", "cd ~/code/acme-tools",
                                       'cd "$HOME/code/acme+tools"', 'cd "$HOME/code/acme tools"',
                                       "ln -sfn ~/code/acme/.venv .venv",
                                       "! grep -rn '~/code/acme/models.toml' README.md",
                                       "true # cd ~/code/acme", "! grep -Fq 'cd ~/code/acme' README.md",
                                       "printf '%s\\n' 'git -C ~/code/acme diff' | grep -q acme",
                                       "cd '~/code/acme'", "cd '$HOME/code/acme'",
                                       "~/code/acme/.venv/bin/python -m pytest", "grep -C 3 x ~/code/acme/y"))
        self.assertIsNone(self.refusal("cd ~/code/acme && make", repo="none"))
        self.assertIsNone(task.launch_refusal({}, ["cd ~/code/acme && make"]))

    def test_a_relative_folder_is_the_runs_own(self):
        os.chdir(self.home / "code")
        self.assertIsNone(self.refusal("cd acme && make", repo="acme"))
        self.assertIsNotNone(self.refusal("cd ~/code/acme && make", repo="acme"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
