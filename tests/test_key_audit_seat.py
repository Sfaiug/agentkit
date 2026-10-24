"""The first tick of a week opens the `audit` seat by itself, and its line names quality first.

The one seat ak opens without a person (AGENTS.md, Owner rules) is how ak improves itself: the
first `ak watch` of an ISO week (UTC) writes that week's board under state/audit/, keeps the line
the seat is told in state/audit.json, and opens a seat called `audit` on `[audit]`'s models, not
the defaults.  The line names the week's largest loss in the vision's order, so a week whose
runs merged in round 1 less often is a loss however much faster they merged.  A second tick that
week writes no new board and opens no second seat.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its
history seeded in ~/.agentkit/history.db as ak keeps it.  The seat's harness is a refused fake,
so its pane ends at once: the seat is judged by its tmux session and its record.
"""

from datetime import datetime, timezone
import json
import sqlite3
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home

DAY = 86400
# The tick fetches the project each seat is filed under, ak's own checkout for this one: a proxy
# nobody answers keeps it off the network, as offline.
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
AUDIT = '[audit]\norchestrator = "beta"\nworkers = ["beta"]\nreviewers = ["alpha"]\n'
LOSS = "the largest loss is product runs merged in round 1, 60% against 80% the week before"
RULE = ("Quality, then speed, then cost: a gain in speed or cost while a quality measure gets "
        "worse is no win.")


def week_of(stamp):
    year, week, _ = datetime.fromtimestamp(stamp, timezone.utc).isocalendar()
    return f"{year}-W{week:02d}"


def seed_history(home, now):
    """Ten merged runs of a project in each of the last two weeks: 8 of last week's merged in
    round 1 after 4 hours, 6 of this week's after 1 hour.  Faster, and worse."""
    database = sqlite3.connect(home.path / ".agentkit" / "history.db")
    database.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, repo TEXT, rounds_used INTEGER,"
                     " final_state TEXT, started_at REAL, finished_at REAL,"
                     " changed_lines INTEGER)")
    for weeks_ago, first_round, hours in ((0, 6, 1), (1, 8, 4)):
        ended = now - weeks_ago * 7 * DAY - 2 * DAY
        for n in range(10):
            database.execute("INSERT INTO runs VALUES (?, ?, ?, 'pass', ?, ?, 20)",
                             (f"fix-api-{weeks_ago}-{n}", "acme", 1 if n < first_round else 2,
                              ended - hours * 3600, ended))
    database.commit()
    database.close()


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AuditSeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, {"alpha": "claude", "beta": "claude"}, audit=True, extra=AUDIT)
        cls.state = home.path / ".agentkit" / "state"
        seed_history(home, time.time())
        began = time.time()
        cls.first = home.ak("watch", env=OFFLINE)
        cls.weeks = {week_of(began), week_of(time.time())}
        cls.audit = cls.read("audit.json")
        cls.record = cls.read("session-audit.json")
        cls.sessions = cls.listed()
        cls.report = Path(cls.audit.get("report") or cls.state / "audit" / "missing.md")
        cls.board = cls.report.read_text() if cls.report.is_file() else ""
        cls.stamp = cls.report.stat().st_mtime_ns if cls.report.is_file() else None
        cls.second = home.ak("watch", env=OFFLINE)

    @classmethod
    def read(cls, name):
        try:
            return json.loads((cls.state / name).read_text())
        except FileNotFoundError:
            return {}

    @classmethod
    def listed(cls):
        done = cls.home.tmux("list-sessions", "-F", "#{session_id} #{session_name} #{@ak_orch}")
        return [line.split(" ") for line in done.out.splitlines()]

    def test_the_tick_opens_a_seat_called_audit_marked_as_ak_opens_seats(self):
        self.assertEqual(self.first.code, 0, self.first.out + self.first.err)
        self.assertEqual([name for _id, name, _mark in self.sessions], ["audit"])
        self.assertEqual(self.sessions[0][2], "1")
        shown = self.home.tmux("show-environment", "-t", "=audit:", "AGENTKIT_SESSION")
        self.assertEqual(shown.out, "AGENTKIT_SESSION=audit\n", shown.err)

    def test_the_seat_takes_the_audit_setting_s_models_not_the_defaults(self):
        self.assertEqual((self.record.get("orchestrator"), self.record.get("workers"),
                          self.record.get("reviewers")), ("beta", ["beta"], ["alpha"]))

    def test_the_week_s_board_is_written_and_its_line_kept_until_it_is_delivered(self):
        self.assertIn(self.audit.get("week"), self.weeks)
        week = self.audit["week"]
        self.assertEqual(self.report, self.state / "audit" / f"{week}.md")
        self.assertTrue(self.board.startswith(f"# ak's week {week}\n"), self.board)
        self.assertEqual((self.audit.get("typed"), self.audit.get("delivered")), (None, None))
        line = self.audit.get("line", "")
        self.assertTrue(line.startswith(f"ak's week {week}: "), line)
        self.assertIn(str(self.report), line)
        self.assertIn(RULE, line)

    def test_a_week_that_merged_faster_but_less_often_in_round_1_is_named_by_its_quality(self):
        self.assertTrue(self.audit.get("line", "").startswith(
            f"ak's week {self.audit.get('week')}: {LOSS}; "), self.audit.get("line"))
        self.assertTrue(self.board.endswith(f"\n{LOSS[0].upper()}{LOSS[1:]}.\n"), self.board)

    def test_a_second_tick_that_week_writes_no_new_board_and_opens_no_second_seat(self):
        self.assertEqual(self.second.code, 0, self.second.out + self.second.err)
        again = self.read("audit.json")
        self.assertEqual([again.get(key) for key in ("week", "report", "line")],
                         [self.audit.get(key) for key in ("week", "report", "line")])
        self.assertEqual(sorted(path.name for path in (self.state / "audit").iterdir()),
                         [self.report.name])
        self.assertEqual((self.report.read_text(), self.report.stat().st_mtime_ns),
                         (self.board, self.stamp))
        # the same session, not a new one by the same name: tmux numbers each session anew
        self.assertEqual([(id_, name) for id_, name, _mark in self.listed()],
                         [(id_, name) for id_, name, _mark in self.sessions])


if __name__ == "__main__":
    unittest.main()
