"""A machine holds the lease it created, `refs/agentkit/home` on ak's remote: each later `ak lease`
there swaps in a value the lease never held, so a standby watching it sees it change.  The value is
made and kept as the create's is (tests/test_key_ak_lease_creates_a_lease.py): a commit of the
empty tree, no parent, ak's name and dates, under `refs/made/` named for the turn's stamp, and what
is kept shrinks to the value the turn found and its own.  A lease is the machine's own where its
lease's repository holds the commit, the ref of it kept or not; another machine's, there before the
read or put there between the read and the push, is left and no object written.  An unreachable
origin writes none and keeps what was kept; a push whose answer is lost is the lease the next turn
swaps from.  A turn while another holds the lease's folder, `.agentkit/tmp/lease`, locked ends
there: it leaves the origin, the folder and what is in it as they were, and the next turn takes
its own.  A turn prints nothing and exits 0, and ~/agentkit/.git is left byte for byte.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, whose
installs share one origin, each machine's clock from AK_NOW, a later turn at a later clock, and
each case builds its own machines.  What came back is the refs git reads in the origin and in each
lease's repository, that repository's objects and `config` file, and what the lease's folder holds.
"""

import contextlib
import fcntl
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.akinstall import _git
from fixtures.twohomes import Machines
from test_key_ak_lease_creates_a_lease import (LEASE, REF, STAMPED, kept, lease, made, objects,
                                               refs)


def now(turn):
    """AK_NOW of a machine's `turn`th turn, from 0: a minute after the one before."""
    return f"{1789000000.5 + 60 * turn} {10000.25 + 60 * turn} acme-boot-1"


def named(turn):
    """The ref under refs/made/ named for the stamp of the `turn`th turn."""
    return "refs/made/" + now(turn).replace(" ", "_")


@contextlib.contextmanager
def under_way(machine):
    """A turn under way on `machine`, as the test's side sees one: an exclusive lock on its lease's
    folder, held till the block ends."""
    folder = os.open(machine.path / LEASE, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(folder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(folder)


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AHomeHoldsALease(unittest.TestCase):
    def machines(self, *names):
        machines = Machines(*(names or ("acme-mini",)))
        self.addCleanup(machines.close)
        self.leases = set()     # each the origin held before a turn of the case
        return machines

    def turn(self, machine, turn):
        """`machine`'s `turn`th `ak lease`, which prints nothing and exits 0."""
        self.leases.add(machine.install.refs().get(REF))
        self.assertEqual(lease(machine, now=now(turn)), (0, "", ""))

    def swaps(self, machine, turn):
        """`machine`'s `turn`th turn, which finds a lease on the origin and leaves one it never held
        before in the case: the value kept under the ref named for its stamp, the empty tree, no
        parent and ak's stamp."""
        bare = machine.install.bare
        self.assertIn(REF, machine.install.refs(), "no lease to swap: a create is no swap")
        self.turn(machine, turn)
        value = machine.install.refs()[REF]
        self.assertNotIn(value, self.leases)
        self.assertEqual(made(machine).get(named(turn)), value)
        self.assertEqual(_git(bare, "cat-file", "-t", value), "commit")
        head = _git(bare, "cat-file", "commit", value).partition("\n\n")[0]
        empty = _git(bare, "hash-object", "-t", "tree", "/dev/null")
        self.assertEqual(head.splitlines(), [f"tree {empty}", *STAMPED])
        return value

    def leaves(self, machine, turn):
        """`machine`'s `turn`th turn, which leaves the origin's lease, and the refs and objects of
        `machine`'s lease's repository, as they were."""
        before = machine.install.refs(), made(machine), objects(machine)
        self.turn(machine, turn)
        self.assertEqual((machine.install.refs(), made(machine), objects(machine)), before)

    def test_each_turn_swaps_and_keeps_the_value_it_found_and_its_own(self):
        mini, = self.machines()

        def own_git():
            return {path: data for path, data in mini.tree().items()
                    if Path(path).is_relative_to("agentkit/.git")}

        before = own_git()
        self.turn(mini, 0)
        second = self.swaps(mini, 1)
        third = self.swaps(mini, 2)
        self.assertEqual(made(mini), {named(1): second, named(2): third})
        self.assertEqual(own_git(), before)

    def test_another_machines_turn_leaves_the_lease_and_the_holder_swaps_on(self):
        mini, vm = self.machines("acme-mini", "acme-vm")
        self.turn(mini, 0)
        self.leaves(vm, 0)
        self.swaps(mini, 1)

    def test_an_unreachable_origin_makes_no_value_and_mended_the_next_turn_swaps(self):
        machines = self.machines()
        mini, = machines
        self.turn(mini, 0)
        machines.break_remote("unreachable")
        self.leaves(mini, 1)
        machines.mend_remote()
        self.swaps(mini, 2)

    def test_a_push_whose_answer_is_lost_is_the_lease_the_next_turn_swaps_from(self):
        machines = self.machines()
        mini, = machines
        machines.break_remote("lost")
        self.turn(mini, 0)
        self.assertEqual(made(mini), {named(0): mini.install.refs().get(REF)})
        first = self.swaps(mini, 1)
        second = self.swaps(mini, 2)
        self.assertEqual(made(mini), {named(1): first, named(2): second})

    def test_a_value_put_there_between_the_read_and_the_push_is_left_by_the_next_turn(self):
        machines = self.machines("acme-mini", "acme-vm")
        mini, vm = machines
        self.turn(vm, 0)
        theirs = vm.install.refs()[REF]
        vm.install.set_ref(REF, None)
        self.turn(mini, 0)
        machines.break_remote("between", mini, refs={REF: theirs})
        self.turn(mini, 1)
        self.assertEqual(mini.install.refs(), {REF: theirs})
        self.leaves(mini, 2)

    def test_a_turn_while_another_is_under_way_leaves_all_and_the_next_swaps(self):
        mini, = self.machines()
        self.turn(mini, 0)
        repo = kept(mini)

        def held():
            return (mini.install.refs(), refs(repo), objects(mini),
                    (repo / "config").read_bytes())

        before = held()
        with under_way(mini):
            self.turn(mini, 1)
        self.assertEqual(held(), before)
        self.swaps(mini, 2)

    def test_a_first_turn_while_another_is_under_way_makes_nothing_and_the_next_creates(self):
        mini, = self.machines()
        folder = mini.path / LEASE
        folder.mkdir(parents=True)
        with under_way(mini):
            self.turn(mini, 0)
        self.assertEqual((mini.install.refs(), list(folder.iterdir())), ({}, []))
        self.turn(mini, 1)
        self.assertEqual(made(mini), {named(1): mini.install.refs().get(REF)})

    def test_a_value_whose_ref_is_gone_is_swapped_out(self):
        mini, = self.machines()
        self.turn(mini, 0)
        _git(kept(mini), "update-ref", "-d", named(0))
        self.swaps(mini, 1)


if __name__ == "__main__":
    unittest.main()
