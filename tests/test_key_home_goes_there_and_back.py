"""Home goes to the stand-in when the home stops, and back once that machine is steady: the legs
that the keys of a takeover and of the way back each pin on a pair built for it alone
(tests/test_key_standby_takes_the_lease.py, test_key_standby_becomes_home.py,
test_key_still_home_becomes_client.py, test_key_client_answers_steady.py,
test_key_home_hands_back.py, test_key_home_freezes_without_its_lease.py), run one after the other
on one pair, so that each leaves it as the next needs it.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, acme-mini
and acme-vm, whose installs share one origin, each machine's clock from AK_NOW, given before its
first command, with the cgroup trees and firings of the freezing key, each machine's install.sh and
host's tools the becoming-home key's, and acme-mini's crontab the still-home key's.  A minute is
the pair's: each command at one is given both machines' clocks there, so a machine it asks reads
the same time.  What came back is exits, read undecoded, the origin's refs, and files as bytes:
records, the record of a server, crontabs, whose rows are their bytes split at each LF, and a
freezer's file.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from test_key_ak_lease_creates_a_lease import REF
from test_key_client_answers_steady import at
from test_key_home_freezes_without_its_lease import Firings, now
from test_key_standby_becomes_home import own_install
import test_key_still_home_becomes_client as stepping
from test_key_still_home_becomes_client import KILL, SERVER, TABLE

TAG = b"# agentkit standby"     # what the standby's row ends in
BOOT = 30   # the minute acme-mini's second boot begins


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class HomeGoesThereAndBack(Firings, unittest.TestCase):
    records = stepping.AStillHomeBecomesAClient.records
    table = stepping.AStillHomeBecomesAClient.table

    def clock(self, machine, minute):
        """Both machines' clocks set to `minute`, acme-mini's on its second boot from BOOT on:
        `machine`'s AK_NOW."""
        self.mini.env["AK_NOW"] = (now(minute) if minute < BOOT else
                                   at(minute, minute - BOOT, "acme-boot-2"))
        self.vm.env["AK_NOW"] = now(minute)
        return machine.env["AK_NOW"]

    def passes(self, machine, home, minute, code=0):
        """`machine`'s pass from `home` at `minute`, which exits `code`."""
        self.clock(machine, minute)
        self.assertEqual(machine.ak("standby", home.name, raw=True).code, code)

    def says(self, machine, word, minute):
        """The exit of `ak standby WORD` on `machine` at `minute`."""
        self.clock(machine, minute)
        return machine.ak("standby", word, raw=True).code

    def swapped(self):
        """The origin's lease is a value it never held before in the run."""
        value = self.mini.install.refs().get(REF)
        self.assertNotIn(value, (None, *self.held))
        self.held.append(value)

    def stays(self):
        """The origin's lease is still the one it held last."""
        self.assertEqual(self.mini.install.refs(), {REF: self.held[-1]})

    def rows(self, machine):
        return self.table(machine).split(b"\n")

    def test_home_goes_to_the_stand_in_when_the_home_stops_and_back_once_it_is_steady(self):
        machines = self.machines("acme-mini", "acme-vm",
                                 now={"acme-mini": now(0), "acme-vm": now(0)})
        self.mini, self.vm = mini, vm = machines
        for machine in machines:     # each installs itself as either, and steps down once
            own_install(machine)
            (machine.root / "cgroups" / KILL).write_bytes(b"")
        (mini.root / "crontab").write_bytes(TABLE)
        vm.client_of(mini)

        # 1. acme-mini is the home, its firings holding the lease, and acme-vm its client, whose
        # pass copies it; then acme-mini's record of acme-vm says `yes`, as a pass tells its home
        # `no` today
        self.held = list(self.home(mini))
        self.passes(vm, mini, 4)
        job, = [row for row in self.rows(vm) if row.endswith(TAG)]     # as a pass keeps it
        self.record(mini, "yes")

        # 2. acme-mini fires no more; acme-vm's pass that has read the lease unchanged for 20
        # minutes, since its pass at 4, sends its swap, and the pass after it makes it the home
        mini.silence()
        self.passes(vm, mini, 23, code=1)
        self.stays()
        self.passes(vm, mini, 24, code=1)
        self.swapped()
        self.passes(vm, mini, 27)
        self.assertEqual(self.says(vm, "--home", 27), 0)
        for minute in (27, 30):
            self.runs(vm, self.clock(vm, minute))
            self.swapped()

        # 3. acme-mini is back, on a new boot, and its firing leaves it acme-vm's client, its
        # crontab's rows kept and the standby's added; acme-vm's record of it says `back`
        mini.answer()
        self.paused(mini, self.clock(mini, 31))
        self.assertEqual((mini.path / SERVER).read_bytes(), b"acme-vm\n")
        rows = self.rows(mini)
        self.assertEqual([row for row in rows if not row.endswith(TAG)], TABLE.split(b"\n"))
        self.assertEqual(len(rows), len(TABLE.split(b"\n")) + 1)
        self.assertEqual(self.records(vm), {"acme-mini": f"{now(31)}\nback\n".encode()})

        # 4. acme-mini's passes from acme-vm end well, keeping the row step 3 added, so it is the
        # standby's; up less than half an hour it is not steady, and acme-vm's firings go on
        # swapping the lease; up half an hour at 60, its pass at 57 of this boot, it is
        table = self.table(mini)
        for minute in range(33, 60, 3):
            self.runs(vm, self.clock(vm, minute))
            self.swapped()
            self.passes(mini, vm, minute)
            self.assertEqual(self.table(mini), table)
            self.assertEqual(self.says(mini, "--steady", minute), 1)
        self.assertEqual(self.says(mini, "--steady", 60), 0)

        # 5. acme-vm's firings leave the lease as it is, and stand still once its proof, the value
        # its turn at 54 made, is 10 minutes old; acme-mini's pass that has read the lease
        # unchanged for 20 minutes, since its pass at 57, sends its swap, and the pass after it
        # makes it the home
        for minute in range(60, 77, 3):
            (self.runs if minute < 54 + 10 else self.paused)(vm, self.clock(vm, minute))
            self.stays()
            self.passes(mini, vm, minute)
            self.stays()
        self.passes(mini, vm, 77)
        self.swapped()
        self.passes(mini, vm, 80)
        self.assertEqual(self.says(mini, "--home", 80), 0)

        # 6. acme-vm's next firing leaves it acme-mini's client, its crontab holding the
        # standby's row; acme-mini's record of it says `yes`, and acme-mini runs as any home,
        # its firings swapping the lease
        self.paused(vm, self.clock(vm, 81))
        self.stays()
        self.assertEqual((vm.path / SERVER).read_bytes(), b"acme-mini\n")
        self.assertIn(job, self.rows(vm))
        self.assertEqual(self.says(vm, "--home", 81), 1)
        self.assertEqual(self.records(mini),
                         {"acme-vm": f"{self.clock(mini, 81)}\nyes\n".encode()})
        for minute in (84, 87):
            self.runs(mini, self.clock(mini, minute))
            self.swapped()


if __name__ == "__main__":
    unittest.main()
