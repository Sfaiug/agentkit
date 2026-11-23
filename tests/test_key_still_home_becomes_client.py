"""A home standing still, its firing of the tick (`ak watch`) paused, asks each machine a record
there says takes over from it whether it holds ak's lease (`ak standby --home`), and where one
answers that it does, becomes that machine's client: it first leaves there a record saying it
copies that machine and, where its own record says `yes`, that home goes back to it, `back`, or,
where it says `back`, that it takes over, `yes`; then writes `1` to the `cgroup.kill` of ak's
slice, makes the standby's folder, adds the standby's job to its crontab, its other lines kept
byte for byte, and installs itself as a client of that machine, which ends the asking: its
firings after are a client's.  A machine that answers no, or nothing, ends nothing and changes
nothing, nor does a home whose only record says `no`, standing still by a proof 20 minutes old,
as that machine is not asked; and a slice with no `cgroup.kill` gets none, the record there kept
and nothing past it done.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, whose
installs share one origin, each machine's clock from AK_NOW, given before its first command, with
the cgroup trees and firings of tests/test_key_home_freezes_without_its_lease.py, and acme-mini's
install.sh the one of the checkout `AK_BIN` names, the host's tools the refusing fakes of
tests/fixtures/installer.py.  acme-vm, its record of acme-mini saying
`yes`, fires at minute 0 and creates the lease; acme-mini keeps a record of acme-vm and a
crontab holding an owner's line and the tick's.  What came back is a firing's exit, read
undecoded, and files: the crontab's bytes, the records, the record of a server and the slice's.
"""

from pathlib import Path
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import boxable
from fixtures.akinstall import Install
from test_key_ak_lease_creates_a_lease import REF, kept
from test_key_home_creates_a_lease import RECORDS
from test_key_home_freezes_without_its_lease import SLICE, Firings, named, now

KILL = SLICE / "cgroup.kill"     # in a machine's cgroup tree
SERVER = Path(".agentkit/state/server")
STANDBY = Path(".agentkit/tmp/standby")
TABLE = b"0 4 * * * acme-backup\n*/3 * * * * ak watch # agentkit watch\n"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AStillHomeBecomesAClient(Firings, unittest.TestCase):
    def pair(self, takes="yes", kill=True):
        """The machines acme-mini, keeping a record of acme-vm saying `takes` and, where `kill`,
        an empty `cgroup.kill` in its slice; and acme-vm, which fired at minute 0 and created the
        lease."""
        machines = self.machines("acme-mini", "acme-vm")
        mini, vm = machines
        for machine in machines:
            machine.env["AK_NOW"] = now(0)
        vm.write(RECORDS / "acme-mini", f"{now(0)}\nyes\n")
        self.runs(vm, now(0))
        self.assertIn(REF, vm.install.refs())
        self.record(mini, takes)
        if kill:
            (mini.root / "cgroups" / KILL).write_bytes(b"")
        shutil.copy(installer.INSTALL, mini.install.path / "install.sh")
        installer.prepare(mini)
        (mini.bin / "hostname").unlink()    # the machine's own, which names it
        (mini.root / "crontab").write_bytes(TABLE)
        return machines

    def records(self, machine):
        return {path.name: path.read_bytes() for path in (machine.path / RECORDS).iterdir()}

    def kill(self, machine):
        """What `machine`'s `cgroup.kill` reads, None where it is not there."""
        try:
            return (machine.root / "cgroups" / KILL).read_bytes()
        except FileNotFoundError:
            return None

    def table(self, machine):
        return (machine.root / "crontab").read_bytes()

    def unchanged(self, mini, vm, minute):
        """acme-mini's firing at `minute`, which exits 0 and leaves its `cgroup.kill` empty, its
        crontab as it was, no record of a server, and acme-vm's records as they were."""
        records = self.records(vm)
        self.assertEqual(self.fire(mini, now(minute))[0], 0)
        self.assertEqual(self.kill(mini), b"")
        self.assertEqual(self.table(mini), TABLE)
        self.assertFalse((mini.path / SERVER).exists())
        self.assertEqual(self.records(vm), records)

    def stepped_down(self, takes, told):
        """acme-mini, its record of acme-vm saying `takes`, standing still becomes acme-vm's
        client, leaving there a record of itself saying `told`."""
        mini, vm = self.pair(takes)
        vm.env["AK_NOW"] = now(1)
        self.paused(mini, now(1))
        self.assertEqual(self.kill(mini), b"1")
        self.assertTrue((mini.path / STANDBY).is_dir())
        self.assertEqual((mini.path / SERVER).read_text(), "acme-vm\n")
        self.assertEqual((vm.path / RECORDS / "acme-mini").read_text(), f"{now(1)}\n{told}\n")
        table, before = self.table(mini), TABLE.splitlines(keepends=True)
        lines = table.splitlines(keepends=True)
        self.assertIn(before, [lines[:at] + lines[at + 1:] for at in range(len(lines))])
        # the line added is the job's, which a pass keeps as it is
        mini.ak("standby", "acme-vm", env={"AK_NOW": now(2)}, raw=True)
        self.assertEqual(self.table(mini), table)
        self.assertEqual(self.fire(mini, now(4))[0], 0)
        self.assertEqual(self.table(mini), table)
        self.assertEqual((mini.path / SERVER).read_text(), "acme-vm\n")
        self.assertEqual(self.kill(mini), b"1")

    def test_a_home_standing_still_becomes_the_client_of_its_standby_that_is_home(self):
        self.stepped_down("yes", "back")

    def test_a_home_whose_record_says_back_tells_its_standby_it_takes_over(self):
        self.stepped_down("back", "yes")

    def test_a_standby_whose_proof_is_10_minutes_old_ends_nothing(self):
        mini, vm = self.pair()
        vm.env["AK_NOW"] = now(10)
        self.unchanged(mini, vm, 10)

    def test_a_silent_standby_ends_nothing(self):
        mini, vm = self.pair()
        vm.env["AK_NOW"] = now(1)
        vm.silence()
        self.unchanged(mini, vm, 1)

    def test_a_record_saying_no_is_not_asked(self):
        machines = self.pair("no")
        mini, vm = machines
        vm.env["AK_NOW"] = now(1)
        # a value made 20 minutes back holds acme-mini to its proof, so it stands still; its
        # origin unreachable, its turn cannot read acme-vm's lease and drop that value
        machines.break_remote("unreachable", mini)
        repo = kept(mini)
        repo.parent.mkdir(parents=True)
        Install._git(repo.parent, "init", "-q", "--bare", str(repo))
        tree = Install._git(repo, "hash-object", "-w", "-t", "tree", "/dev/null")
        Install._git(repo, "update-ref", named(-19),
                     Install._git(repo, "commit-tree", tree, "-m", "acme"))
        self.unchanged(mini, vm, 1)
        self.assertEqual(self.freezer(mini), "1")

    def test_a_slice_with_no_kill_file_gets_none_its_standby_told_it_copies_it(self):
        mini, vm = self.pair(kill=False)
        vm.env["AK_NOW"] = now(1)
        self.paused(mini, now(1))
        self.assertIsNone(self.kill(mini))
        self.assertEqual(self.table(mini), TABLE)
        self.assertFalse((mini.path / SERVER).exists())
        self.assertEqual((vm.path / RECORDS / "acme-mini").read_text(), f"{now(1)}\nback\n")


if __name__ == "__main__":
    unittest.main()
