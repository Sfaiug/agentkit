"""A tick run from ~/agentkit fast-forwards it to origin's main and runs its install.sh, once.

Merged agentkit goes live on its own: the tick the cron line runs from ~/agentkit/bin/ak
fetches origin, moves that checkout to origin's main when the commit has no tests/live.sh to
pass first, runs install.sh, and logs `agentkit is live at <commit>`.  With nothing new on
origin it moves and installs nothing, so a merge is installed once, not every three minutes,
and no install is left pending.  Black-box: tests/fixtures/akinstall.py copies the program
`AK_BIN` names into a clone of a bare origin at HOME/agentkit, with an install.sh that only
counts its runs, and each tick runs that copy through tests/fixtures/akbin.py; this test fails
against `/bin/false`.
"""

from collections import namedtuple
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.akinstall import Install

Tick = namedtuple("Tick", "code err said head installs pending clean")


class FastForward(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        cls.install = Install(home)
        cls.start = cls.install.head()
        cls.idle = cls.tick()
        cls.tip = cls.install.advance()
        cls.moved = cls.tick()
        cls.again = cls.tick()

    @classmethod
    def tick(cls):
        """One `ak watch` of the live copy: what it said of agentkit, and where the checkout
        and its install stand after it."""
        done = cls.home.run(cls.install.ak, "watch")
        said = [line for line in done.out.splitlines()
                # the daily git gc of the checkout is its own story
                if ("agentkit" in line or line.startswith(" ")) and not line.startswith("git gc: ")]
        pending = cls.home.path / ".agentkit" / "state" / "agentkit-install-pending"
        return Tick(done.code, done.err, said, cls.install.head(), cls.install.installs(),
                    pending.exists(), cls.install.git("status", "--porcelain") == "")

    def test_a_tick_with_nothing_new_on_origin_moves_and_installs_nothing(self):
        self.assertEqual(self.idle.code, 0, self.idle.err)
        self.assertEqual(self.idle.said, [])
        self.assertEqual(self.idle.head, self.start)
        self.assertEqual(self.idle.installs, 0)
        self.assertFalse(self.idle.pending)

    def test_a_tick_fast_forwards_the_checkout_to_origin_main(self):
        self.assertEqual(self.moved.code, 0, self.moved.err)
        self.assertNotEqual(self.tip, self.start)
        self.assertEqual(self.install.origin(), self.tip)
        self.assertEqual(self.moved.head, self.tip)
        self.assertTrue(self.moved.clean)

    def test_it_runs_install_sh_and_says_which_commit_is_live(self):
        self.assertEqual(self.moved.installs, 1)
        self.assertFalse(self.moved.pending)
        self.assertEqual(self.moved.said, [f"agentkit is live at {self.tip[:12]}"])

    def test_the_next_tick_neither_moves_nor_installs_again(self):
        self.assertEqual(self.again.code, 0, self.again.err)
        self.assertEqual(self.again.said, [])
        self.assertEqual(self.again.head, self.tip)
        self.assertEqual(self.again.installs, 1)
        self.assertFalse(self.again.pending)


if __name__ == "__main__":
    unittest.main()
