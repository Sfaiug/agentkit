"""~/agentkit half an hour short of going live at a commit it owes is a stall the audit is told.

A move a killed git left half done kept it off main for ten hours, its every tick saying only
`left as it is`, until a harness upgrade's gate failed on the tree.  However a move fails, a
commit owed that long -- one whose tests/live.sh passed, the fast-forward's target, or HEAD while
its install.sh is owed, from that pass, else from its landing -- is one stall (`stuck.stalls`),
none told while a harness upgrade holds the moves, nor again once it ends.  test_go_live_retries_install's offline clone.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_go_live_retries_install as base
from agentkit import config, stuck, update

git = base.git
DAY = 86400


class StallGoingLive(unittest.TestCase):
    setUp = base.GoLiveRetriesInstall.setUp

    def stall(self, now):
        return [found for found in stuck.stalls(now) if found[0].startswith("live:")]

    def landed(self):
        git(self.clone, "fetch", "-q", "origin", "main")
        return int(git(self.clone, "log", "-1", "--format=%ct", self.new))

    def test_a_commit_not_live_half_an_hour_after_it_landed_or_passed_is_a_stall(self):
        landed, key = self.landed(), f"live:{self.new}"
        self.assertEqual(self.stall(landed + stuck.FLOOR - 60),
                         [(key, "the stall of ak going live", None)])
        (found, what, line), = self.stall(landed + stuck.FLOOR + 60)
        self.assertEqual(found, key)
        self.assertIn(f"has not gone live at {self.new[:12]} for 31m;", line)
        (self.clone / "notes").write_text("mine\n")
        self.assertIn("for 31m, and it is dirty;", self.stall(landed + stuck.FLOOR + 60)[0][2])
        check = config.STATE / update.LIVE / f"{self.new}-{landed}"
        check.mkdir(parents=True)
        (check / "exit").write_text("0\n")
        os.utime(check / "exit", (landed + 600,) * 2)       # its pass dates it, not its landing
        self.assertEqual(self.stall(landed + stuck.FLOOR + 60), [(key, "the stall of ak going live", None)])

    def test_live_owes_none_an_owed_install_does_and_an_upgrade_holds_it(self):
        landed = self.landed()
        update.go_live(lambda line: None)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.new)
        self.assertEqual(self.stall(landed + DAY), [])
        (config.STATE / "agentkit-install-pending").touch()
        self.assertIn(f"has not gone live at {self.new[:12]} for 1d;", self.stall(landed + DAY)[0][2])
        with patch.object(update, "upgrading", return_value=True):
            self.assertEqual(self.stall(landed + DAY), [(f"live:{self.new}", "the stall of ak going live", None)])

    def test_an_install_a_pass_left_owed_is_dated_from_that_pass(self):
        now = self.landed() + DAY
        check = config.STATE / update.LIVE / f"{self.new}-{now - 600}"
        check.mkdir(parents=True)
        (check / "exit").write_text("0\n")
        os.utime(check / "exit", (now - 120,) * 2)
        (self.root / "broken").touch()
        for _ in range(2):          # the second tick finds HEAD at the commit the pass moved it to
            update.go_live(lambda line: None, now=now)
        self.assertEqual(git(self.clone, "rev-parse", "HEAD"), self.new)
        self.assertEqual(self.stall(now), [(f"live:{self.new}", "the stall of ak going live", None)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
