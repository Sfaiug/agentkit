"""A saved worker token says nothing about a seat's login: no seat runs on one.

`contract.unavailable` tells a harness this host does not have, which a check leaves out, from
one whose saved login is broken, which fails the check.  Claude Code's long-lived worker token
signs a turn in and never a seat, so a host holding only that token has no seat login: missing,
not broken.  A worker's question still reads a token past its year as broken.
"""

import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
ASK = ("import sys; from agentkit.contract import unavailable; "
       "why, broken = unavailable('claude', seat=sys.argv[1] == 'seat'); "
       "print(int(bool(why)), int(broken))")


class AWorkerTokenIsNoSeatLogin(unittest.TestCase):
    def asked(self, who, age_days):
        with Home() as home:
            token = home.write(".agentkit/secrets/claude_oauth_token", "acme-worker\n")
            then = time.time() - age_days * 86400
            os.utime(token, (then, then))
            done = home.run(sys.executable, "-c", ASK, who, env={"PYTHONPATH": str(REPO)})
            return done.out.split(), done.err

    def test_a_seat_beside_only_a_worker_token_has_no_login_and_no_broken_one(self):
        self.assertEqual(self.asked("seat", 100)[0], ["1", "0"])

    def test_a_worker_whose_token_is_past_its_year_has_a_broken_login(self):
        self.assertEqual(self.asked("worker", 366)[0], ["1", "1"])


if __name__ == "__main__":
    unittest.main()
