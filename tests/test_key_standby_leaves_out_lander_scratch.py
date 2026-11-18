"""`ak standby ALIAS` leaves out each scratch checkout of the home's lander, a folder in wt whose
name begins `land-`: none crosses, and one here goes.  A checkout of another name crosses as
before.  Black-box, through tests/fixtures/twohomes.py.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

WT = ".agentkit/wt/"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class APassLeavesOutTheLandersScratch(unittest.TestCase):
    def test_no_scratch_checkout_crosses_and_one_here_goes(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        home, here = machines
        here.client_of(home)
        home.write(f"{WT}land-ab12cd34/tests/built.bin", "a check's own")
        home.write(f"{WT}landing-page-fix/main.py", "a run's checkout")
        here.write(f"{WT}land-zz99yy88/tests/built.bin", "copied before")
        done = here.ak("standby", home.name)
        self.assertEqual(done.code, 0, done.out + done.err)
        copy = here.tree()
        self.assertEqual([path for path in copy if path.startswith(f"{WT}land-")], [])
        self.assertEqual(copy[f"{WT}landing-page-fix/main.py"], b"a run's checkout")
        self.assertIn(f"{WT}land-ab12cd34/tests/built.bin", home.tree())


if __name__ == "__main__":
    unittest.main()
