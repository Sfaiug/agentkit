"""A plan line whose check is replaced within 14 days of its run going live is counted on the board.

A live change whose outcome had to be rewritten that soon missed its intent, however green its
tests.  `ak plan check` replaces a line's check; each run of that seat naming the line
(`runs.session` with `runs.plan_line`, its outcome and written stamp) that went live in the last
14 days is stamped once, and the board's `rewritten` row counts, in the week each went live, how
many of that week's live plan lines were rewritten.  A run recorded under a name the seat was
renamed from serves the same line; another seat's run naming a line in the same words and stamp
does not, and a run live 20 days ago is past the window.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, against
a history.db holding the live runs as their launches wrote them, read with sqlite3.
"""

import sqlite3
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig
from test_key_history_db import DATABASE, ORIGINAL
from test_key_scoreboard import ROOMY, scoreboard

DAY = 86400
SEAT = "fix-api"
# Each plan line of the seat: its outcome, its check, and how many days ago its run went live.
LINES = (("the parser works", "test -f parser.txt", 3),
         ("the cache is warm", "test -f cache.txt", 20))


class PlanRewriteCounted(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.home.env["AK_HOST_READINGS"] = ROOMY
        rig = Rig(self.home, "acme")
        self.cwd, self.now = rig.path, time.time()
        root, base = rig.git("rev-list", "--max-parents=0", "HEAD")[:12], rig.head()[:12]
        Seat(self.home, SEAT, cwd=rig.path, record={"repo": str(rig.path)}, alive=False)
        self.home.write(f".agentkit/state/plan-{SEAT}.md", "".join(
            f"- [ ] {what} · check: `{check}` · ~/code/acme#{root} · written {self.written(days)} "
            f"on {base}\n" for what, check, days in LINES))
        # the seat's runs, one recorded before it was renamed from `api`, whose pointer a rename
        # leaves; and another seat's naming a line in the same words and stamp, live the same day
        self.home.write(".agentkit/state/session-api.json", {"renamed": SEAT})
        runs = [(f"{SEAT}-{days}", SEAT, what, days) for what, _, days in LINES]
        runs += [("api-3", "api", LINES[0][0], 3), ("fix-web-3", "fix-web", LINES[0][0], 3)]
        self.db = sqlite3.connect(self.home.path / DATABASE)
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE runs (%s, plan_line TEXT, live_at REAL, changed_lines INTEGER)"
                        % ", ".join(map(" ".join, ORIGINAL)))
        self.db.executemany(
            "INSERT INTO runs (run_id, repo, session, final_state, started_at, finished_at, plan_line, "
            "live_at, changed_lines) VALUES (?, 'acme', ?, 'pass', ?, ?, ?, ?, 1)",
            [(run, seat, self.now - (days + 1) * DAY, self.now - days * DAY - 3600,
              f"{what} · written {self.written(days)}", self.now - days * DAY)
             for run, seat, what, days in runs])
        self.db.commit()

    def written(self, days):
        """The stamp of a line written the day before its run went live `days` ago."""
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.now - (days + 1) * DAY))

    def ak(self, *args):
        done = self.home.ak(*args, env={"AGENTKIT_SESSION": SEAT, "COLUMNS": "200"}, cwd=self.cwd)
        self.assertEqual(done.code, 0, done.out + done.err)
        return done.out

    def counted(self):
        """The `rewritten` row's two weeks: the last 7 days', then the 7 days' before."""
        return next((this, last) for label, this, last in scoreboard(self.ak("run", "status", "--history"))
                    if label == "rewritten")

    def stamped(self):
        return {run for run, at in self.db.execute("SELECT run_id, check_rewritten_at FROM runs") if at}

    def test_a_line_live_3_days_ago_given_a_new_check_is_counted_for_its_seat_alone(self):
        self.assertEqual(self.counted(), ("0 of 2 live plan lines rewritten within 14 days",
                                          "no plan line went live"))
        self.ak("plan", "check", "1", "test -f parser-v2.txt")
        self.assertEqual(self.stamped(), {f"{SEAT}-3", "api-3"})
        self.assertEqual(self.counted(), ("1 of 2 live plan lines rewritten within 14 days",
                                          "no plan line went live"))

    def test_a_line_live_20_days_ago_given_a_new_check_stamps_nothing(self):
        self.ak("plan", "check", "2", "test -f cache-v2.txt")
        self.assertEqual(self.stamped(), set())


if __name__ == "__main__":
    unittest.main()
