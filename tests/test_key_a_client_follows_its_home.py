"""A client's own moves of ak go to the commit ~/agentkit is at on its home, as a standby's pass
does (tests/test_key_standby_install_follows_home.py): `ak update` there, and the update opening
`ak` starts, move its install from ak's remote, swapped in, its install.sh run once, and never to
the remote's main past it, whose tests/live.sh only a home's tick checks.  The home is asked on
its own paths, so one whose HOME is at another path than the client's is followed too.  Only once
the home's move there is final: while its keep link is there (`~/.agentkit/tmp/keep/ak`) the
client stays where it is.  Forward only: a client ahead of its home stays there.  A home that does
not answer moves nothing.  Each stay is no failure: `ak update` exits 0 with a line saying why,
in the words `ak standby` uses.  A machine with a standby's job is a client like any other, though
its pass copies the home's checks of tests/live.sh, one of the remote's main passed among them.
The update opening `ak` starts asks the home, not the remote, so a remote out of reach holds
nothing back.  Black-box, through tests/fixtures/twohomes.py: the machines' installs are clones
of one origin, both at one commit, and a key moves one with git itself.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

KEEP = ".agentkit/tmp/keep/ak"              # the home's link while its last move is not final
LIVE = ".agentkit/state/live-checks"        # a machine's checks of tests/live.sh


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AClientFollowsItsHome(unittest.TestCase):
    def pair(self, homes=None):
        """`acme-vm`, a client of `acme-mini`, each HOME where `homes` puts it, both installs at
        `first`."""
        machines = Machines("acme-mini", "acme-vm", homes=homes)
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        here.client_of(home)
        self.first = home.install.head()

    def pulled(self, machine, commit):
        """`machine`'s clone moved with git to `commit` on origin's main; `commit`."""
        machine.install.git("fetch", "-q", "origin")
        machine.install.git("merge", "-q", "--ff-only", commit)
        return commit

    def moved(self, machine):
        """`machine`'s clone moved with git to one more commit on origin's main, and the main
        one more past it; the commit moved to."""
        commit = self.pulled(machine, machine.install.advance())
        machine.install.advance()
        return commit

    def updated(self):
        """`ak update` on the client, which exits 0 however its install fares; what it said."""
        done = self.here.ak("update", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out

    def seen(self):
        return self.here.install.head(), self.here.install.installs()

    def test_ak_update_goes_to_its_homes_commit_though_main_is_past_it(self):
        self.pair()
        commit = self.moved(self.home)
        self.updated()
        self.assertEqual(self.seen(), (commit, 1))

    def test_a_home_at_another_path_than_the_clients_is_followed_too(self):
        self.pair(homes={"acme-mini": "Users/acme"})
        commit = self.moved(self.home)
        self.updated()
        self.assertEqual(self.seen(), (commit, 1))

    def test_a_homes_move_not_final_moves_nothing_here_till_it_is(self):
        self.pair()
        home = self.home
        commit = self.moved(home)
        keep = home.path / KEEP
        keep.parent.mkdir(parents=True)
        keep.symlink_to(Path(home.env["HOME"], ".agentkit/versions/acme/bin/ak"))
        self.assertRegex(self.updated(), f"does not follow {home.name} yet: .*not final")
        self.assertEqual(self.seen(), (self.first, 0))
        keep.unlink()
        self.updated()
        self.assertEqual(self.seen(), (commit, 1))

    def test_a_client_ahead_of_its_home_stays_there(self):
        self.pair()
        commit = self.moved(self.here)
        self.assertRegex(self.updated(), f"does not follow {self.home.name} yet: .*ahead")
        self.assertEqual(self.seen(), (commit, 0))

    def test_a_standby_stays_at_its_homes_commit_though_main_passed_its_live_check(self):
        self.pair()
        home, here = self.home, self.here
        commit = self.moved(home)
        home.write(f"{LIVE}/{home.install.origin()}-{int(time.time()) - 60}/exit", "0\n")
        done = here.ak("standby", home.name, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.seen(), (commit, 1))
        self.updated()
        self.assertEqual(self.seen(), (commit, 1))

    def test_a_silent_home_moves_nothing(self):
        self.pair()
        self.moved(self.home)
        self.home.silence()
        self.assertRegex(self.updated(), f"does not follow {self.home.name} yet: .*did not answer")
        self.assertEqual(self.seen(), (self.first, 0))

    def test_the_update_opening_ak_starts_goes_there_too_though_the_remote_is_out_of_reach(self):
        self.pair()
        here, commit = self.here, self.moved(self.home)
        here.install.git("fetch", "-q", "origin")
        here.install.git("remote", "set-url", "origin", str(here.at / "unreachable.git"))
        here.ak(timeout=120)    # then the hop to the home's menu, which no machine here has
        deadline = time.monotonic() + 120
        while not here.install.installs() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(self.seen(), (commit, 1))


if __name__ == "__main__":
    unittest.main()
