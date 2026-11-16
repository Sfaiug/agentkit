"""A standby keeps the version of ak a move here replaced till a pass of the new one ends well, and
puts it back when none does, as a home does with its tick
(tests/test_key_ticks_that_stop_after_a_move_put_it_back.py).  The job's one crontab line runs the
keeper, `~/.agentkit/tmp/keep/ak back --when-broken`, while it is there, then the pass, whatever
the keeper did.  A pass that moves ak here to its home's commit links that keeper; the next pass
that ends well takes the link away, the move final, and says why it went no further if its
home moved on meanwhile; the pass after moves on.  Past the keeper's hour with no pass ending
well, its home silent, ~/agentkit goes back to the commit before, that commit's install.sh runs,
the owner is paged once naming both commits and the home the passes copy, and the commit put back
is marked failed here: no pass goes to it again while its home runs it, `ak standby` saying so
after the copy's age, and the next pass goes to a newer commit once the home runs that, its move
there final.  Black-box, through tests/fixtures/twohomes.py: `acme-vm` is `acme-mini`'s standby,
and its job's line runs as cron hands it to sh; a home's install moves with git itself, so its
move is final, and each commit past the first has an install.sh adding `moved` to HOME/installed,
the first's `installed`.  An hour passing is the link's time moved back by as much.  Pages reach
tests/fixtures/sink.py.
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.sink import Sink
from fixtures.twohomes import Machines

MINUTE = 60
KEEP = ".agentkit/tmp/keep/ak"          # the version a move here replaced, while it is not final
STATE = ".agentkit/state/watch.json"    # the home's, which a pass copies
MOVED = '#!/bin/sh\n[ "$1" != --prepare ] || exit 0\necho moved >>"$HOME/installed"\n'
# a stand-in keeper: its words, and the copy of the home's state as it found it
KEEPER = '#!/bin/sh\n{{ echo "$*"; cat "$HOME/{state}"; }} >"$HOME/kept"\nexit 1\n'


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AStandbyPutsItsOldAkBack(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        self.addCleanup(home.answer)
        here.client_of(home)
        self.sink = Sink(here)
        self.addCleanup(self.sink.close)
        self.link = here.path / KEEP
        (home.install.seed / "install.sh").write_text(MOVED)
        self.first = here.install.head()
        home.write(STATE, "the home's first")
        done = here.ak("standby", home.name, timeout=300)     # the first pass, which keeps the job
        self.assertEqual(done.code, 0, done.out + done.err)
        line, = [line for line in (here.root / "crontab").read_text().splitlines()
                 if line.endswith(" # agentkit standby")]
        self.job = line.split(None, 5)[5]      # what cron hands sh

    def cron(self):
        """One run of the job's line, as cron runs it."""
        self.here.run("/bin/sh", "-c", self.job, timeout=600)

    def moved(self):
        """The home's install moved with git to one more commit on origin's main; its sha."""
        commit = self.home.install.advance()
        self.home.install.git("fetch", "-q", "origin")
        self.home.install.git("merge", "-q", "--ff-only", commit)
        return commit

    def age(self, minutes):
        """The link's time `minutes` further back, as that long passing leaves it."""
        then = os.lstat(self.link).st_mtime - minutes * MINUTE
        os.utime(self.link, (then, then), follow_symlinks=False)

    def seen(self):
        """What a person sees of ak here: the commit live, the installs, the link, the pages."""
        installed = self.here.install.installed
        return (self.here.install.head(),
                installed.read_text().splitlines() if installed.exists() else [],
                os.path.lexists(self.link), self.sink.pages())

    def test_the_jobs_line_runs_the_keeper_before_the_pass(self):
        home, here = self.home, self.here
        here.write(KEEP, KEEPER.format(state=STATE)).chmod(0o755)
        home.write(STATE, "the home's second")
        self.cron()
        self.assertEqual(here.path.joinpath("kept").read_text().splitlines(),
                         ["back --when-broken", "the home's first"])
        self.assertEqual(here.tree()[STATE], b"the home's second")    # the pass ran after it

    def test_the_next_pass_that_ends_well_makes_a_move_final(self):
        commit = self.moved()
        self.cron()
        self.assertEqual(self.seen(), (commit, ["moved"], True, []))
        self.age(59)        # within the keeper's hour
        self.cron()
        self.assertEqual(self.seen(), (commit, ["moved"], False, []))
        self.cron()         # its hour long over
        self.assertEqual(self.seen(), (commit, ["moved"], False, []))

    def test_the_pass_making_a_move_final_says_so_and_the_next_goes_on(self):
        commit = self.moved()
        self.cron()
        newer = self.moved()
        self.cron()
        self.assertEqual(self.seen(), (commit, ["moved"], False, []))
        said = self.here.ak("standby")
        self.assertEqual(said.code, 0, said.out + said.err)
        self.assertRegex(said.out, f"does not follow {self.home.name} yet: .*move of ak here is "
                                   "not final")
        self.cron()
        self.assertEqual(self.seen(), (newer, ["moved", "moved"], True, []))

    def test_a_move_no_pass_ends_well_after_is_put_back_and_not_followed_again(self):
        home, here = self.home, self.here
        commit = self.moved()
        self.cron()
        home.silence()
        self.cron()
        self.assertEqual(self.seen(), (commit, ["moved"], True, []))
        self.age(61)
        self.cron()
        head, installs, linked, pages = seen = self.seen()
        self.assertEqual((head, installs, linked), (self.first, ["moved", "installed"], False))
        page, = pages
        for named in (self.first[:7], commit[:7], home.name):
            self.assertIn(named, page)
        self.cron()         # the old ak's pass, its home silent still
        self.assertEqual(self.seen(), seen)
        home.answer()
        home.write(STATE, "the home's second")
        self.cron()
        self.assertEqual((self.seen(), here.tree()[STATE]), (seen, b"the home's second"))
        said = here.ak("standby")
        self.assertEqual(said.code, 0, said.out + said.err)
        self.assertRegex(said.out, rf"copies {home.name}: the copy is .* old\n"
                                   rf".*does not follow {home.name} yet: {commit[:12]} .*failed")
        newer = self.moved()
        self.cron()
        self.assertEqual(self.seen()[:3], (newer, ["moved", "installed", "moved"], True))


if __name__ == "__main__":
    unittest.main()
