"""A firing of the tick, `ak watch`, on a home whose record says a machine takes over from it, and
whose youngest value made, the proof that it is the home, is 10 minutes old by either clock,
writes `1` to the `cgroup.freeze` of ak's slice and exits 0 before the tick's lock: a standby that
takes a lease standing still finds the home doing nothing.  A value is made only where the origin
said the lease is the home's or there is none, so an unreachable origin or another machine's lease
pauses it.  Any other firing that is no dry run and no client's writes `0` there where it reads
`1`, whoever froze it: a mended origin's next firing, one with no record or one saying `no`, one
that never made a value.  A freezer's file that is not there is not made.  No output of a firing
is compared: what a tick prints varies with the clock.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, whose
installs share one origin, each machine's clock from AK_NOW, a later firing at a later clock, and
ak's slice a folder in the cgroup tree each machine is given (AK_CGROUP_ROOT, AK_CGROUP_FILE).
Each case builds its own machines.  What came back is a firing's exit, the freezer's file, and
whether the tick's lock file, removed before each firing, is there after.
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SOCKET, boxable
from fixtures.twohomes import Machines
from test_key_ak_lease_creates_a_lease import REF, made
from test_key_home_creates_a_lease import LOCK

SERVICE = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"
SLICE = Path(SERVICE, "agentkit.slice", f"{SOCKET}.slice")     # in a machine's cgroup tree


def now(wall, since=None):
    """AK_NOW `wall` minutes into the case by the wall clock and `since`, `wall` unless named, by
    the clock since boot."""
    return f"{1789000000.5 + 60 * wall} {10000.25 + 60 * (wall if since is None else since)} " \
           "acme-boot-1"


def named(minute):
    """The ref under refs/made/ named for the stamp of a value made at `minute`."""
    return "refs/made/" + now(minute).replace(" ", "_")


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AHomeFreezesWithoutItsLease(unittest.TestCase):
    def machines(self, *names, freezer="0"):
        """Machines of these names, each in ak's user manager by its cgroup file, with ak's slice
        in its cgroup tree and its freezer's file reading `freezer`, or with no slice for None."""
        machines = Machines(*(names or ("acme-mini",)))
        self.addCleanup(machines.close)
        for machine in machines:
            (machine.root / "membership").write_text(f"0::/{SERVICE}/app.slice/acme.service\n")
            machine.env["AK_CGROUP_FILE"] = str(machine.at / "membership")
            if freezer is not None:
                (machine.root / "cgroups" / SLICE).mkdir(parents=True)
                (machine.root / "cgroups" / SLICE / "cgroup.freeze").write_text(freezer)
        return machines

    def record(self, home, takes):
        """acme-vm's record on `home`, as a pass that ended well leaves it, saying whether it
        takes over."""
        began = home.ak("standby", "--began")
        kept = home.ak("standby", "--copied", "acme-vm", *began.out.split(), takes)
        self.assertEqual((began.code, kept.code), (0, 0), began.err + kept.err)

    def freezer(self, machine):
        """What `machine`'s freezer's file reads, None where it is not there."""
        try:
            return (machine.root / "cgroups" / SLICE / "cgroup.freeze").read_text()
        except FileNotFoundError:
            return None

    def fire(self, machine, at, dry=False):
        """One firing on `machine` at AK_NOW `at`, a dry run where `dry`: its exit, its freezer's
        file, and whether the tick's lock file, removed first, is there after."""
        lock = machine.path / LOCK
        lock.unlink(missing_ok=True)
        env = {"AK_NOW": at}
        done = machine.ak("watch", "--dry-run", env=env) if dry else machine.tick(env=env)
        return done.code, self.freezer(machine), lock.exists()

    def paused(self, machine, at):
        """A firing that exits 0 before the tick's lock, its slice frozen."""
        self.assertEqual(self.fire(machine, at), (0, "1", False))

    def runs(self, machine, at, freezer="0"):
        """A firing that goes on as any: it exits 0, the tick's lock taken, its freezer's file at
        `freezer`."""
        self.assertEqual(self.fire(machine, at), (0, freezer, True))

    def home(self, home):
        """`home` with acme-vm's record saying `yes`, whose firing at minute 0 created the lease
        and whose firing at minute 3 wrote it anew, each going on as any: its last value made
        then."""
        self.record(home, "yes")
        freezer = self.freezer(home)
        self.runs(home, now(0), freezer)
        created = home.install.refs().get(REF)
        self.assertEqual(made(home), {named(0): created})
        self.runs(home, now(3), freezer)
        anew = home.install.refs().get(REF)
        self.assertNotEqual(anew, created)
        self.assertEqual(made(home), {named(0): created, named(3): anew})

    def test_an_unreachable_origin_pauses_the_home_at_10_minutes_till_it_is_mended(self):
        machines = self.machines()
        home, = machines
        self.home(home)
        machines.break_remote("unreachable")
        self.runs(home, now(12))
        self.paused(home, now(13))
        self.paused(home, now(16))
        machines.mend_remote()
        self.runs(home, now(19))

    def test_either_clock_at_10_minutes_pauses_the_home(self):
        for wall, since in ((4, 13), (13, 4)):
            with self.subTest(wall=wall, since=since):
                machines = self.machines()
                home, = machines
                self.home(home)
                machines.break_remote("unreachable")
                self.paused(home, now(wall, since))

    def test_another_machines_lease_pauses_the_home_at_10_minutes(self):
        home, vm = self.machines("acme-mini", "acme-vm")
        self.home(home)
        home.install.set_ref(REF, None)
        self.assertEqual(vm.ak("lease", env={"AK_NOW": now(4)}).code, 0)
        self.assertNotIn(home.install.refs().get(REF), (None, *made(home).values()))
        self.paused(home, now(13))

    def test_a_paused_firing_makes_no_slice(self):
        machines = self.machines(freezer=None)
        home, = machines
        self.home(home)
        machines.break_remote("unreachable")
        tree = home.root / "cgroups"
        before = sorted(tree.rglob("*"))
        self.assertEqual(self.fire(home, now(13)), (0, None, False))
        self.assertEqual(sorted(tree.rglob("*")), before)

    def test_a_home_that_never_made_a_value_runs(self):
        machines = self.machines()
        home, = machines
        self.record(home, "yes")
        machines.break_remote("unreachable")
        self.runs(home, now(0))
        self.runs(home, now(60))
        self.assertEqual(made(home), {})

    def test_a_home_whose_record_turned_to_no_runs(self):
        home, = self.machines()
        self.home(home)
        self.record(home, "no")
        self.runs(home, now(63))

    def test_a_home_with_no_record_thaws_the_slice(self):
        home, = self.machines(freezer="1")
        self.runs(home, now(0))

    def test_a_dry_run_and_a_clients_firing_leave_the_freezer_as_it_was(self):
        machines = self.machines()
        home, = machines
        self.home(home)
        machines.break_remote("unreachable")
        self.assertEqual(self.fire(home, now(13), dry=True), (0, "0", False))
        self.paused(home, now(13))
        server, client = self.machines("acme-mini", "acme-vm", freezer="1")
        client.client_of(server)
        self.assertEqual(self.fire(server, now(0), dry=True), (0, "1", False))
        self.assertEqual(self.fire(client, now(0)), (0, "1", False))


if __name__ == "__main__":
    unittest.main()
