"""`ak lease` puts the lease, `refs/agentkit/home`, on ak's remote where the remote holds none,
and leaves one that is there, whoever wrote it.  Its value is a commit of the empty tree, with no
parent, in ak's own name and dates, whose message no other value shares.  The machine keeps it in
a repository of the lease's own, `.agentkit/tmp/lease/repo`, under `refs/made/`, named for the
stamp `AK_NOW` held (`wall_since_boot`), before sending it.  A turn prints nothing and exits 0,
whatever the remote does: unreachable, silent or losing a push's answer, the next turn after a
mend creates the lease from the one value made.  The address is the push address of
~/agentkit's `origin`, a relative one read from that checkout; with two, or one that reads as an
option, nothing is made.  ~/agentkit/.git is left byte for byte as it was.  A stamp that is no
time makes nothing.  With any word it is a usage error, as `ak back acme` is, and takes no turn.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, whose
installs share one origin, and each case builds its own machines.  What came back is the refs
git reads in the origin and in each lease's repository; this test fails against `/bin/false`.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.akinstall import _git
from fixtures.twohomes import Machines

REF = "refs/agentkit/home"
NOW = "1789000000.5 10000.25 acme-boot-1"
MADE = "refs/made/1789000000.5_10000.25_acme-boot-1"
LEASE = Path(".agentkit/tmp/lease")
STAMPED = [f"{who} ak <ak@localhost> 946684800 +0000" for who in ("author", "committer")]
LEASES = []     # each case's lease, which no other case's is


def refs(repo):
    """Every ref the repository at `repo`, on the test's side, holds, and its value; none where
    there is no repository."""
    if not repo.exists():
        return {}
    listed = _git(repo, "for-each-ref", "--format=%(refname) %(objectname)")
    return dict(line.split(" ") for line in listed.splitlines())


def kept(machine):
    """`machine`'s lease's repository, on the test's side."""
    return machine.path / LEASE / "repo"


def made(machine):
    """The values `machine` made, by their refs under refs/made/."""
    return {ref: value for ref, value in refs(kept(machine)).items()
            if ref.startswith("refs/made/")}


def lease(machine, *words, now=NOW):
    return machine.ak("lease", *words, env={"AK_NOW": now})


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AkLeaseCreatesALease(unittest.TestCase):
    def machines(self, *names):
        machines = Machines(*names)
        self.addCleanup(machines.close)
        return machines

    def turn(self, machine, now=NOW):
        """One `ak lease` on `machine`, which prints nothing and exits 0."""
        self.assertEqual(lease(machine, now=now), (0, "", ""))

    def created(self, machine, remote=None):
        """The lease on `remote`, the origin unless named, checked as the one value `machine` made:
        the empty tree, no parent, ak's stamp, and no other case's."""
        remote = remote or machine.install.bare
        value = refs(remote).get(REF)
        self.assertEqual(made(machine), {MADE: value})
        head = _git(remote, "cat-file", "commit", value).partition("\n\n")[0]
        empty = _git(remote, "hash-object", "-t", "tree", "/dev/null")
        self.assertEqual(head.splitlines(), [f"tree {empty}", *STAMPED])
        self.assertNotIn(value, LEASES)
        LEASES.append(value)
        return value

    def leaves(self, machine):
        """One more turn on `machine`, which leaves the origin's refs and its lease's repository's
        as they were."""
        before = refs(machine.install.bare), refs(kept(machine))
        self.turn(machine)
        self.assertEqual((refs(machine.install.bare), refs(kept(machine))), before)

    def test_a_lease_is_created_once_and_the_checkout_left_as_it_was(self):
        mini, = self.machines("acme-mini")

        def own_git():
            return {path: data for path, data in mini.tree().items()
                    if Path(path).is_relative_to("agentkit/.git")}

        before = own_git()
        self.turn(mini)
        self.created(mini)
        self.assertEqual(own_git(), before)
        self.leaves(mini)

    def test_a_lease_another_machine_put_there_is_left_and_no_value_made(self):
        mini, vm = self.machines("acme-mini", "acme-vm")
        self.turn(vm)
        theirs = self.created(vm)
        self.turn(mini)
        self.assertEqual((mini.install.refs(), made(mini)), ({REF: theirs}, {}))

    def test_a_ref_whose_name_ends_as_the_leases_does_is_no_lease(self):
        mini, = self.machines("acme-mini")
        mini.install.set_ref(f"refs/heads/archive/{REF}", mini.install.origin())
        self.turn(mini)
        self.created(mini)

    def test_an_unreachable_remote_makes_no_value_till_mended(self):
        machines = self.machines("acme-mini")
        mini, = machines
        machines.break_remote("unreachable")
        self.turn(mini)
        self.assertEqual((mini.install.refs(), made(mini)), ({}, {}))
        machines.mend_remote()
        self.turn(mini)
        self.created(mini)

    def test_a_push_whose_answer_is_lost_is_the_lease_the_next_turn_leaves(self):
        machines = self.machines("acme-mini")
        mini, = machines
        machines.break_remote("lost")
        self.turn(mini)
        self.created(mini)
        self.leaves(mini)

    def test_a_silent_remote_ends_each_turn_and_the_mended_one_creates_the_lease(self):
        machines = self.machines("acme-mini")
        mini, = machines
        machines.break_remote("silent")
        for _ in range(3):
            self.turn(mini)
            self.assertTrue(mini.held.acquire(timeout=0), "a turn never reached the remote")
        self.assertEqual(mini.install.refs(), {})
        machines.mend_remote()
        self.turn(mini)
        self.created(mini)

    def test_the_lease_goes_to_origins_push_address_and_to_none_of_two_or_an_option(self):
        mini, vm, mac = self.machines("acme-mini", "acme-vm", "acme-mac")
        for machine, names in ((mini, ["mirror.git"]), (vm, ["mirror.git", "other.git"])):
            for name in names:     # beside ~/agentkit, named from it
                self.assertEqual(machine.run("git", "init", "-q", "--bare", name).code, 0)
                machine.install.git("config", "--add", "remote.origin.pushurl", f"../{name}")
        # git's options would take it for one of their own
        with (mac.install.path / ".git" / "config").open("a") as config:
            config.write('[remote "origin"]\n\tpushurl = --get-url\n')
        for machine in (mini, vm, mac):
            self.turn(machine)
        self.created(mini, mini.path / "mirror.git")
        self.assertEqual([refs(vm.path / "mirror.git"), refs(vm.path / "other.git"),
                          mini.install.refs(), made(vm), made(mac)], [{}] * 5)

    def test_a_stamp_that_is_no_time_makes_nothing(self):
        mini, = self.machines("acme-mini")
        self.turn(mini, now="acme")
        self.assertEqual((mini.install.refs(), made(mini)), ({}, {}))

    def test_a_word_is_a_usage_error_that_takes_no_turn(self):
        mini, = self.machines("acme-mini")
        back, done = mini.ak("back", "acme"), lease(mini, "acme")
        self.assertNotEqual(back.code, 0)
        self.assertEqual(done.code, back.code)
        self.assertIn("usage: ak lease\n", done.err)
        self.assertFalse((mini.path / LEASE).exists())
        self.assertEqual(mini.install.refs(), {})


if __name__ == "__main__":
    unittest.main()
