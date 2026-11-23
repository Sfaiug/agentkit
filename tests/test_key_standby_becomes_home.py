"""A standby's pass that finds the lease on ak's remote is its own, `refs/agentkit/home` at a
value a ref under `refs/made/` in its lease's repository names, as its swap the origin took leaves
it (tests/test_key_standby_takes_the_lease.py), copies nothing and runs `install.sh --server` of
~/agentkit, exiting what that exited.  The install adds the tick's row to
the crontab, ending in `# agentkit watch`, the other rows kept byte for byte, and only then
removes the record of a server, so the machine is a home: it holds the lease by its own word
(`ak standby --home`), and its tick swaps the lease.  An install that exits 1, or a crontab that
writes no table, leaves the record of a server and the crontab as they were, and the pass after
it, mended, does what the first would have.  A pass that finds the home's lease copies the home
and leaves both as they were.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, a home,
acme-mini, and its standby, acme-vm, built and fired as the takeover key builds and fires them,
each case its own and each machine's clock from AK_NOW.  acme-vm's install.sh is the checkout's
own, the host's tools the fakes of tests/fixtures/installer.py, its home the account's own and its
`hostname` the machine's, and its crontab holds an owner's row before its first pass.  What came
back is a pass's exit, read undecoded, `ak standby --home`'s exit, the origin's lease, and files:
the crontab and the record of a server as bytes, and a file of the home's under ~/code.  A
crontab's rows are what its bytes split into at each LF.  No output is compared.
"""

import os
from pathlib import Path
import shlex
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import boxable
from test_key_ak_lease_creates_a_lease import REF
import test_key_standby_takes_the_lease as taking
from test_key_standby_watches_its_homes_lease import now
from test_key_still_home_becomes_client import SERVER

TICK = b"# agentkit watch"      # what the tick's row ends in
OWNER = b"0 4 * * * acme-backup\n"
NOTES = "code/notes"        # a file of the home's, which a pass copies
# a crontab that reads the table it keeps and refuses, writing nothing, every table it is given
REFUSING = '#!/bin/sh\n[ "$1" = -l ] && exec cat {table}\nexit 1\n'


def own_install(machine):
    """`machine`'s install.sh the checkout's own, the host's tools the fakes of
    tests/fixtures/installer.py, its home the account's own and its `hostname` the machine's."""
    shutil.copy(installer.INSTALL, machine.install.path / "install.sh")
    installer.prepare(machine)
    installer.own_home(machine)
    (machine.bin / "hostname").unlink()     # the machine's own, which names it


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AStandbyBecomesHome(unittest.TestCase):
    # each firing of the home, the takeover key's own
    fire = taking.AStandbyTakesTheLease.fire

    def setUp(self):
        taking.AStandbyTakesTheLease.setUp(self)     # the machines, the takeover key's own
        standby = self.standby
        own_install(standby)
        (standby.root / "crontab").write_bytes(OWNER)
        self.home.write(NOTES, "notes\n")
        self.read = set()       # each value the key read as the origin's lease

    def lease(self):
        """The origin's lease now."""
        value = self.home.install.refs().get(REF)
        self.read.add(value)
        return value

    def passes(self, minute):
        """The standby's pass at `minute`: its exit."""
        self.standby.env["AK_NOW"] = now(minute)
        code = self.standby.ak("standby", "acme-mini", raw=True).code
        self.lease()
        return code

    def kept(self):
        """The standby's record of a server, None where there is no file, and its crontab."""
        record = self.standby.path / SERVER
        return (record.read_bytes() if os.path.lexists(record) else None,
                (self.standby.root / "crontab").read_bytes())

    def notes(self):
        """What the standby's copy of the home's file reads."""
        return (self.standby.path / NOTES).read_bytes()

    def took(self, fired=False):
        """The lease the home's firing at minute 0 created, which the standby's pass at minute 1
        first read and its pass at minute 21 swapped for its own, or, `fired`, the home's firing at
        minute 20 for one of the home's; then the home's file changed: the record of a server and
        the crontab the pass at minute 21 left."""
        self.read.add(self.fire(0))
        self.assertEqual(self.passes(1), 0)
        if fired:
            self.read.add(self.fire(20))
        self.assertEqual(self.passes(21), 0)
        self.assertEqual(self.notes(), b"notes\n")
        self.home.write(NOTES, "changed\n")
        return self.kept()

    def becomes_home(self, minute, before):
        """The pass at `minute`, which exits 0 and leaves no record of a server and a crontab of
        the rows of `before`'s, each byte for byte and in their order, and one more, the tick's;
        the home's file not copied."""
        self.assertEqual(self.passes(minute), 0)
        record, table = self.kept()
        self.assertIsNone(record)
        # the rows in their order, as an assignment in a crontab holds for the rows after it
        rows = table.split(b"\n")
        self.assertIn(before[1].split(b"\n"), [rows[:at] + rows[at + 1:] for at, row in
                                                enumerate(rows) if row.endswith(TICK)], table)
        self.assertEqual(self.notes(), b"notes\n")

    def stays(self, minute, before):
        """The pass at `minute`, which leaves the record of a server and the crontab `before`, byte
        for byte, and the home's file not copied: its exit."""
        code = self.passes(minute)
        self.assertEqual(self.kept(), before)
        self.assertEqual(self.notes(), b"notes\n")
        return code

    def test_a_pass_finding_its_own_lease_installs_a_home_whose_tick_swaps_it(self):
        self.becomes_home(24, self.took())
        self.standby.env["AK_NOW"] = now(25)
        self.assertEqual(self.standby.ak("standby", "--home", raw=True).code, 0)
        self.lease()
        self.standby.env["AK_NOW"] = now(27)
        self.standby.tick(raw=True)
        after = self.home.install.refs()
        self.assertIn(REF, after, "the tick left no lease")
        self.assertNotIn(after[REF], self.read)

    def test_an_install_that_fails_fails_the_pass_and_the_next_installs_again(self):
        before = self.took()
        install = self.standby.install.path / "install.sh"
        real = install.read_bytes()
        install.write_bytes(b"#!/bin/sh\nexit 1\n")
        self.assertEqual(self.stays(24, before), 1)
        install.write_bytes(real)
        self.becomes_home(27, before)

    def test_a_crontab_refusing_the_tick_leaves_a_client_whose_next_pass_installs_again(self):
        before = self.took()
        crontab = self.standby.bin / "crontab"
        working = crontab.read_text()
        self.standby.fake("crontab", REFUSING.format(
            table=shlex.quote(str(self.standby.at / "crontab"))))
        self.stays(24, before)
        self.standby.fake("crontab", working)
        self.becomes_home(27, before)

    def test_a_pass_finding_the_homes_lease_copies_it(self):
        before = self.took(fired=True)
        self.assertEqual(self.passes(24), 0)
        self.assertEqual(self.kept(), before)
        self.assertEqual(self.notes(), b"changed\n")


if __name__ == "__main__":
    unittest.main()
