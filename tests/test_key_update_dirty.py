"""A ~/agentkit somebody works in is left as it is by the tick, and why is said once per commit.

The tick only ever fast-forwards main: a checkout with changes of its own -- a file edited, or
one added that git is told not to show -- or with another branch out is somebody's work, so
the tick moves nothing, runs no install.sh and keeps the change, and its log says why, at
origin's commit: `WARN agentkit did not go live at <commit>:` over
`  update: agentkit: left as it is: <checkout> is dirty` (or `is on <branch>, not main`).
Said every three minutes it would bury the log, so it is said once per origin commit, and again
when origin moves on; state/agentkit-said-watch holds the commit it was last said for.
Black-box: tests/fixtures/akinstall.py copies the program `AK_BIN` names into a clone of a bare
origin at HOME/agentkit, and each tick runs that copy through tests/fixtures/akbin.py; this
test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akinstall import Install


class LeftAsIs(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus"])
        self.install = Install(self.home)

    def tick(self):
        """One `ak watch` of the live copy: the lines it said of agentkit."""
        done = self.home.run(self.install.ak, "watch")
        self.assertEqual(done.code, 0, done.err)
        return [line for line in done.out.splitlines()
                # the daily git gc of the checkout is its own story
                if ("agentkit" in line or line.startswith(" ")) and not line.startswith("git gc: ")]

    def assert_left_and_said_once(self, why):
        start = self.install.head()
        record = self.home.path / ".agentkit" / "state" / "agentkit-said-watch"
        because = f"  update: agentkit: left as it is: {self.install.path} is {why}"
        for _ in range(2):          # each new origin commit is said once
            tip = self.install.advance()
            self.assertEqual(self.tick(), [f"WARN agentkit did not go live at {tip[:12]}:",
                                           because])
            self.assertEqual(record.read_text().strip(), tip)
            self.assertEqual(self.tick(), [])
            self.assertEqual(record.read_text().strip(), tip)
        self.assertEqual(self.install.head(), start)
        self.assertEqual(self.install.installs(), 0)

    def test_a_checkout_with_an_edited_file_is_left_and_said_dirty_once_per_commit(self):
        notes = self.install.path / "notes"
        notes.write_text("somebody's edit\n")
        self.assert_left_and_said_once("dirty")
        self.assertEqual(notes.read_text(), "somebody's edit\n")

    def test_a_new_file_git_is_told_not_to_show_makes_the_checkout_dirty_too(self):
        self.install.git("config", "status.showUntrackedFiles", "no")
        scratch = self.install.path / "scratch"
        scratch.write_text("somebody's new file\n")
        self.assert_left_and_said_once("dirty")
        self.assertEqual(scratch.read_text(), "somebody's new file\n")

    def test_a_checkout_on_another_branch_is_left_and_said_so_once_per_commit(self):
        self.install.git("checkout", "-q", "-b", "fix-api")
        self.assert_left_and_said_once("on fix-api, not main")
        self.assertEqual(self.install.git("symbolic-ref", "--short", "HEAD"), "fix-api")


if __name__ == "__main__":
    unittest.main()
