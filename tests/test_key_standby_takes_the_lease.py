"""A standby's watch of its home's lease (tests/test_key_standby_watches_its_homes_lease.py) sends a
swap for the lease it has read unchanged for twenty minutes: a pass that reads the value its record
holds, first read 20 minutes before or more by whichever of the wall clock and the clock since boot
calls it younger, on the boot that read it, makes a value, keeps it under `refs/made/` in its
lease's repository, and sends it as a swap from the value read to `refs/agentkit/home` on the
origin.  One sooner by either clock, or of another boot, sends none; nor does one that reads
another value, which is watched anew from that pass, or none, the origin unreachable, after which
the next pass that reads the value watches it anew.  A swap the origin refused, another value
written there between the read and the push, or whose answer was lost, is not sent again.
`refs/seen` and every ref under `refs/made/` stay as they were.  The swap is sent whether the copy
of the home that follows ends well or not, and the home's firing after it leaves the standby's value
on the origin.  Every pass exits 0 but the one whose home is silent.

Black-box: the program `AK_BIN` names runs on the machines of tests/fixtures/twohomes.py, a home and
a standby that is its client, built and fired as the watch's key builds and fires them, each case
its own: each machine's clock from AK_NOW, and the home's record of the standby saying `yes` before
each firing of its tick.  What came back is a pass's exit, the origin's refs, and the refs git reads
in the standby's lease repository; no output is compared and no object looked at.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.akinstall import _git
from test_key_ak_lease_creates_a_lease import REF, kept, made, refs
import test_key_standby_watches_its_homes_lease as watching
from test_key_standby_watches_its_homes_lease import SEEN, now


def on(wall, since):
    """The standby's AK_NOW `wall` minutes into the case by the wall clock and `since` minutes by
    the clock since boot."""
    return " ".join((*now(wall).split()[:1], *now(since).split()[1:]))


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AStandbyTakesTheLease(unittest.TestCase):
    # the machines, and each firing of the home, the watch key's own
    setUp = watching.AStandbyWatchesItsHomesLease.setUp
    fire = watching.AStandbyWatchesItsHomesLease.fire

    def passes(self, at, code=0):
        """The standby's pass at AK_NOW `at`, which exits `code`: the origin's lease after it."""
        self.standby.env["AK_NOW"] = at
        done = self.standby.ak("standby", "acme-mini")
        self.assertEqual(done.code, code, done.err)
        return self.home.install.refs().get(REF)

    def leaves(self, at):
        """The pass at `at`, which leaves the origin's refs as they were."""
        before = refs(self.home.install.bare)
        self.passes(at)
        self.assertEqual(refs(self.home.install.bare), before)

    def takes(self, at, code=0):
        """The pass at `at`, which exits `code` and leaves the origin's lease at the standby's value,
        one no firing of the home left there: that value."""
        value = self.passes(at, code)
        self.assertIn(value, made(self.standby).values())
        self.assertNotIn(value, self.leases)
        return value

    def watched(self):
        """The lease the home's firing at minute 0 created, which the standby's pass at minute 1
        first read."""
        self.fire(0)
        self.leaves(now(1))

    def test_a_lease_read_unchanged_for_twenty_minutes_is_swapped_for_the_standbys(self):
        self.watched()
        self.leaves(now(20))
        seen = refs(kept(self.standby))[SEEN]
        taken = self.takes(now(21))
        self.assertEqual(refs(kept(self.standby))[SEEN], seen)
        self.assertEqual(self.fire(22), taken)

    def test_a_lease_the_home_swapped_is_watched_anew(self):
        self.watched()
        self.fire(10)
        self.leaves(now(22))
        self.leaves(now(41))
        self.takes(now(42))

    def test_the_swap_is_sent_whatever_the_copy_of_a_silent_home_does(self):
        self.watched()
        self.home.silence()
        self.takes(now(21), code=1)

    def test_a_value_written_between_the_read_and_the_push_stays(self):
        self.watched()
        other = self.home.install.origin()
        self.machines.break_remote("between", self.standby, refs={REF: other})
        self.assertEqual(self.passes(now(21)), other)

    def test_a_swap_whose_answer_was_lost_is_not_sent_again(self):
        self.watched()
        self.machines.break_remote("lost", self.standby)
        self.takes(now(21))
        self.machines.mend_remote()
        self.leaves(now(24))

    def test_two_hours_by_the_wall_clock_and_five_minutes_since_boot_send_no_swap(self):
        self.watched()
        self.leaves(on(121, 6))

    def test_five_minutes_by_the_wall_clock_and_two_hours_since_boot_send_no_swap(self):
        self.watched()
        self.leaves(on(6, 121))

    def test_two_hours_on_at_another_boot_send_no_swap(self):
        self.watched()
        self.leaves(now(121, "acme-vm-boot-2", since=30.25))

    def test_a_lease_read_again_after_an_unreachable_origin_is_watched_anew(self):
        self.watched()
        self.machines.break_remote("unreachable", self.standby)
        self.leaves(now(21))
        self.machines.mend_remote()
        self.leaves(now(24))
        self.leaves(now(43))
        self.takes(now(44))

    def test_a_ref_under_refs_made_stays(self):
        self.watched()
        repo = kept(self.standby)
        named = refs(repo)[SEEN]
        _git(repo, "update-ref", "refs/made/acme", named)
        self.takes(now(21))
        self.assertEqual(refs(repo).get("refs/made/acme"), named)


if __name__ == "__main__":
    unittest.main()
