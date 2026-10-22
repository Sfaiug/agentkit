"""A tick forgets a seat a week after tmux last saw it, or a week after the owner stopped it.

Forgetting frees the seat's name and takes its row off the menu, so it must wait the whole week:
a seat tmux lost keeps its record until a week after its last sighting, and one the owner stopped
until a week after the stop, however long before that tmux last saw it; then the record goes and
only the stop mark comes back, for a hand-back of the seat's runs to read.  A seat tmux still
holds is seen again on every tick, a dead one is kept while tmux saw its pane die within the
week, whatever its record says, and a seat whose question is unanswered is kept past it.
Black-box: the program `AK_BIN` names runs `ak watch` from outside through
tests/fixtures/akbin.py, before seats of tests/fixtures/akseat.py; this test fails against
`/bin/false`.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures import akconfig

DAY = 86400


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class SeatRetired(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        # a collection on record from just now: one due would outlive the tick's box
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        cls.started = now = time.time()

        def seen(days, **more):
            # opened long before, so only the last sighting can count
            return {"created": int(now) - 40 * DAY, "seen": now - days * DAY, **more}

        Seat(home, "acme", alive=False, record=seen(8))
        Seat(home, "beta", alive=False, record=seen(6))
        # stopped long after tmux lost them: the week runs from the stop
        cls.stopped = {"gamma": now - 8 * DAY, "delta": now - 6 * DAY}
        for name, at in cls.stopped.items():
            Seat(home, name, alive=False, record=seen(30))
            home.write(f".agentkit/state/seat-{name}.json",
                       {"session": name, "stopped_at": at, "closed_by_owner": True,
                        "word": "idle", "reason": "session closed"})
        Seat(home, "eta", alive=False, record=seen(8))
        cls.asked = home.ak("notify", "needs", "Which branch should the fix land on?",
                            "--session", "eta")
        Seat(home, "zeta", record=seen(8))
        cls.dead = Seat(home, "theta", record=seen(8, exited_since=now - 8 * DAY))
        cls.end(cls.dead)
        cls.tick = home.tick()

    @classmethod
    def end(cls, seat, bound=30):
        """End the harness in the seat's pane, which tmux keeps, dead, as it keeps a seat's."""
        done = cls.home.tmux("respawn-pane", "-k", "-t", seat.pane, "true")
        assert done.code == 0, done.err
        deadline = time.monotonic() + bound
        while cls.home.tmux("display-message", "-p", "-t", seat.pane,
                            "#{pane_dead}").out.strip() != "1":
            assert time.monotonic() < deadline, f"{seat.name}'s pane never died"
            time.sleep(0.05)

    def setUp(self):
        # a seat is kept by a tick that did its work, never by one that failed
        self.assertEqual(self.tick.code, 0, self.tick.err)

    def state(self, name):
        path = self.home.path / ".agentkit" / "state" / name
        return json.loads(path.read_text()) if path.is_file() else None

    def test_a_seat_tmux_lost_over_a_week_ago_is_forgotten(self):
        self.assertIsNone(self.state("session-acme.json"))
        self.assertIn("forgot the session acme, gone for 8d", self.tick.out.splitlines())

    def test_a_seat_tmux_lost_under_a_week_ago_is_kept(self):
        self.assertEqual(self.state("session-beta.json")["seen"], self.started - 6 * DAY)

    def test_a_seat_stopped_over_a_week_ago_is_forgotten_but_for_its_stop_mark(self):
        self.assertIsNone(self.state("session-gamma.json"))
        self.assertIn("forgot the session gamma, gone for 8d", self.tick.out.splitlines())
        self.assertEqual(self.state("seat-gamma.json"),
                         {"session": "gamma", "stopped_at": self.stopped["gamma"],
                          "closed_by_owner": True})

    def test_a_stopped_seats_week_runs_from_the_stop_not_from_its_last_sighting(self):
        self.assertEqual(self.state("session-delta.json")["seen"], self.started - 30 * DAY)
        self.assertEqual(self.state("seat-delta.json")["stopped_at"], self.stopped["delta"])

    def test_a_seat_whose_question_is_unanswered_is_kept_past_its_week(self):
        self.assertEqual(self.asked.code, 0, self.asked.err)
        self.assertEqual(self.state("session-eta.json")["seen"], self.started - 8 * DAY)

    def test_a_seat_tmux_holds_is_kept_and_seen_again(self):
        self.assertGreaterEqual(self.state("session-zeta.json")["seen"], self.started)
        self.assertEqual(self.home.tmux("has-session", "-t", "=zeta").code, 0)

    def test_a_dead_seat_is_kept_while_tmux_saw_its_pane_die_within_the_week(self):
        # its record says it exited eight days ago; tmux, which saw the pane die, says now
        self.assertIsNotNone(self.state("session-theta.json"))
        self.assertEqual(self.home.tmux("display-message", "-p", "-t", self.dead.pane,
                                        "#{pane_dead}").out, "1\n")


if __name__ == "__main__":
    unittest.main()
