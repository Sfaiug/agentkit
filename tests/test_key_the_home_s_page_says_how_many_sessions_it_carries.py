"""The home's page (`c`, Machines, `this one`) has, under `runs at once`, a row `sessions at once`
that Enter does nothing on. Its value is read as the page opens from the runs that ended in the 7
days before, as every statistic counts them: going up from the fewest sessions working at once,
the most before the first number whose time had a run waiting for its slot a tenth of it or more.
`about N`, `all N seen` where none reached a tenth, `under K` where the fewest did, and `no runs`
with none counted or no history to read.

Black-box: AK_BIN runs under a terminal in a temporary HOME. Before each visit the test puts in
history.db's `runs` rows as ak writes them, relative to now, and each visit reads the value off the
screen: a run that ends while the page is open shows on the next visit.
"""

from pathlib import Path
import os
import re
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal

HOUR, DAY = 3600, 86400
COLUMNS = ("run_id", "repo", "final_state", "session", "started_at", "finished_at",
           "slot_wait_seconds")
# Each run (session, hours from two days ago to its start, to its end, hours it waited for a slot).
# One session working 6 h, a run waiting 0.5 h of them (8%); two 2 h, 0.1 h; three 2 h, 0.3 h
# (15%).  The last is the first's session again: two sessions, it would make two wait 15% of 4 h.
ABOUT_2 = [("acme-api", 0, 10, 0), ("acme-web", 2, 6, 0.1), ("acme-docs", 3, 5, 0.3),
           ("acme-api", 7, 9, 0.5)]
# One session 19 h, waiting 1 h: the first run's wait counts as its own hour, where 99 h would
# be all 19; two and three 1 h each, no wait.
ALL_3 = [("acme-api", 0, 1, 99), ("acme-web", 2, 22, 0), ("acme-docs", 4, 6, 0),
         ("acme-cli", 4, 5, 0)]
UNDER_2 = [("acme-api", 0, 4, 0), ("acme-web", 0, 4, 1)]      # two 4 h, waiting 1 h
# Rows not counted, each of which counted alone would read a number: (final_state, repo, run).
LEFT_OUT = [("pass", "acme", ("acme-api", -146, -144, 1)),     # ended 8 days ago
            ("stopped", "acme", ("acme-api", 0, 2, 1)),
            ("unknown", "acme", ("acme-api", 3, 5, 1)),
            ("pass", "agentkit-smoke", ("acme-api", 6, 8, 1)),     # a suite's
            ("pass", "acme", (None, 9, 11, 1)),
            ("pass", "acme", ("acme-api", None, 14, 1)),
            ("running", "acme", ("acme-api", 15, None, 1)),
            ("pass", "acme", ("", 18, 20, 1)),
            ("pass", "acme", ("acme-api", 21, 23, "unavailable"))]     # text in a REAL column
WEEK = "(last 7 days)"
VALUE = re.compile(r"sessions at once (no runs in the last 7 days|.+? \(last 7 days\))")


def history(home, runs, columns=COLUMNS):
    """history.db holding `runs`, (final_state, repo, run) each, in place of any before."""
    made = home.path / ".agentkit/history.db.new"
    made.unlink(missing_ok=True)
    start = time.time() - 2 * DAY
    at = lambda hours: None if hours is None else start + hours * HOUR
    connection = sqlite3.connect(made)
    try:
        connection.execute(f"CREATE TABLE runs ({', '.join(columns)})")
        connection.executemany(
            f"INSERT INTO runs VALUES ({', '.join('?' * len(columns))})",
            [(f"20261125-1200-fix-api-{number}", repo, state, session, at(began), at(ended),
              waited if isinstance(waited, str) else waited * HOUR)[:len(columns)]
             for number, (state, repo, (session, began, ended, waited)) in enumerate(runs)])
        connection.commit()
    finally:
        connection.close()
    os.replace(made, home.path / ".agentkit/history.db")


def passed(runs):
    return [("pass", "acme", run) for run in runs]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class HomesPageSaysHowManySessionsItCarries(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakeadapter.install(self.home, claude="pass")
        self.config = akconfig.write(self.home, ["fable"])
        self.term = Terminal(self.home, "attach", "--overlay", size=(120, 40),
                             env={"NO_COLOR": "1"})
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait(lambda screen: "agentkit · config " in screen and "Machines" in screen
                       and "esc back" in screen)
        self.term.keys(*(["Down"] * 5))       # one model, then the fifth config row
        self.term.wait("› Machines")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "config · machines" in screen and "› this one" in screen
                       and "esc back" in screen)

    def visit(self):
        """`sessions at once`'s value on the home's page, opened from Machines and left again."""
        self.term.keys("Enter")
        shown = self.term.wait(lambda screen: "› runs at once" in screen
                               and VALUE.search(" ".join(screen.split())))
        self.term.keys("Escape")
        self.term.wait(lambda screen: "› this one" in screen and "runs at once" not in screen)
        return VALUE.search(" ".join(shown.split()))[1]

    def test_each_value_is_read_off_the_last_7_days_as_the_page_opens(self):
        self.assertEqual(self.visit(), "no runs in the last 7 days")        # no history at all
        history(self.home, LEFT_OUT)
        self.assertEqual(self.visit(), "no runs in the last 7 days")
        history(self.home, passed(ABOUT_2))
        self.assertEqual(self.visit(), f"about 2 · with more a run waited over a tenth of the "
                                       f"time {WEEK}")
        history(self.home, passed(ALL_3))
        self.assertEqual(self.visit(), f"all 3 seen · no run waited a tenth of the time {WEEK}")
        history(self.home, passed(UNDER_2))
        self.assertEqual(self.visit(), f"under 2 · with 2 a run waited over a tenth of the time "
                                       f"{WEEK}")
        # a history from before slot_wait_seconds counted no wait
        history(self.home, passed(ABOUT_2), COLUMNS[:-1])
        self.assertEqual(self.visit(), f"all 3 seen · no run waited a tenth of the time {WEEK}")

    def test_enter_on_the_row_does_nothing(self):
        history(self.home, passed(UNDER_2))
        before = self.config.read_bytes()
        self.term.keys("Enter")
        self.term.wait("› runs at once")
        self.term.keys("Down")
        on_row = self.term.wait("› sessions at once")
        keys = next(line for line in reversed(on_row.splitlines()) if line.strip())
        self.assertNotIn("⏎", keys)
        self.term.keys("Enter", "Up")
        shown = self.term.wait("› runs at once")
        self.assertIn("config · machines · this one", shown)
        self.assertEqual(self.config.read_bytes(), before)
        self.term.keys("Escape", "Escape", "Escape", "Escape")
        self.assertEqual(self.term.exit_code(), 0)


if __name__ == "__main__":
    unittest.main()
