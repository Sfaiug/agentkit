"""The audit seat the owner closed stays closed: the week's line waits for them to open it.

Only a person opens a seat, with one exception: each week the tick opens the `audit` seat by
itself and tells it the week's largest loss.  Once the owner has stopped that seat, a tick
neither reopens nor resumes it, says once in its log that the line waits, and keeps the line
undelivered; a later tick that week stays as quiet.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, the owner closes the seat with `ak orch stop`, and
each tick runs boxed with a loopback of its own, as cron runs it; judged by what tmux holds,
what the tick printed and `state/audit.json`.  This test fails against `/bin/false`.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

HELD = ("audit: the audit seat was closed by the owner; its line about week {} waits for them "
        "to open it")


def week():
    year, number, _ = datetime.now(timezone.utc).isocalendar()
    return f"{year}-W{number:02d}"


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class OwnerClosedAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"], audit=True)
        # a collection on record from just now: one due would outlive the tick's box
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        # A session of the owner's own keeps ak's tmux server up outside the box: a seat a
        # tick opened would still be there to see once the tick has ended.
        done = home.tmux("-f", "/dev/null", "new-session", "-d", "-s", "notes", "sleep 3600")
        assert done.code == 0, done.err
        Seat(home, "audit")
        cls.weeks = {week()}
        stopped = home.ak("orch", "stop", "audit")
        assert stopped.code == 0, stopped.err
        assert home.tmux("has-session", "-t", "=audit").code != 0, "the stop left the seat"
        cls.ticks = []
        for _ in range(2):
            done = home.tick()
            sessions = home.tmux("list-sessions", "-F", "#{session_name}").out.split()
            cls.ticks.append((done, sessions, cls.audit()))
        cls.weeks.add(week())

    @classmethod
    def audit(cls):
        try:
            return json.loads((cls.home.path / ".agentkit/state/audit.json").read_text())
        except FileNotFoundError:
            return {}

    def test_a_tick_leaves_it_closed_and_says_the_week_s_line_waits_for_the_owner(self):
        done, sessions, state = self.ticks[0]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(("audit" in sessions, "notes" in sessions), (False, True), sessions)
        self.assertIn(state.get("week"), self.weeks)
        self.assertIn(HELD.format(state["week"]), done.out.splitlines(), done.out)

    def test_the_line_is_held_and_not_delivered(self):
        state = self.ticks[0][2]
        self.assertIs(state.get("held"), True, state)
        self.assertIsNone(state.get("delivered"), state)

    def test_a_later_tick_that_week_stays_quiet_and_still_opens_nothing(self):
        done, sessions, state = self.ticks[1]
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(("audit" in sessions, "notes" in sessions), (False, True), sessions)
        self.assertNotIn(HELD.format(state.get("week")), done.out.splitlines())
        self.assertEqual(state, self.ticks[0][2])


if __name__ == "__main__":
    unittest.main()
