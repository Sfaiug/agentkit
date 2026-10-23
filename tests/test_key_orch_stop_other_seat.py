"""A seat cannot stop another seat: `ak orch stop` from inside one names the owner, changes nothing.

A seat stops only its own work, so a model's guess in one seat never ends the owner's
conversation in another (owner rules: seats never act on one another).  Run inside a seat (its
environment names it, as the seat's tmux session gives each process in it), stopping another
seat exits 2 saying whose it is, and that seat is left as it was: its session and pane still
there with nothing typed into them, its record unchanged and no stop mark on it, whether tmux
still holds it or only its record does.  A seat the owner stopped is not removed from their list
by another seat either.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, before seats of tests/fixtures/akseat.py; this test fails against
`/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

INSIDE_OTHER = {"AGENTKIT_SESSION": "other"}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class StopAnotherSeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.other = Seat(cls.home, "other")

    def state(self, name):
        path = self.home.path / ".agentkit" / "state" / name
        return json.loads(path.read_text()) if path.is_file() else None

    def refused(self, name):
        done = self.home.ak("orch", "stop", name, env=INSIDE_OTHER)
        self.assertEqual((done.code, done.out), (2, ""), done.err)
        self.assertEqual(done.err,
                         f"ak orch: owned by seat {name}; a seat stops only its own runs\n")

    def test_a_live_seat_keeps_its_session_and_pane(self):
        seat = Seat(self.home, "acme", screen="claude-prompt-pane.txt")
        self.refused("acme")
        self.assertEqual(self.home.tmux("display-message", "-p", "-t", seat.pane,
                                        "#{session_name} #{pane_dead}").out, "acme 0\n")
        self.assertEqual(seat.typed(), "")
        self.assertEqual(self.state("session-acme.json"), seat.record)
        self.assertFalse((self.state("seat-acme.json") or {}).get("closed_by_owner"))
        self.assertEqual(self.home.tmux("has-session", "-t", "=other").code, 0)

    def test_a_seat_tmux_lost_keeps_its_record_unmarked(self):
        seat = Seat(self.home, "fix-api", alive=False)
        self.refused("fix-api")
        self.assertEqual(self.state("session-fix-api.json"), seat.record)
        self.assertFalse((self.state("seat-fix-api.json") or {}).get("closed_by_owner"))
        self.assertNotEqual(self.home.tmux("has-session", "-t", "=fix-api").code, 0)

    def test_a_seat_the_owner_stopped_stays_on_their_list(self):
        seat = Seat(self.home, "beta")
        # Outside every seat it is the owner's stop, which ends the session and keeps the seat.
        done = self.home.ak("orch", "stop", "beta")
        self.assertEqual(done.code, 0, done.err)
        mark = self.state("seat-beta.json")
        self.assertTrue(mark["closed_by_owner"])
        self.refused("beta")
        self.assertEqual(self.state("session-beta.json"), seat.record)
        self.assertEqual(self.state("seat-beta.json"), mark)


if __name__ == "__main__":
    unittest.main()
