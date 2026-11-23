"""`ak standby --home` prints nothing and exits 0 on a machine that holds ak's lease by its own
word: it is no home's client, and its proof that it is the home, the oldest value it keeps of the
lease, is under 10 minutes old; else it exits 1.  So a home whose record says a machine takes over
from it answers 0 right after the firing that created the lease and at a clock 9 minutes on, its
next firing between keeping that lease, which it read, as its proof; 1 at 10 minutes on with no
firing since; and 0 again after its next firing.  A home that fired with no record of a standby
holds no lease and answers 1, as do a client, the standby or a home made one, and a home whose
firing read another value at the origin's lease.  No answer changes a ref of the origin, and none
makes a lease's folder.  A word after `--home` is refused as `ak standby --nonsense` is.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, whose
installs share one origin, each machine's clock from AK_NOW, given before its first command; each
case builds its own, and the home's record saying `yes` is written with `ak standby --began` and
`--copied` there.  What came back is an exit, the answer's standard output, the origin's refs and
whether the lease's folder is there.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines
from test_key_ak_lease_creates_a_lease import LEASE, REF, refs
from test_key_home_freezes_without_its_lease import now


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AMachineAnswersWhetherItIsHome(unittest.TestCase):
    def machines(self, *names):
        names = names or ("acme-mini",)
        machines = Machines(*names, now=dict.fromkeys(names, now(0)))
        self.addCleanup(machines.close)
        return machines

    def home(self, *names):
        """The first of these machines, acme-mini alone where none are named, as a home whose
        record says acme-vm takes over from it and whose firing at minute 0 created the lease;
        and the rest."""
        home, *rest = self.machines(*names)
        began = home.ak("standby", "--began")
        kept = home.ak("standby", "--copied", "acme-vm", *began.out.split(), "yes")
        self.assertEqual((began.code, kept.code), (0, 0), began.err + kept.err)
        self.fire(home, 0)
        self.assertIn(REF, home.install.refs())
        return home, *rest

    def fire(self, machine, minute):
        done = machine.tick(env={"AK_NOW": now(minute)})
        self.assertEqual(done.code, 0, done.err)

    def answer(self, machine, minute=0):
        """The exit of `ak standby --home` on `machine` at `minute`, which printed nothing and
        left the origin's refs as they were."""
        before = refs(machine.install.bare)
        done = machine.ak("standby", "--home", env={"AK_NOW": now(minute)})
        self.assertEqual(done.out, "", done)
        self.assertEqual(refs(machine.install.bare), before)
        return done.code

    def test_a_home_that_fired_with_no_record_of_a_standby_holds_no_lease(self):
        home, = self.machines()
        self.fire(home, 0)
        self.assertEqual(self.answer(home), 1)
        self.assertFalse((home.path / LEASE).exists())

    def test_a_home_holds_its_lease_while_its_proof_is_under_10_minutes_old(self):
        home, = self.home()
        self.assertEqual(self.answer(home, 0), 0)
        # the tick's next firing writes the lease anew, keeping the value of minute 0, which it
        # read, as its proof, so that proof is 10 minutes old at minute 10 with no firing since;
        # the firing after keeps the value of minute 3 instead
        self.fire(home, 3)
        self.assertEqual(self.answer(home, 9), 0)
        self.assertEqual(self.answer(home, 10), 1)
        self.fire(home, 12)
        self.assertEqual(self.answer(home, 12), 0)

    def test_the_standby_its_homes_client_holds_none(self):
        home, standby = self.home("acme-mini", "acme-vm")
        standby.client_of(home)
        self.assertEqual(self.answer(standby), 1)

    def test_a_home_made_a_client_of_the_other_machine_holds_none(self):
        home, other = self.home("acme-mini", "acme-vm")
        self.assertEqual(self.answer(home), 0)
        home.client_of(other)
        self.assertEqual(self.answer(home), 1)

    def test_a_home_whose_firing_read_another_value_at_the_origins_lease_holds_none(self):
        home, = self.home()
        home.install.set_ref(REF, refs(home.install.bare)["refs/heads/main"])
        self.fire(home, 3)
        self.assertEqual(self.answer(home, 3), 1)

    def test_a_word_after_it_is_refused_as_a_flag_ak_standby_does_not_know(self):
        home, = self.home()
        self.assertEqual(self.answer(home), 0)
        refused = home.ak("standby", "--nonsense").code
        # help too, whose 0 would read as the answer
        for words in (["acme-vm"], ["--home"], ["-h"], ["--help"]):
            with self.subTest(words=words):
                self.assertEqual(home.ak("standby", "--home", *words).code, refused)


if __name__ == "__main__":
    unittest.main()
