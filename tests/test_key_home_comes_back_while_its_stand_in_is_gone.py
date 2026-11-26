"""Home comes back to the machine that stopped once the stand-in that took over from it stops too:
the legs of ak's answer to a double failure that the keys of a home that read another's lease, of
one removing a still lease and of a still home becoming a client each pin on a pair built for it
alone (tests/test_key_home_that_read_anothers_lease_stands_still.py,
test_key_home_removes_a_still_lease.py, test_key_still_home_becomes_client.py), run one after the
other on one pair, after the takeover of tests/test_key_home_goes_there_and_back.py, so that each
leaves it as the next needs it.

Black-box: the pair of that walk, built and driven as it is, the program `AK_BIN` names running on
acme-mini and acme-vm of tests/fixtures/twohomes.py.  What came back is exits, read undecoded, the
origin's refs, and files as bytes: records, the record of a server, a crontab, whose rows are its
bytes split at each LF, a file of the home's under ~/code and a freezer's file.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
import test_key_home_goes_there_and_back as walk
from test_key_still_home_becomes_client import SERVER


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class HomeComesBackWhileItsStandInIsGone(walk.Walk, unittest.TestCase):
    def test_home_comes_back_to_the_machine_that_stopped_while_its_stand_in_is_gone(self):
        mini, vm = self.stands_in()

        # 3. acme-vm stops, and acme-mini is back, on a new boot: its firings stand still, as its
        # turn read acme-vm's lease, and it watches that lease; the first 20 minutes after the
        # first removes it, the next creates the lease, and acme-mini is the home again
        vm.silence()
        mini.answer()
        for minute in range(33, 33 + 20, 3):
            self.paused(mini, self.clock(mini, minute))
            self.stays()
            self.assertEqual(self.says(mini, "--home", minute), 1)
            self.assertFalse((mini.path / SERVER).exists())
        self.paused(mini, self.clock(mini, 54))
        self.assertEqual(mini.install.refs(), {})
        self.runs(mini, self.clock(mini, 57))
        self.swapped()
        self.assertEqual(self.says(mini, "--home", 57), 0)
        self.runs(mini, self.clock(mini, 60))
        self.swapped()

        # 4. acme-vm is back, and its firing, as its turn read acme-mini's lease, leaves it
        # acme-mini's client, which copies acme-mini; acme-mini's one record is acme-vm's, saying
        # `yes`, and acme-mini runs as any home, its firings swapping the lease
        vm.answer()
        self.paused(vm, self.clock(vm, 63))
        self.stays()
        self.assertEqual((vm.path / SERVER).read_bytes(), b"acme-mini\n")
        self.assertEqual(self.says(vm, "--home", 63), 1)
        self.assertEqual(self.records(mini),
                         {"acme-vm": f"{self.clock(mini, 63)}\nyes\n".encode()})
        self.copies(vm, mini, 63)
        for minute in (66, 69):
            self.runs(mini, self.clock(mini, minute))
            self.swapped()


if __name__ == "__main__":
    unittest.main()
