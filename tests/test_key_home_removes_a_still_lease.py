"""A home standing still with no proof that it is the home, as one whose turn read another
machine's lease keeps none, watches that lease as a standby does, and removes it once it has read it
unchanged for twenty minutes: each of its firings of the tick, `ak watch`, pauses, and the first
twenty minutes or more after the first that read the value it reads sends `refs/agentkit/home`'s
deletion to the origin as a swap from that value.  Every firing before it leaves the lease as it
was, and one that reads another value watches that value anew.  The firing that removed the lease
stands still, and after it the home says it holds no lease (`ak standby --home` exits 1); the
firing after creates the lease and runs, its slice thawed, and the home says it holds the lease.
An origin refusing the removal keeps its lease and the home standing still.  A home standing still
with a proof, its own lease unchanged on an origin refusing its swaps, removes nothing.

Black-box: the program `AK_BIN` names runs on the machines and firings of
tests/test_key_home_freezes_without_its_lease.py, each case its own machine, its clock given
before its first command and its record of acme-vm, no machine there, saying `yes`, fired every
three minutes.  Another machine's lease is a commit of the origin's, which the key has the origin's
lease name, and a hook of the key's refuses pushes there.  What came back is a firing's exit, the
freezer's file, whether the tick's lock file is there after, `ak standby --home`'s exit, the refs
under `refs/agentkit/` on the origin and the values the home keeps.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.akinstall import _git
from test_key_ak_lease_creates_a_lease import REF, made
from test_key_home_freezes_without_its_lease import Firings, named, now

EVERY = "exit 1\n"      # a pre-receive hook refusing every push
# ... and one refusing each push of a value, so taking only a deletion
SWAPS = "while read old new ref; do case $new in *[!0]*) exit 1;; esac; done\n"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AHomeRemovesAStillLease(Firings, unittest.TestCase):
    def machine(self):
        """A case's acme-mini, its clock at minute 0, a home with a record saying `yes` that kept
        the values of its firings at minutes 0 and 3: the machine and the lease of minute 3."""
        home, = self.machines(now={"acme-mini": now(0)})
        return home, self.home(home)[1]

    def still(self):
        """A case's machine once another machine's value is the origin's lease: the machine and
        that value."""
        home, _ = self.machine()
        other = home.install.origin()
        home.install.set_ref(REF, other)
        return home, other

    def refuses(self, home, hook):
        """`home`'s origin with `hook` as its pre-receive hook."""
        path = home.install.bare / "hooks" / "pre-receive"
        path.write_text("#!/bin/sh\n" + hook)
        path.chmod(0o755)

    def says(self, home, minute):
        """The exit of `ak standby --home` on `home` at `minute`."""
        return home.ak("standby", "--home", env={"AK_NOW": now(minute)}).code

    def stays(self, home, minutes, value):
        """`home`'s firings at `minutes`, each paused and leaving the origin's lease at `value`."""
        for minute in minutes:
            self.paused(home, now(minute))
            self.assertEqual(home.install.refs(), {REF: value})

    def test_the_first_firing_twenty_minutes_on_removes_the_lease_and_the_next_creates_one(self):
        home, other = self.still()
        self.stays(home, range(6, 25, 3), other)
        self.paused(home, now(27))
        self.assertEqual(home.install.refs(), {})
        self.assertEqual(self.says(home, 27), 1)
        self.runs(home, now(30))
        self.assertEqual(made(home), {named(30): home.install.refs().get(REF)})
        self.assertEqual(self.says(home, 30), 0)

    def test_a_lease_replaced_is_watched_anew(self):
        home, other = self.still()
        self.stays(home, range(6, 16, 3), other)
        second = _git(home.install.bare, "commit-tree", "-p", other, "-m", "acme-vm",
                      f"{other}^{{tree}}")
        home.install.set_ref(REF, second)
        # 27 among them, twenty minutes after the first value was first read
        self.stays(home, range(18, 37, 3), second)
        self.paused(home, now(39))
        self.assertEqual(home.install.refs(), {})

    def test_an_origin_refusing_the_removal_keeps_the_lease_and_the_home_still(self):
        home, other = self.still()
        self.refuses(home, EVERY)
        for minute in range(6, 37, 3):
            self.stays(home, [minute], other)
            self.assertEqual(self.says(home, minute), 1)

    def test_a_home_standing_still_with_a_proof_removes_nothing(self):
        home, anew = self.machine()
        self.refuses(home, SWAPS)
        for minute in 6, 9, 12:
            self.runs(home, now(minute))
        # its proof 12 minutes old at 15, and the lease of minute 3 unchanged till 36
        self.stays(home, range(15, 37, 3), anew)


if __name__ == "__main__":
    unittest.main()
