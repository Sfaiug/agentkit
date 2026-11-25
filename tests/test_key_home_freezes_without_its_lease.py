"""A firing of the tick, `ak watch`, on a home whose oldest value kept, the proof that it is the
home, is 10 minutes old by either clock, or that keeps none where its record says a machine takes
over from it or the stamp of its last pass as a standby names a home, writes `1` to the
`cgroup.freeze` of ak's slice and exits 0 before the tick's lock: a standby that takes a lease
standing still finds the home doing nothing.  A turn that reads the
home's own lease keeps only that value and the one it makes, so an unreachable origin or one that
answers reads and refuses pushes pauses it at 10 minutes.  One that reads another machine's lease
keeps none, as one that never made a value does, so it pauses at once and at each firing after,
the origin reachable or not; one that lost its lease's folder reads its own lease as another's.
A home keeping a value takes its turns and pauses by that proof whatever its records say: one whose
record turned to `no`, or went, does as one whose record says `yes`.  Any other firing that is no
dry run and no client's writes `0` there where it reads `1`, whoever froze it: a mended origin's
second firing, its first having swapped, the firing that makes a home's first value, one with
neither record nor stamp keeping no value, whose origin holds no lease.  A freezer's file that is
not there is not made.  No output of a firing is compared: what a tick prints varies with the
clock.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, whose
installs share one origin, each machine's clock from AK_NOW, a later firing at a later clock, and
ak's slice a folder in the cgroup tree each machine is given (AK_CGROUP_ROOT, AK_CGROUP_FILE).
Each case builds its own machines and writes and removes a home's record by hand, as
`ak standby --copied` leaves one.  What came back is a firing's exit, the freezer's file, and
whether the tick's lock file, removed before each firing, is there after.
"""

import os
from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SOCKET, boxable
from fixtures.twohomes import Machines
from test_key_ak_lease_creates_a_lease import LEASE, REF, made
from test_key_home_creates_a_lease import LOCK, RECORDS

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


