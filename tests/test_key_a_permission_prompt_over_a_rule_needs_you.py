"""A Claude seat at a permission prompt with its rule drawn under it needs you, even while the
Stop that handed background work over stands; test_a_permission_prompt_over_a_rule_reads_asking.py
says why.  Black-box: the seat's screen and its hook fact, read by `ak orch why`.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat


class PermissionOverRule(unittest.TestCase):
    def test_the_seat_needs_you(self):
        for standing in (None, "background"):
            with self.subTest(stop=standing), Home() as home:
                Seat(home, "acme", model="opus", screen="claude-permission-over-rule-pane.txt")
                if standing:
                    home.write(".agentkit/state/hook-acme.json", {
                        "session": "acme", "event": "Stop", "kind": standing, "text": "",
                        "at": time.time() - 60})
                done = home.ak("orch", "why", "acme")
                self.assertEqual(done.code, 0, done.err)
                self.assertEqual(done.out.splitlines()[0].split(), ["acme", "needs", "you"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
