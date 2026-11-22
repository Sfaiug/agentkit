"""A standby's pass, `ak standby HOME`, watches its home's lease, `refs/agentkit/home` on ak's
remote, first of all: it keeps one ref, `refs/seen`, in its lease's repository,
`.agentkit/tmp/lease/repo`, at a commit made there whose message is the value read, a space, and
the stamp (`wall since boot`) of the pass that first read it, a line.  A pass that reads the value
the record holds with a stamp of its own boot leaves the ref at the same commit; one that reads
another value, finds the record of another boot, or finds the ref at a blob, at a tag of the record,
at a commit whose message is not exactly that or at an object the repository lacks, a promisor
remote holding it, or the record under another name, keeps the value read with its own stamp.  One
that reads no lease, the origin holding none or unreachable, or ak's checkout having no `origin`,
leaves no record, and mended, the next keeps one with its own stamp.  Every pass exits 0, its
lease's repository holds no lease's commit after it, and the origin's refs are what they were
before it.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, a home
and a standby that is its client, whose installs share one origin, each machine's clock from
AK_NOW, a later command at a later clock, and each case builds its own.  The home's record of the
standby says `yes`, written by `ak standby --began` and `--copied` there before each firing of its
tick, which creates the lease and swaps it.  What came back is a pass's exit, the refs git reads in
the origin and in the standby's lease repository, its objects, and the message of the commit
`refs/seen` names, read through git; no output is compared.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.akinstall import _git
from fixtures.twohomes import Machines
from test_key_ak_lease_creates_a_lease import LEASE, REF, kept, objects, refs

SEEN = "refs/seen"


def now(minute, boot="acme-vm-boot-1", since=None):
    """The standby's AK_NOW `minute` minutes into the case on both clocks, or `since` seconds since
    `boot` began, as the line of the stamp a pass keeps reads it."""
    return f"{1789000000.5 + 60 * minute} {10000.25 + 60 * minute if since is None else since} " \
           f"{boot}"


def home_now(minute):
    """The home's AK_NOW `minute` minutes into the case."""
    return f"{1789000000.5 + 60 * minute} {50000.25 + 60 * minute} acme-boot-1"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AStandbyWatchesItsHomesLease(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.machines = machines
        self.home, self.standby = machines
        self.home.env["AK_NOW"] = home_now(0)
        self.standby.env["AK_NOW"] = now(0)
        self.standby.client_of(self.home)
        self.leases = set()     # each value the origin held as the lease in the case

    def fire(self, minute):
        """The home's tick at `minute`, its record of the standby saying `yes`, which leaves a
        lease on the origin it never held before in the case: that value."""
        home = self.home
        home.env["AK_NOW"] = home_now(minute)
        began = home.ak("standby", "--began")
        copied = home.ak("standby", "--copied", "acme-vm", *began.out.split(), "yes")
        self.assertEqual((began.code, copied.code), (0, 0), began.err + copied.err)
        home.tick()
        value = home.install.refs().get(REF)
        self.assertIsNotNone(value, "the home's firing left no lease")
        self.assertNotIn(value, self.leases)
        self.leases.add(value)
        return value

    def passes(self, at):
        """The standby's pass at AK_NOW `at`, which exits 0, leaves the origin's refs as they were
        and its lease's repository holding no lease's commit: what `refs/seen` names after it and
        that commit's message, None where there is no such ref."""
        origin = refs(self.home.install.bare)
        self.standby.env["AK_NOW"] = at
        done = self.standby.ak("standby", "acme-mini")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(refs(self.home.install.bare), origin)
        self.assertEqual(self.leases & objects(self.standby), set())
        repo = kept(self.standby)
        named = refs(repo).get(SEEN)
        if named is None:
            return None
        # the object itself: `cat-file commit` would read the commit a tag names as well
        self.assertEqual(_git(repo, "cat-file", "-t", named), "commit")
        commit = _git(repo, "cat-file", "commit", named, raw=True)
        return named, commit.partition(b"\n\n")[2].decode()

    def keeps(self, at, value):
        """The pass at `at`, which keeps `value` with its own stamp: the commit the ref names."""
        named, message = self.passes(at)
        self.assertEqual(message, f"{value} {at}\n")
        return named

    def leaves(self, at):
        """The pass at `at`, which leaves no record."""
        self.assertIsNone(self.passes(at))

    def watched(self):
        """The lease the home's firing at minute 0 created, which the standby's pass at minute 1
        kept."""
        created = self.fire(0)
        self.keeps(now(1), created)
        return created

    def put(self, made):
        """`refs/seen` put by the key at `made` in the standby's lease repository."""
        _git(kept(self.standby), "update-ref", SEEN, made)

    def test_with_no_lease_on_the_origin_a_pass_leaves_no_record(self):
        self.leaves(now(1))

    def test_a_pass_keeps_the_value_read_and_its_stamp_till_the_home_swaps_it(self):
        created = self.fire(0)
        first = self.keeps(now(1), created)
        self.assertEqual(self.passes(now(4)), (first, f"{created} {now(1)}\n"))
        swapped = self.fire(3)
        self.keeps(now(7), swapped)

    def test_an_unreachable_origin_leaves_no_record_and_mended_the_next_pass_keeps_one(self):
        created = self.watched()
        self.machines.break_remote("unreachable", self.standby)
        self.leaves(now(4))
        self.machines.mend_remote()
        self.keeps(now(7), created)

    def test_a_pass_of_another_boot_keeps_the_value_with_its_own_stamp(self):
        created = self.watched()
        self.keeps(now(4, "acme-vm-boot-2", since=30.25), created)

    def test_a_ref_at_a_blob_is_no_record(self):
        created = self.watched()
        self.put(_git(kept(self.standby), "hash-object", "-w", os.devnull))
        self.keeps(now(4), created)

    def test_a_ref_at_a_commit_of_another_message_is_no_record(self):
        created = self.watched()
        repo = kept(self.standby)
        tree = _git(repo, "hash-object", "-w", "-t", "tree", os.devnull)
        # the record the pass before kept, and one more line: a message read whole is no record
        self.put(_git(repo, "commit-tree", tree, "-m", f"{created} {now(1)}\nacme\n"))
        self.keeps(now(4), created)

    def test_a_ref_at_a_tag_of_the_record_is_no_record(self):
        created = self.watched()
        repo = kept(self.standby)
        _git(repo, "tag", "-a", "-m", "acme", "acme", refs(repo)[SEEN])
        self.put(refs(repo)["refs/tags/acme"])
        self.keeps(now(4), created)

    def test_the_record_under_another_name_is_none(self):
        created = self.watched()
        repo = kept(self.standby)
        # the name git reads for refs/seen where there is none
        _git(repo, "update-ref", "refs/heads/refs/seen", refs(repo)[SEEN])
        _git(repo, "update-ref", "-d", SEEN)
        self.keeps(now(4), created)

    def test_a_ref_at_an_object_the_repository_lacks_fetches_it_from_no_promisor(self):
        created = self.watched()
        repo = kept(self.standby)
        # promisors in the standby's root, where its commands find them and the test's side, whose
        # git reads the lease's repository too, finds none: a copy of the origin, holding the
        # lease's commit, and one of the lease's repository's object format holding the record the
        # pass before kept, which a pass fetching it would keep
        root = self.standby.root
        _git(root, "clone", "-q", "--bare", str(self.home.install.bare), "acme.git")
        seen = root / "seen.git"
        _git(root, "init", "-q", "--bare",
             f"--object-format={_git(repo, 'rev-parse', '--show-object-format')}", seen.name)
        tree = _git(seen, "hash-object", "-w", "-t", "tree", os.devnull)
        record = _git(seen, "commit-tree", tree, "-m", f"{created} {now(1)}\n")
        _git(seen, "update-ref", "refs/heads/main", record)
        for name in ("acme", "seen"):
            _git(repo, "config", f"remote.{name}.url", str(self.standby.at / f"{name}.git"))
            _git(repo, "config", f"remote.{name}.promisor", "true")
        # git writes a ref only at an object it holds: seen.git's, for that write alone
        done = self.standby.run("git", "-C", str(Path(self.standby.env["HOME"], LEASE, "repo")),
                                "update-ref", SEEN, record,
                                env={"GIT_ALTERNATE_OBJECT_DIRECTORIES":
                                     str(self.standby.at / seen.name / "objects")})
        self.assertEqual(done.code, 0, done.err)
        self.keeps(now(4), created)
        self.assertNotIn(record, objects(self.standby))

    def test_a_checkout_without_origin_leaves_no_record_where_one_was_kept(self):
        self.watched()
        self.standby.install.git("remote", "remove", "origin")
        self.leaves(now(4))

    def test_a_lease_removed_from_the_origin_leaves_no_record(self):
        self.watched()
        self.home.install.set_ref(REF, None)
        self.leaves(now(4))


if __name__ == "__main__":
    unittest.main()
