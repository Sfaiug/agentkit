"""A home standing still, its firing of the tick (`ak watch`) paused, asks each machine a record
there says takes over from it, then the home the stamp of its last pass as a standby names, where
it has no such record of that name, whether it holds ak's lease (`ak standby --home`), and where
one answers that it does, one silent past AK_STANDBY_TIMEOUT answering no, becomes that machine's
client: it first leaves there a record saying it copies that machine and, where its own record says
`yes`, that home goes back to it, `back`, or, where it says `back`, that it takes over, `yes`, as
the record reads once that machine has given its stamp, which that machine's pass may write
meanwhile; then writes `1` to the `cgroup.kill` of ak's slice, makes the standby's folder, adds the
standby's job to its crontab, its other lines kept byte for byte, and installs itself as a client
of that machine, which ends the asking: its firings after are a client's.  A machine that answers
no, or nothing, ends nothing and changes nothing, nor does a home whose only record says `no`,
standing still by a proof 20 minutes old, as that machine is not asked, nor one with no record
whose stamp names no home: none, one whose first line is no stamp, or one naming what ssh would
read as an option, which asks nobody; and a slice with no `cgroup.kill` gets none, the record there
kept and nothing past it done.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, whose
installs share one origin, each machine's clock from AK_NOW, given before its first command, with
the cgroup trees and firings of tests/test_key_home_freezes_without_its_lease.py, and acme-mini's
install.sh the one of the checkout `AK_BIN` names, the host's tools the refusing fakes of
tests/fixtures/installer.py.  acme-vm, its record of acme-mini saying
`yes`, fires at minute 0 and creates the lease; acme-mini keeps a record of acme-vm, or none,
and a crontab holding an owner's line and the tick's.  What came back is a firing's exit, read
undecoded, and files: the crontab's bytes, the records, the record of a server and the slice's;
and the calls acme-mini's ssh logged.
"""

from pathlib import Path
import shlex
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import LOG, boxable
from fixtures.akinstall import FETCH, PUSH, Install
from test_key_ak_lease_creates_a_lease import REF, kept
from test_key_home_creates_a_lease import RECORDS
from test_key_home_freezes_without_its_lease import SLICE, Firings, named, now

