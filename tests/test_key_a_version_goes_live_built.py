"""A version of ak goes live only once its own `install.sh --prepare` passed in its folder.

Every seat's hooks and the cron tick run ~/agentkit/bin/ak, and Go's is built from go/, which git
does not track: a build run after the swap would leave ~/agentkit without a working ak until it
ended.  So the tick runs the new version's `install.sh --prepare` where that version is checked
out, before it is swapped in; one that fails moves and installs nothing, leaves no install owed
by the version still live, and the next tick tries again.  Black-box: tests/fixtures/akinstall.py's
Home, as tests/test_key_update_ff.py builds it, each new commit on origin holding an install.sh of
its own that notes in HOME/ran what ran, the commit checked out where it ran and the one
HOME/agentkit held then; this test fails against `/bin/false`.
"""

from collections import namedtuple
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home, rerun_boxed
from fixtures.akinstall import Install

# `{code}`: how its --prepare exits
INSTALL = """#!/bin/sh
if [ "$1" = --prepare ]; then
  echo "prepare $(git rev-parse HEAD) $(git -C "$HOME/agentkit" rev-parse HEAD)" >>"$HOME/ran"
  printf 'not built yet \\377\\n' >&2    # a byte no UTF-8 holds says nothing of how it went
  exit {code}
fi
echo "install $(git -C "$HOME/agentkit" rev-parse HEAD)" >>"$HOME/ran"
"""
Tick = namedtuple("Tick", "code err out head ran installs pending")


class AVersionGoesLiveBuilt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        cls.install = Install(home)
        cls.start = cls.install.head()
        cls.unbuilt = cls.commit(1)
        cls.refused = cls.tick(), cls.tick()
        cls.built = cls.commit(0)
        cls.moved = cls.tick()

    @classmethod
    def commit(cls, code):
        """One more commit on origin's main, its --prepare exiting `code`; its sha."""
        (cls.install.seed / "install.sh").write_text(INSTALL.format(code=code))
        return cls.install._push(f"a prepare that exits {code}")

    @classmethod
    def tick(cls):
        """One `ak watch` of the live copy, and where the checkout and its installs stand then."""
        done = cls.home.run(cls.install.ak, "watch")
        ran = cls.home.path / "ran"
        pending = cls.home.path / ".agentkit" / "state" / "agentkit-install-pending"
        return Tick(done.code, done.err, done.out, cls.install.head(),
                    ran.read_text().splitlines() if ran.exists() else [], cls.install.installs(),
                    pending.exists())

    def test_a_prepare_that_exits_1_moves_and_installs_nothing_tick_after_tick(self):
        prepared = f"prepare {self.unbuilt} {self.start}"
        for n, tick in enumerate(self.refused, 1):
            with self.subTest(tick=n):
                self.assertEqual(tick.code, 0, tick.err)
                self.assertEqual(tick.head, self.start)
                self.assertEqual(tick.ran, [prepared] * n)
                self.assertEqual(tick.installs, 0)
                self.assertFalse(tick.pending)
        first = self.refused[0].out
        self.assertIn(f"agentkit did not go live at {self.unbuilt[:12]}", first)
        self.assertIn("not built yet", first)

    def test_a_prepare_that_exits_0_goes_live_and_its_install_runs_once_after_it(self):
        self.assertEqual(self.moved.code, 0, self.moved.err)
        self.assertEqual(self.moved.head, self.built)
        self.assertEqual(self.moved.ran[2:], [f"prepare {self.built} {self.start}",
                                              f"install {self.built}"])
        self.assertEqual(self.moved.installs, 0)
        self.assertIn(f"agentkit is live at {self.built[:12]}", self.moved.out)


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
