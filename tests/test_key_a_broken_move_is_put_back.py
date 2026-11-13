"""A move of ak that is broken from the start is put back: its install.sh never passing, or its
doctor failing where the version it replaced passes on the same home.

A move is final once a tick of the version it put live completes with its install.sh passed:
until then each tick runs that install.sh again, and past the hour the cron line's keeper puts
the move back.  After an install.sh that passes, the move runs the new bin/ak's doctor, and where
that exits 1 and the replaced version's exits 0 it is put back at once; where both exit 1 the
fault is the home's, and the move stays.  Put back is ~/agentkit at the commit it left, that
commit's install.sh run after the new one's, no version kept, the owner paged once naming both
commits, and the next slot moving nowhere.  Black-box, the Home built as
tests/test_key_ticks_that_stop_after_a_move_put_it_back.py builds it: the commit moved to has an
install.sh adding `moved` to HOME/installed, the one before `installed`.  An hour passing is the
link's time moved back by as much.  Pages reach tests/fixtures/sink.py.  A tick sweeps /tmp, so
the whole file runs in one box with a /tmp of its own (`rerun_boxed`).
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home, rerun_boxed
from fixtures.akinstall import Install
from fixtures.sink import Sink

MINUTE = 60
# the commit moved to's install.sh, `{then}` once it has said it ran
INSTALL = '#!/bin/sh\n[ "$1" != --prepare ] || exit 0\necho moved >>"$HOME/installed"\n{then}\n'
FAILS = "exit 1"
FAILS_ONCE = '[ -e "$HOME/failed" ] || { : >"$HOME/failed"; exit 1; }'
# its bin/ak: a doctor exiting 1, every other verb the program's
DOCTOR = '#!/bin/sh\n[ "$1" != doctor ] || exit 1\nexec "$(dirname "$0")/program" "$@"\n'


class ABrokenMoveIsPutBack(unittest.TestCase):
    def moved(self, then="", doctor=False, ticked=True):
        """A Home whose first slot moves ~/agentkit to one more commit, its install.sh going on
        to `then`, its doctor exiting 1 with `doctor`; with `ticked`, a tick ended a minute
        before, without which every version's doctor reads the tick as hung.  The commit before
        and the one moved to."""
        self.home = home = self.enterContext(Home())
        akconfig.write(home, ["opus"])
        self.sink = self.enterContext(Sink(home))
        self.install = install = Install(home)
        self.link = home.path / ".agentkit" / "tmp" / "keep" / "ak"
        before, ak = install.head(), install.seed / "bin" / "ak"
        if doctor:
            ak.rename(ak.with_name("program"))
            ak.write_text(DOCTOR)
            ak.chmod(0o755)
        (install.seed / "install.sh").write_text(INSTALL.format(then=then))
        after = install.advance()
        if ticked:
            home.ticked()
        self.assertEqual(self.slot(), 0)
        return before, after

    def slot(self):
        """One cron slot: the keeper while the link is there, then the tick; the tick's exit."""
        if os.access(self.link, os.X_OK):
            self.home.run(str(self.link), "back", "--when-broken", timeout=300)
        return self.home.run(self.install.ak, "watch", timeout=300).code

    def age(self, minutes):
        """The link's time `minutes` further back, as that long passing leaves it."""
        then = os.lstat(self.link).st_mtime - minutes * MINUTE
        os.utime(self.link, (then, then), follow_symlinks=False)

    def seen(self):
        """What a person sees of the move: the commit live, the installs, the link, the pages."""
        return (self.install.head(), self.install.installed.read_text().splitlines(),
                os.path.lexists(self.link), self.sink.pages())

    def assert_put_back(self, before, after, installs):
        head, installed, linked, pages = seen = self.seen()
        self.assertEqual((head, installed, linked), (before, [*installs, "installed"], False))
        page, = pages
        self.assertIn(before[:7], page)
        self.assertIn(after[:7], page)
        self.slot()
        self.assertEqual(self.seen(), seen)

    def test_an_install_that_never_passes_is_put_back_past_the_hour(self):
        before, after = self.moved(FAILS)
        for runs in range(2, 4):
            self.assertEqual(self.slot(), 0)
            self.assertEqual(self.seen(), (after, ["moved"] * runs, True, []))
        self.age(61)
        self.slot()
        self.assert_put_back(before, after, ["moved"] * 3)

    def test_an_install_that_passes_the_second_time_goes_live(self):
        before, after = self.moved(FAILS_ONCE)
        self.assertEqual(self.seen(), (after, ["moved"], True, []))
        self.assertEqual(self.slot(), 0)
        self.assertEqual(self.seen(), (after, ["moved"] * 2, False, []))

    def test_a_doctor_failing_where_the_replaced_one_passes_is_put_back_at_once(self):
        before, after = self.moved(doctor=True)
        self.assert_put_back(before, after, ["moved"])

    def test_a_doctor_failing_where_the_replaced_one_fails_too_stays(self):
        before, after = self.moved(doctor=True, ticked=False)
        self.assertEqual(self.seen(), (after, ["moved"], True, []))
        self.assertEqual(self.slot(), 0)
        self.assertEqual(self.seen(), (after, ["moved"], False, []))


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
