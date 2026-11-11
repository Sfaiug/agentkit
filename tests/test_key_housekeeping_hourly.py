"""Git housekeeping runs at most once an hour, not on every tick.

A tick has 3 minutes, and its git housekeeping need not take from every one.  ak keeps the Unix
time housekeeping last ran in ~/.agentkit/state/git-housekeeping: a tick 10 minutes after it
runs none, one 61 minutes after it runs it again, and `ak doctor`'s tick line names when it last
ran.  The program reads its own clock, so the test moves that time back to make a tick come
later.  Housekeeping that runs collects each idle repository due its daily `git gc`, and the
repository here is due before every tick: its own mark (`.git/ak-gc`) is gone.  Black-box: the
program `AK_BIN` names ticks from outside in tests/fixtures/akbin.py's box, its `git` a fake
that logs each command and runs the real one.
"""

import os
from pathlib import Path
import shlex
import shutil
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import SYSTEM, Home, boxable

MINUTE = 60
MARK = ".agentkit/state/git-housekeeping"
GIT = '#!/bin/sh\nprintf "%s\\n" "$*" >> {log}\nexec {real} "$@"\n'


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class HousekeepingHourly(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(Home())
        akconfig.write(self.home, ["opus"])
        self.repo = self.home.path / "code" / "acme"
        self.repo.mkdir(parents=True)
        for args in (("init", "-q"), ("commit", "--allow-empty", "-qm", "seed")):
            done = self.home.run("git", "-C", self.repo, *args)
            self.assertEqual(done.code, 0, done.err)
        real = shutil.which("git", path=os.pathsep.join(SYSTEM))
        self.home.fake("git", GIT.format(log=shlex.quote(str(self.home.log("git"))),
                                         real=shlex.quote(real)))

    def collections(self):
        """How many `git gc`s one tick runs."""
        (self.repo / ".git" / "ak-gc").unlink(missing_ok=True)
        self.home.log("git").unlink(missing_ok=True)
        done = self.home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        log = self.home.log("git")
        return sum("gc" in line.split() for line in log.read_text().splitlines()
                   ) if log.exists() else 0

    def ran(self, minutes):
        """Housekeeping last ran `minutes` ago, as the program's clock reads it."""
        at = time.time() - minutes * MINUTE
        self.home.write(MARK, f"{at}\n")
        return at

    def test_two_ticks_10_minutes_apart_run_housekeeping_once_and_one_61_minutes_on_again(self):
        self.assertEqual(self.collections(), 1)
        first = self.ran(10)
        self.assertEqual(self.collections(), 0)
        before = time.time()
        line = next(line for line in self.home.ak("doctor").out.splitlines()
                    if line.startswith("tick  "))
        ages = range(int(before - first) // MINUTE, int(time.time() - first) // MINUTE + 1)
        self.assertIn(line.rpartition(" · ")[2], [f"git housekeeping ran {age}m ago"
                                                  for age in ages])
        self.ran(61)
        self.assertEqual(self.collections(), 1)


if __name__ == "__main__":
    unittest.main()
