"""A home that was a standby, the stamp of its last pass naming the home it copied, is held to the
proof that it is the home as one whose record says a machine takes over from it is, though it has
no record: a machine that took over has none till its old home steps down under it.  Its firing
of the tick, `ak watch`, takes a turn of the lease, which creates the lease where the origin holds
none, so it runs; and once its turn reads another machine's lease it keeps no value, so that
firing and each after write `1` to the `cgroup.freeze` of ak's slice and exit 0 before the tick's
lock, the origin reachable or not, till the origin holds no lease and a firing creates one again.
A home with no record keeping no value whose stamp is none, one whose first line is no stamp, or
one longer than the MiB any pass writes, read no further, takes no turn and runs, as one that
never was a standby.

Black-box: the program `AK_BIN` names runs on the machines and firings of
tests/test_key_home_freezes_without_its_lease.py, each case its own machine, its clock given
before its first command, with no record and its stamp written as a pass from acme-vm that ended
well at minute 0 leaves it, acme-vm being no machine there.  Another machine's lease is the commit
origin's main names, which the key has the origin's lease name.  What came back is a firing's
exit, the freezer's file, whether the tick's lock file is there after, the refs under
`refs/agentkit/` on the origin and the values the home keeps.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from test_key_ak_lease_creates_a_lease import LEASE, REF, made
from test_key_home_freezes_without_its_lease import Firings, named, now
from test_key_still_home_becomes_client import COPIED

STAMP = f"{now(0)}\nacme-vm\n"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AHomeThatReadAnothersLeaseStandsStill(Firings, unittest.TestCase):
    def standby_was(self, stamp=STAMP):
        """The machines of a case: acme-mini, its clock at minute 0, with no record and its stamp
        reading `stamp`, none for None."""
        machines = self.machines(now={"acme-mini": now(0)})
        if stamp:
            machines[0].write(COPIED, stamp)
        return machines

    def stood_still(self):
        """The machines of a case whose acme-mini kept the values of its firings at minutes 0
        and 3 till the origin's lease became another machine's: its firing at minute 6 paused,
        no value kept."""
        machines = self.standby_was()
        home, = machines
        self.home(home, None)
        home.install.set_ref(REF, home.install.origin())
        self.paused(home, now(6))
        self.assertEqual(made(home), {})
        return machines

    def test_a_home_that_read_anothers_lease_stands_still_reachable_or_not(self):
        machines = self.stood_still()
        home, = machines
        self.paused(home, now(9))
        machines.break_remote("unreachable")
        self.paused(home, now(12))
        self.assertEqual(made(home), {})
        self.assertEqual(home.install.refs(), {REF: home.install.origin()})

    def test_it_runs_once_its_firing_creates_the_lease_on_an_origin_holding_none(self):
        home, = self.stood_still()
        home.install.set_ref(REF, None)
        self.runs(home, now(9))
        self.assertEqual(made(home), {named(9): home.install.refs()[REF]})

    def test_a_home_whose_stamp_names_a_home_creates_the_lease_and_runs(self):
        home, = self.standby_was()
        self.runs(home, now(0))
        self.assertEqual(made(home), {named(0): home.install.refs()[REF]})

    def test_one_with_no_stamp_or_one_no_pass_wrote_takes_no_turn_and_runs(self):
        for stamp in None, "acme\nacme-vm\n", STAMP + "acme\n" * 2**18:
            with self.subTest(stamp=stamp and stamp[:40]):
                home, = self.standby_was(stamp)
                self.runs(home, now(0))
                self.assertEqual(home.install.refs(), {})
                self.assertFalse((home.path / LEASE).exists())


if __name__ == "__main__":
    unittest.main()
