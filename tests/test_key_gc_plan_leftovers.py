"""`ak run gc --dry-run` names each leftover outside runs and jobs it would take, and why.

Past its age, nobody holding it and its seat gone, the collector plans to take each family: an
ephemeral file in ~/.agentkit/tmp, a checkout no run owns, a passed one never merged, a gone
seat's file, a harness's entries naming a gone checkout, a /tmp entry, one in a repository's
TMPDIR, an entry of ak's home and an ended conversation.  Younger, held open or its seat alive,
each stays off the plan, and a dry run changes nothing.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, and this test fails against `/bin/false`.
Each dry run is boxed with a /tmp, a /var/tmp and processes of its own, which are all it judges.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable, Home
from fixtures.garbage import Leftovers

@unittest.skipUnless(boxable(), "no bwrap able to box a dry run here")
class Taken(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.leftovers = Leftovers(cls.home)
        cls.done = cls.leftovers.ak("run", "gc", "--dry-run")

    def test_it_names_each_family_in_order_and_why(self):
        self.assertEqual(self.done.code, 0, self.done.err)
        self.assertEqual(self.done.out.splitlines(), self.leftovers.expected)


@unittest.skipUnless(boxable(), "no bwrap able to box a dry run here")
class Kept(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.done = Leftovers(cls.home, kept=True).ak("run", "gc", "--dry-run")

    def test_kepter_held_open_or_its_seat_alive_each_stays_off_the_plan(self):
        self.assertEqual(self.done.code, 0, self.done.err)
        self.assertEqual(self.done.out.splitlines(), ["gc: no eligible artifacts"])


@unittest.skipUnless(boxable(), "no bwrap able to box a dry run here")
class Still(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.leftovers = Leftovers(cls.home)
        cls.before = cls.leftovers.seen()
        cls.done = cls.leftovers.ak("run", "gc", "--dry-run")

    def test_a_dry_run_changes_nothing_it_saw(self):
        self.assertEqual(self.done.code, 0, self.done.err)
        self.assertEqual(self.leftovers.seen(), self.before)


if __name__ == "__main__":
    unittest.main()