class Firings:
    """A key's machines, a home's record on them and its firings, for a TestCase."""

    def machines(self, *names, freezer=b"0", now=None):
        """Machines of these names, each in ak's user manager by its cgroup file, with ak's slice
        in its cgroup tree and its freezer's file reading `freezer`, or with no slice for None,
        and its clocks where `now` names them."""
        machines = Machines(*(names or ("acme-mini",)), now=now)
        self.addCleanup(machines.close)
        for machine in machines:
            (machine.root / "membership").write_text(f"0::/{SERVICE}/app.slice/acme.service\n")
            machine.env["AK_CGROUP_FILE"] = str(machine.at / "membership")
            if freezer is not None:
                (machine.root / "cgroups" / SLICE).mkdir(parents=True)
                (machine.root / "cgroups" / SLICE / "cgroup.freeze").write_bytes(freezer)
        return machines

    def record(self, home, takes, machine="acme-vm"):
        """`machine`'s record on `home`, written as a pass that ended well at minute 0 leaves it:
        its stamp, and whether it takes over."""
        home.write(RECORDS / machine, f"{now(0)}\n{takes}\n")

    def freezer(self, machine):
        """What `machine`'s freezer's file reads, None where it is not there."""
        try:
            return (machine.root / "cgroups" / SLICE / "cgroup.freeze").read_bytes()
        except FileNotFoundError:
            return None

    def fire(self, machine, at, dry=False):
        """One firing on `machine` at AK_NOW `at`, a dry run where `dry`: its exit, what it printed
        left undecoded, its freezer's file, and whether the tick's lock file, removed first, is
        there after."""
        lock = machine.path / LOCK
        lock.unlink(missing_ok=True)
        env = {"AK_NOW": at}
        done = (machine.ak("watch", "--dry-run", env=env, raw=True) if dry else
                machine.tick(env=env, raw=True))
        return done.code, self.freezer(machine), lock.exists()

    def paused(self, machine, at):
        """A firing that exits 0 before the tick's lock, its slice frozen."""
        self.assertEqual(self.fire(machine, at), (0, b"1", False))

    def runs(self, machine, at, freezer=b"0"):
        """A firing that goes on as any: it exits 0, the tick's lock taken, its freezer's file at
        `freezer`."""
        self.assertEqual(self.fire(machine, at), (0, freezer, True))

    def home(self, home, machine="acme-vm"):
        """`home` with `machine`'s record saying `yes`, none for None, whose firing at minute 0
        created the lease and whose firing at minute 3 wrote it anew, each going on as any: the
        values of both kept, and returned, and the lease on the origin the one of minute 3."""
        if machine:
            self.record(home, "yes", machine)
        freezer = self.freezer(home)
        self.runs(home, now(0), freezer)
        created = home.install.refs().get(REF)
        self.assertEqual(made(home), {named(0): created})
        self.runs(home, now(3), freezer)
        anew = home.install.refs().get(REF)
        self.assertNotEqual(anew, created)
        self.assertEqual(made(home), {named(0): created, named(3): anew})
        return created, anew


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AHomeFreezesWithoutItsLease(Firings, unittest.TestCase):
    def unreachable(self, machines, home, since, older, newer):
        """`home`, keeping `older`, made at minute `since`, and `newer`, made 3 minutes on and the
        lease on the origin, with the origin unreachable: its firings run till that proof is 10
        minutes old and are paused from then, the origin mended too, till the firing that swapped
        in a value from `newer` is paused for the last time; the one after runs."""
        machines.break_remote("unreachable")
        self.runs(home, now(since + 9))
        self.paused(home, now(since + 10))
        self.paused(home, now(since + 13))
        machines.mend_remote()
        self.paused(home, now(since + 16))
        swapped = made(home).get(named(since + 16))
        self.assertNotIn(swapped, (older, newer))
        self.assertEqual(home.install.refs(), {REF: swapped})
        self.assertEqual(made(home), {named(since + 3): newer, named(since + 16): swapped})
        self.runs(home, now(since + 19))

    def test_an_origin_refusing_every_push_pauses_the_home_at_10_minutes(self):
        home, = self.machines()
        created, anew = self.home(home)
        refuse = home.install.bare / "hooks" / "pre-receive"
        refuse.write_text("#!/bin/sh\nexit 1\n")
        refuse.chmod(0o755)
        seen = {created, anew}
        for minute in (6, 9, 12):
            self.runs(home, now(minute))
            self.assertEqual(home.install.refs(), {REF: anew})
            own = made(home).get(named(minute))
            self.assertEqual(made(home), {named(3): anew, named(minute): own})
            self.assertNotIn(own, seen)     # a value never made before
            seen.add(own)
        self.paused(home, now(13))

    def test_an_unreachable_origin_pauses_the_home_at_10_minutes_till_it_is_mended(self):
        machines = self.machines()
        home, = machines
        self.unreachable(machines, home, 0, *self.home(home))

    def test_either_clock_at_10_minutes_pauses_the_home(self):
        # each clock alone, the other held at minute 4
        for clock in (lambda minute: now(minute, 4), lambda minute: now(4, minute)):
            with self.subTest(at_10=clock(10)):
                machines = self.machines()
                home, = machines
                self.home(home)
                machines.break_remote("unreachable")
                self.runs(home, clock(9))
                self.paused(home, clock(10))
                self.paused(home, clock(13))

    def test_another_machines_lease_pauses_the_home_at_once_reachable_or_not(self):
        machines = self.machines("acme-mini", "acme-vm")
        home, vm = machines
        self.home(home)
        home.install.set_ref(REF, None)
        self.assertEqual(vm.ak("lease", env={"AK_NOW": now(4)}).code, 0)
        self.assertNotIn(home.install.refs().get(REF), (None, *made(home).values()))
        self.paused(home, now(6))
        machines.break_remote("unreachable")
        self.paused(home, now(9))

    def test_a_home_that_lost_its_lease_folder_pauses(self):
        home, = self.machines()
        _, anew = self.home(home)
        shutil.rmtree(home.path / LEASE)
        self.paused(home, now(6))
        self.paused(home, now(9))
        self.assertEqual(home.install.refs(), {REF: anew})

    def test_a_paused_firing_makes_no_slice(self):
        machines = self.machines(freezer=None)
        home, = machines
        self.home(home)
        machines.break_remote("unreachable")
        tree = home.root / "cgroups"
        before = sorted(tree.rglob("*"))
        self.assertEqual(self.fire(home, now(10)), (0, None, False))
        self.assertEqual(sorted(tree.rglob("*")), before)

    def test_a_home_that_never_made_a_value_pauses_till_a_firing_makes_one(self):
        machines = self.machines()
        home, = machines
        self.record(home, "yes")
        machines.break_remote("unreachable")
        self.paused(home, now(0))
        self.paused(home, now(60))
        self.assertEqual(made(home), {})
        machines.mend_remote()
        self.runs(home, now(63))
        self.assertEqual(made(home), {named(63): home.install.refs().get(REF)})

    def test_a_home_whose_record_turned_to_no_or_went_holds_its_lease_as_one_saying_yes(self):
        for takes in ("no", None):      # None: the record removed
            with self.subTest(takes=takes):
                machines = self.machines()
                home, = machines
                _, anew = self.home(home)
                if takes:
                    self.record(home, takes)
                else:
                    (home.path / RECORDS / "acme-vm").unlink()
                self.runs(home, now(6))
                swapped = made(home).get(named(6))
                self.assertNotIn(swapped, (None, anew))
                self.assertEqual(home.install.refs(), {REF: swapped})
                self.unreachable(machines, home, 3, anew, swapped)

    def test_a_home_with_no_record_keeping_no_value_thaws_the_slice_and_holds_no_lease(self):
        machines = self.machines(freezer=b"1")
        home, = machines
        self.runs(home, now(0))
        machines.break_remote("unreachable")
        self.runs(home, now(10))
        # no turn taken, the origin reachable or not
        self.assertEqual(home.install.refs(), {})
        self.assertFalse((home.path / LEASE).exists())

    def test_a_dry_run_and_a_clients_firing_leave_the_freezer_as_it_was(self):
        machines = self.machines("acme-mini", "acme-vm")
        home, vm = machines
        _, anew = self.home(home)
        machines.break_remote("unreachable")
        self.assertEqual(self.fire(home, now(10), dry=True), (0, b"0", False))
        self.paused(home, now(10))
        # mended, a firing here swaps the lease from `anew`, keeping a proof 7 minutes old, and
        # thaws
        machines.mend_remote()
        self.assertEqual(self.fire(home, now(10), dry=True), (0, b"1", False))
        home.client_of(vm)      # the values it made as home kept
        self.assertEqual(self.fire(home, now(10)), (0, b"1", False))
        self.assertEqual(home.install.refs(), {REF: anew})
        server, client = self.machines("acme-mini", "acme-vm", freezer=b"1")
        client.client_of(server)
        self.assertEqual(self.fire(server, now(0), dry=True), (0, b"1", False))
        self.assertEqual(self.fire(client, now(0)), (0, b"1", False))


if __name__ == "__main__":
    unittest.main()
