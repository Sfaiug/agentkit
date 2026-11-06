"""A seat renamed back to an earlier name takes the verification lock held under its name with it.

One verification of a seat's plan runs at a time: it holds `state/verify-<name>.lock`, under the
name the seat goes by, from the plan's read to its write-back.  A verification that read the
seat's name before a rename and opened the lock after it leaves an empty lock under the old name,
which nobody keeps.  Renaming back there must move the held lock over it, or the next verification
takes that empty one and runs beside the first.  Here the test holds the lock as a verification of
beta, once fix-api, does; `ak orch rename beta fix-api` must leave `ak plan` in fix-api waiting
for it.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py
on a seat from tests/fixtures/akseat.py, and this test fails against `/bin/false`.
"""

import fcntl
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

STATE = ".agentkit/state"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RenameBack(unittest.TestCase):
    def test_a_verification_after_renaming_back_waits_for_the_one_holding_the_lock(self):
        home = Home()
        self.addCleanup(home.close)
        Seat(home, "beta")
        home.write(f"{STATE}/session-fix-api.json", {"renamed": "beta"})
        held = home.write(f"{STATE}/verify-beta.lock", "").open("a")
        self.addCleanup(held.close)
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        home.write(f"{STATE}/verify-fix-api.lock", "")      # the one a late verification left
        done = home.ak("orch", "rename", "beta", "fix-api")
        self.assertEqual(done.code, 0, done.err)
        listing = home.spawn("plan", env={"AGENTKIT_SESSION": "fix-api"})
        deadline = time.monotonic() + 3
        while listing.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIsNone(listing.poll(), "`ak plan` verified beside the verification holding "
                                          f"the lock: {home.log('spawn-1.err').read_text()}")
        held.close()
        self.assertEqual(listing.wait(60), 0, home.log("spawn-1.err").read_text())


if __name__ == "__main__":
    unittest.main()