KILL = SLICE / "cgroup.kill"     # in a machine's cgroup tree
SERVER = Path(".agentkit/state/server")
STANDBY = Path(".agentkit/tmp/standby")
COPIED = STANDBY / "copied"     # the stamp of a pass that ended well, and the home it copied
TABLE = b"0 4 * * * acme-backup\n*/3 * * * * ak watch # agentkit watch\n"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AStillHomeBecomesAClient(Firings, unittest.TestCase):
    def pair(self, takes="yes", kill=True, others=()):
        """The machines acme-mini, keeping a record of acme-vm saying `takes`, none for None,
        and, where `kill`, an empty `cgroup.kill` in its slice; acme-vm, which fired at minute 0
        and created the lease; and the machines `others` names, after them."""
        names = "acme-mini", "acme-vm", *others
        machines = self.machines(*names, now=dict.fromkeys(names, now(0)))
        mini, vm = machines[:2]
        vm.write(RECORDS / "acme-mini", f"{now(0)}\nyes\n")
        self.runs(vm, now(0))
        self.assertIn(REF, vm.install.refs())
        if takes:
            self.record(mini, takes)
        if kill:
            (mini.root / "cgroups" / KILL).write_bytes(b"")
        shutil.copy(installer.INSTALL, mini.install.path / "install.sh")
        installer.prepare(mini)
        (mini.bin / "hostname").unlink()    # the machine's own, which names it
        (mini.root / "crontab").write_bytes(TABLE)
        return machines

    def stands_still(self, machines):
        """acme-mini held to its proof, 20 minutes old: it keeps a value made then, and its
        origin unreachable, its turn cannot read acme-vm's lease and drop that value."""
        mini = machines[0]
        machines.break_remote("unreachable", mini)
        repo = kept(mini)
        repo.parent.mkdir(parents=True)
        Install._git(repo.parent, "init", "-q", "--bare", str(repo))
        tree = Install._git(repo, "hash-object", "-w", "-t", "tree", "/dev/null")
        Install._git(repo, "update-ref", named(-19),
                     Install._git(repo, "commit-tree", tree, "-m", "acme"))

    def records(self, machine):
        return {path.name: path.read_bytes() for path in (machine.path / RECORDS).iterdir()}

    def kill(self, machine):
        """What `machine`'s `cgroup.kill` reads, None where it is not there."""
        try:
            return (machine.root / "cgroups" / KILL).read_bytes()
        except FileNotFoundError:
            return None

    def stamp(self, machine):
        """What `machine`'s stamp of its last pass reads, None where it is not there."""
        try:
            return (machine.path / COPIED).read_bytes()
        except FileNotFoundError:
            return None

    def table(self, machine):
        return (machine.root / "crontab").read_bytes()

    def unchanged(self, mini, vm, minute):
        """acme-mini's firing at `minute`, which exits 0 and leaves its `cgroup.kill` empty, its
        crontab and stamp as they were, no record of a server, and acme-vm's records as they
        were."""
        records, stamp = self.records(vm), self.stamp(mini)
        self.assertEqual(self.fire(mini, now(minute))[0], 0)
        self.assertEqual(self.kill(mini), b"")
        self.assertEqual(self.table(mini), TABLE)
        self.assertFalse((mini.path / SERVER).exists())
        self.assertEqual(self.records(vm), records)
        self.assertEqual(self.stamp(mini), stamp)

    def stepped_down(self, takes, told, rewritten=None):
        """acme-mini, its record of acme-vm saying `takes`, standing still becomes acme-vm's
        client, leaving there a record of itself saying `told` and its own record of acme-vm as
        its firing found it; where `rewritten`, acme-vm, as it gives its stamp, first writes that
        record anew, dated minute 0 and saying `rewritten`, as its pass would."""
        mini, vm = self.pair(takes)
        if rewritten:
            installed = vm.path / ".local/bin/ak"
            installed.unlink()
            copied = shlex.join([".local/bin/ak", "standby", "--copied", "acme-vm",
                                 *now(0).split(), rewritten])
            installed.write_text(f"""#!/bin/sh
[ "$2" != --began ] || ssh acme-mini '"$HOME"/'{shlex.quote(copied)} >/dev/null || exit
exec {shlex.quote(vm.install.ak)} "$@"
""")
            installed.chmod(0o755)
        vm.env["AK_NOW"] = now(1)
        self.paused(mini, now(1))
        self.assertEqual((mini.path / RECORDS / "acme-vm").read_text(),
                         f"{now(0)}\n{rewritten or takes}\n")
        self.client(mini, vm, told)

    def client(self, mini, vm, told):
        """acme-mini, its firing at minute 1 done, acme-vm's client: its slice's processes ended,
        the standby's folder made, its job kept and a record of a server, and a record of it on
        acme-vm saying `told`; a pass and a firing after keep them."""
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

    def test_a_record_that_turns_to_back_as_the_standby_gives_its_stamp_tells_it_yes(self):
        # back, as acme-vm's pass tells acme-mini, acme-vm's own record of it saying `yes`
        self.stepped_down("yes", "yes", rewritten="back")

    def test_a_machine_that_takes_ssh_and_answers_nothing_leaves_the_next_asked(self):
        machines = self.pair(others=("acme-box",))
        mini, vm, box = machines
        self.record(mini, "yes", "acme-box")     # asked first, by its name
        box.hang()
        vm.env["AK_NOW"] = now(1)
        mini.env["AK_STANDBY_TIMEOUT"] = "20"
        self.paused(mini, now(1))
        del mini.env["AK_STANDBY_TIMEOUT"]
        self.client(mini, vm, "back")

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
        self.stands_still(machines)
        self.unchanged(mini, vm, 1)
        self.assertEqual(self.freezer(mini), b"1")

    def test_a_home_with_no_record_becomes_the_client_of_the_home_its_stamp_names(self):
        machines = self.pair(None)
        mini, vm = machines
        mini.write(COPIED, f"{now(0)}\nacme-vm\n")
        vm.env["AK_NOW"] = now(1)
        self.stands_still(machines)
        self.paused(mini, now(1))
        machines.mend_remote(mini)
        # no record here says `yes`, so acme-vm is told this machine takes over
        self.client(mini, vm, "yes")

    def test_a_home_its_stamp_names_answering_no_or_nothing_ends_nothing(self):
        for minute, silent in (10, False), (1, True):
            with self.subTest(minute=minute, silent=silent):
                machines = self.pair(None)
                mini, vm = machines
                mini.write(COPIED, f"{now(0)}\nacme-vm\n")
                vm.env["AK_NOW"] = now(minute)
                if silent:
                    vm.silence()
                self.stands_still(machines)
                self.unchanged(mini, vm, minute)
                self.assertEqual(self.freezer(mini), b"1")

    def asks_nobody(self, stamp):
        """acme-mini, with no record and its stamp `stamp`, none for None, standing still asks no
        machine whether it is home and changes nothing."""
        machines = self.pair(None)
        mini, vm = machines
        if stamp:
            mini.write(COPIED, stamp)
        vm.env["AK_NOW"] = now(1)
        # acme-mini's ssh, each call logged before it goes on as it would
        (mini.bin / "ssh").rename(mini.bin / "ssh-sent")
        sent = shlex.quote(str(mini.at / "bin" / "ssh-sent"))
        mini.refuse("ssh", LOG + f'exec {sent} "$@"\n')
        self.stands_still(machines)
        self.unchanged(mini, vm, 1)
        self.assertEqual(self.freezer(mini), b"1")
        # no call but git's fetch or push of the origin, its host and command, which go by ssh too
        self.assertEqual([call for call in mini.calls("ssh")
                          if tuple(call[-2:]) not in (FETCH, PUSH)], [])

    def test_no_stamp_or_one_whose_first_line_is_none_asks_nobody(self):
        for stamp in None, "acme\nacme-vm\n":
            with self.subTest(stamp=stamp):
                self.asks_nobody(stamp)

    def test_a_stamp_naming_what_ssh_reads_as_an_option_asks_nobody(self):
        self.asks_nobody(f"{now(0)}\n-V\n")

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
