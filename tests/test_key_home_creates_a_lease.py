"""A firing of the tick, `ak watch`, takes the turn `ak lease` takes, before the tick's lock, on a
home whose record says a machine takes over from it: one `ak standby` lists so, written there
by `ak standby --began` and `--copied HOST WALL SINCE BOOT yes`.  So the lease is on ak's remote,
`refs/agentkit/home`, the one value that home made, and is put there while another tick holds the
lock, beside a record that says `no` or a named pipe at a record's path.  A home with no record,
or only one that says `no` or whose stamp does not read, makes none and keeps no lease folder; a
dry run takes no turn, nor does a client, whose tick ends first.  An unreachable origin holds up
no tick: a home's with a record, which then has no proof that it is the home, exits 0 before the
lock, and one without takes it; mended, the home's next firing creates the lease and takes its
lock.  No output of a firing is compared: what a tick prints varies with the clock.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, whose
installs share one origin, each machine's clock from AK_NOW, and each case builds its own.
"""

import fcntl
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines
from test_key_ak_lease_creates_a_lease import LEASE, MADE, NOW, REF, made

RECORDS = Path(".agentkit/tmp/copies")      # the home's records of the machines that copy it
LOCK = Path(".agentkit/state/watch.tick.lock")


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AHomeCreatesALease(unittest.TestCase):
    def machines(self, *names):
        machines = Machines(*(names or ("acme-mini",)))
        self.addCleanup(machines.close)
        for machine in machines:
            machine.env["AK_NOW"] = NOW
        return machines

    def record(self, home, host, takes):
        """`host`'s record on `home`, as a pass that ended well leaves it: the stamp `--began`
        printed there handed back, and whether it takes over."""
        began = home.ak("standby", "--began")
        kept = home.ak("standby", "--copied", host, *began.out.split(), takes)
        self.assertEqual((began.code, kept.code), (0, 0), began.err + kept.err)

    def created(self, home):
        """The lease on the origin is the one value `home` made."""
        self.assertEqual(made(home), {MADE: home.install.refs().get(REF)})

    def none(self, machine):
        """The origin holds no lease, and `machine` no lease folder."""
        self.assertNotIn(REF, machine.install.refs())
        self.assertFalse((machine.path / LEASE).exists())

    def test_a_home_no_record_says_takes_over_from_makes_no_lease(self):
        for takes in (None, "no"):
            home, = self.machines()
            if takes:
                self.record(home, "acme-vm", takes)
            home.tick()
            self.none(home)

    def test_a_record_saying_yes_creates_the_lease_beside_one_saying_no(self):
        for records in ((("acme-vm", "yes"),), (("acme-vm", "no"), ("acme-laptop", "yes"))):
            home, = self.machines()
            for host, takes in records:
                self.record(home, host, takes)
            home.tick()
            self.created(home)

    def test_a_firing_creates_the_lease_while_another_tick_holds_the_lock(self):
        home, = self.machines()
        self.record(home, "acme-vm", "yes")
        with (home.path / LOCK).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            home.tick()
        self.created(home)

    def test_a_dry_run_takes_no_turn(self):
        home, = self.machines()
        self.record(home, "acme-vm", "yes")
        home.ak("watch", "--dry-run")
        self.none(home)

    def test_a_client_takes_no_turn(self):
        home, client = self.machines("acme-mini", "acme-vm")
        client.client_of(home)
        self.record(client, "acme-laptop", "yes")
        client.tick()
        self.none(client)

    def test_a_named_pipe_at_a_records_path_holds_up_no_firing(self):
        home, = self.machines()
        self.record(home, "acme-vm", "yes")
        os.mkfifo(home.path / RECORDS / "acme-laptop")
        home.tick()     # one that waited on the pipe would fail the run's bound
        self.created(home)

    def test_a_yes_whose_stamp_does_not_read_says_nothing(self):
        home, = self.machines()
        home.write(RECORDS / "acme-vm", "acme\nyes\n")
        home.tick()
        self.none(home)

    def test_an_unreachable_origin_holds_up_no_tick_and_mended_the_next_creates_the_lease(self):
        machines = self.machines("acme-mini", "acme-vm")
        home, other = machines
        self.record(home, "acme-laptop", "yes")
        machines.break_remote("unreachable")
        self.assertEqual(home.tick().code, 0)
        self.assertFalse((home.path / LOCK).exists())
        other.tick()
        self.assertTrue((other.path / LOCK).exists())
        machines.mend_remote()
        home.tick()
        self.created(home)
        self.assertTrue((home.path / LOCK).exists())


if __name__ == "__main__":
    unittest.main()
