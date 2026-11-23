"""A firing of the tick, `ak watch`, on a home whose record says home goes back to a machine
(`back`) asks that machine whether it is steady (`ak standby --steady`) before it would take its
turn at ak's lease, and takes none where it says so: the lease on the origin stays as its last turn
left it, the firings going on as any till the home's proof is 10 minutes old, and standing still
from then.  The firing after that machine stops saying so takes its turn again, and two firings
later the home goes on as any.  A record saying `yes` asks nobody, a machine that does not answer
is no machine saying it is steady, and a dry run, which takes no turn, asks nobody.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, whose
installs share one origin, each machine's clock from AK_NOW, given before its first command, with
the cgroup trees and firings of tests/test_key_home_freezes_without_its_lease.py.  acme-vm is the
home: its firings at minutes 0 and 3 created its lease and wrote it anew.  acme-mini answers for
itself, acme-vm's client and steady as tests/test_key_client_answers_steady.py makes a machine.
What came back is a firing's exit, read undecoded, its freezer's file, the origin's refs, and the
calls acme-vm's ssh logged.
"""

from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import LOG, boxable
from test_key_ak_lease_creates_a_lease import REF
from test_key_client_answers_steady import STAMP, UP, at, steady
from test_key_home_freezes_without_its_lease import Firings, now


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AHomeHandsBack(Firings, unittest.TestCase):
    def pair(self, takes):
        """acme-mini, steady, and acme-vm, the home, its record of acme-mini saying `takes`; and
        the values the lease on the origin held, the last the one there."""
        mini, vm = self.machines("acme-mini", "acme-vm",
                                 now={"acme-mini": at(UP), "acme-vm": now(0)})
        steady(mini)
        held = self.home(vm, "acme-mini")
        self.record(vm, takes, "acme-mini")
        return mini, vm, held

    def swaps(self, vm, minute, held):
        """acme-vm's firing at `minute`, which leaves the origin's lease at a value it did not
        hold before."""
        self.fire(vm, now(minute))
        self.assertNotIn(vm.install.refs().get(REF), (None, *held))

    def test_a_home_takes_no_turn_while_the_machine_home_goes_back_to_is_steady(self):
        mini, vm, held = self.pair("back")
        for minute in (6, 9):
            self.runs(vm, now(minute))
            self.assertEqual(vm.install.refs(), {REF: held[-1]})
        self.paused(vm, now(15))
        self.assertEqual(vm.install.refs(), {REF: held[-1]})
        (mini.path / STAMP).unlink()
        self.swaps(vm, 18, held)
        self.runs(vm, now(24))

    def test_a_record_saying_yes_or_a_silent_machine_leaves_the_turn_taken(self):
        for takes, silent in (("yes", False), ("back", True)):
            with self.subTest(takes=takes, silent=silent):
                mini, vm, held = self.pair(takes)
                if silent:
                    mini.silence()
                self.swaps(vm, 6, held)

    def test_a_dry_run_asks_nobody(self):
        mini, vm, _ = self.pair("back")
        # acme-vm's ssh, each call logged before it goes on as it would
        (vm.bin / "ssh").rename(vm.bin / "ssh-sent")
        vm.refuse("ssh", LOG + f'exec {shlex.quote(str(vm.at / "bin" / "ssh-sent"))} "$@"\n')
        self.fire(vm, now(6), dry=True)
        self.assertEqual([call for call in vm.calls("ssh") if mini.name in call], [])
        # the log works: a firing that is no dry run asks
        self.fire(vm, now(6))
        self.assertNotEqual([call for call in vm.calls("ssh") if mini.name in call], [])


if __name__ == "__main__":
    unittest.main()
