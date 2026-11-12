"""A move of ak after which no tick of its version completes within the hour is put back.

A move links `~/.agentkit/tmp/keep/ak` to the bin/ak of the version it replaced, and each cron
slot runs that link's `back --when-broken` while it is there, then the tick.  The hour counts from
the link's time, which the move gives it and the tick that made the move sets to its own end.
Past it, with the link still there, ~/agentkit goes back to the version replaced, that version's
install.sh runs, the owner is paged once naming both commits, the link goes, and no later slot
moves to the commit put back.  `ak back` does so at once, and with no link exits 1.  Black-box,
the Home built as tests/test_key_a_move_is_final_once_its_version_ticks.py builds it: the commit
moved to has a bin/ak whose `watch` exits 1 and which runs the program for every other verb, and
an install.sh adding its own line to HOME/installed.  An hour passing is the link's time moved
back by as much.  Pages reach tests/fixtures/sink.py.  A tick sweeps /tmp, so the whole file runs
in one box with a /tmp of its own (`rerun_boxed`).
"""

import os
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home, rerun_boxed
from fixtures.akinstall import Install
from fixtures.sink import Sink

MINUTE = 60
# the commit moved to: no tick of it completes; every other verb is the program's
BROKEN = '#!/bin/sh\n[ "$1" != watch ] || exit 1\nexec "$(dirname "$0")/program" "$@"\n'
# its install.sh, which the tick making the move runs after the move: the link's time `{minutes}`
# minutes back, so that tick ends as long after the move
INSTALL = """#!/bin/sh
[ "$1" != --prepare ] || exit 0
echo moved >>"$HOME/installed"
exec {python} -c 'import os, sys, time
then = time.time() - {minutes} * 60
os.utime(sys.argv[1], (then, then), follow_symlinks=False)' "$HOME/.agentkit/tmp/keep/ak"
"""


class TicksThatStopAfterAMovePutItBack(unittest.TestCase):
    def moved(self, minutes=0):
        """A Home whose first slot moved ~/agentkit to a commit no tick of completes, the tick
        making the move ending `minutes` after it: the commit before and the one moved to."""
        self.home = home = self.enterContext(Home())
        akconfig.write(home, ["opus"])
        self.sink = self.enterContext(Sink(home))
        self.install = install = Install(home)
        self.link = home.path / ".agentkit" / "tmp" / "keep" / "ak"
        before, ak = install.head(), install.seed / "bin" / "ak"
        ak.rename(ak.with_name("program"))
        ak.write_text(BROKEN)
        ak.chmod(0o755)
        (install.seed / "install.sh").write_text(INSTALL.format(
            python=shlex.quote(sys.executable), minutes=minutes))
        after = install.advance()
        self.slot()
        self.assertEqual(install.head(), after)
        self.assertTrue(self.link.is_symlink())
        return before, after

    def slot(self):
        """One cron slot: the keeper while the link is there, then the tick."""
        if os.access(self.link, os.X_OK):
            self.home.run(str(self.link), "back", "--when-broken", timeout=300)
        self.home.run(self.install.ak, "watch", timeout=300)

    def age(self, minutes):
        """The link's time `minutes` further back, as that long passing leaves it."""
        then = os.lstat(self.link).st_mtime - minutes * MINUTE
        os.utime(self.link, (then, then), follow_symlinks=False)

    def seen(self):
        """What a person sees of the move: the commit live, the installs, the link, the pages."""
        return (self.install.head(), self.install.installed.read_text().splitlines(),
                os.path.lexists(self.link), self.sink.pages())

    def assert_put_back(self, before, after):
        head, installs, linked, pages = self.seen()
        self.assertEqual((head, installs, linked), (before, ["moved", "installed"], False))
        page, = pages
        self.assertIn(before[:7], page)
        self.assertIn(after[:7], page)

    def test_ticks_that_never_complete_are_put_back_past_the_hour(self):
        before, after = self.moved()
        self.slot()
        self.assertEqual(self.seen(), (after, ["moved"], True, []))
        self.age(61)
        self.slot()
        self.assert_put_back(before, after)
        seen = self.seen()
        for _ in range(2):
            self.slot()
            self.assertEqual(self.seen(), seen)

    def test_a_slow_tick_keeps_the_move(self):
        before, after = self.moved(minutes=40)
        self.age(21)    # 61 minutes after the move, 21 after the tick that made it ended
        self.slot()
        self.assertEqual(self.seen(), (after, ["moved"], True, []))

    def test_by_hand(self):
        before, after = self.moved()
        done = self.home.run(self.install.ak, "back", timeout=300)
        self.assertEqual(done.code, 0, done.err)
        self.assert_put_back(before, after)
        seen = self.seen()
        done = self.home.run(self.install.ak, "back", timeout=300)
        self.assertEqual(done.code, 1, done.err)
        self.assertEqual(self.seen(), seen)


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
