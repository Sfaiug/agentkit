"""A seat's name is normalised once, the same way when it opens and when it is named again.

The name a person types becomes the one carried everywhere: the tmux session, the record's file
name, the menu and every message.  So it is lowercased, each run of characters other than a
letter, a digit, `_` or `-` (spaces, slashes, and the `:` and `.` tmux reads as target syntax)
becomes one dash, as do dashes in a row, none is left at either end, and it is cut to the 40
characters a phone shows whole.  A name typed later in any spelling that comes out the same
finds that same seat.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

PICKED = ("--model", "opus", "--workers", "opus")   # nothing left to ask about but the name
CONVERSATION = "5b7d9f1a-3c5e-4f7a-9b1d-3f5a7c9e1b3d"
NAMES = {
    "Acme Web!": "acme-web",
    "  Fix  API: v2.1 ": "fix-api-v2-1",
    "Beta_One/Two": "beta_one-two",
    "(Acme) -- Docs": "acme-docs",
    "c" * 45: "c" * 40,
    "d" * 39 + "-tail": "d" * 39,
}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatNameNormalised(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.code = cls.home.path / "code"
        cls.code.mkdir()

    def state(self, name):
        return self.home.path / ".agentkit" / "state" / f"session-{name}.json"

    def test_a_new_seat_is_planned_under_its_normalised_name(self):
        for typed, name in NAMES.items():
            with self.subTest(typed=typed):
                done = self.home.ak("orch", typed, *PICKED, "--dry-run", cwd=self.code)
                self.assertEqual(done.code, 0, done.err)
                self.assertIn(f"session {name} in {self.code} (new)", done.out.splitlines())
                self.assertFalse(self.state(name).exists())

    def test_the_seat_opens_under_that_name(self):
        done = self.home.ak("orch", "Beta Docs?", *PICKED, tty=True, cwd=self.code)
        self.assertEqual(done.code, 0, done.err)
        shown = self.home.tmux("display-message", "-p", "-t", "=beta-docs:",
                               "#{session_name}\t#{@ak_orch}")
        self.assertEqual(shown.out, "beta-docs\t1\n", shown.err)
        record = json.loads(self.state("beta-docs").read_text())
        self.assertEqual((record["orchestrator"], record["cwd"]), ("opus", str(self.code)))

    def test_another_spelling_of_the_name_finds_the_same_seat(self):
        seat = Seat(self.home, "fix-web", record={"conversation": CONVERSATION}, alive=False)
        done = self.home.ak("orch", " FIX  Web ", "--dry-run")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(done.out.splitlines()[0], f"orch: resuming fix-web on opus in "
                                                   f"{seat.cwd} (conversation {CONVERSATION})")


if __name__ == "__main__":
    unittest.main()
