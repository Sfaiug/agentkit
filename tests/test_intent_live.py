"""An intent is live once each run its seat started for it, from the owner's first message to
the done, has ended and each that passed is live: the last of them.  It is not live while one
runs, while one that passed is not live (no merge yet, or no `health:` to prove it) or where
none passed.  The board shows the median hours from the owner's first message to live beside
those to done, and the weekly loss reads them right after.

Offline: a sandbox HOME with its own history database, a fake seat harness and run records,
git answering nothing.
"""

from contextlib import closing
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, history, menu, notify, orch, scoreboard, terminal

NOW = 1_800_000_000
HOUR = 3600


class Harness:
    name = "claude"

    def conversation(self, record, cwd):
        return "c1"

    def user_messages(self, record, cwd, conversation, *, seat=None):
        return [{"at": NOW - 10 * HOUR, "text": "words"}]


class IntentLive(Sandbox):
    def setUp(self):
        super().setUp()
        self.seats = {"fix-api": {"cwd": "/acme"}, "parser": {"cwd": "/acme"}}
        # (run, seat, started): before the message, two for it, another seat's, after the done
        self.runs = [("r-before", "fix-api", NOW - 11 * HOUR), ("r1", "fix-api", NOW - 9 * HOUR),
                     ("r2", "fix-api", NOW - 8 * HOUR), ("r-other", "parser", NOW - 8 * HOUR),
                     ("r-after", "fix-api", NOW - HOUR)]
        for target, name, value in ((orch, "seat_plugin", lambda record, **_kw: Harness()),
                                    (config, "session_records", lambda: self.seats),
                                    (menu, "run_records", lambda: [
                                        (Path(run), {"launched_session": seat, "started_at": at})
                                        for run, seat, at in self.runs]),
                                    (scoreboard, "_git", lambda *args, **kw: None),
                                    (terminal, "content_width", lambda: 400)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for run, _, at in self.runs:
            history.start_run(run, repo="acme", started_at=at)
        with notify.session_lock("fix-api") as name:
            notify._intent(name, NOW - 2 * HOUR)

    def live(self):
        return history.dones(0, NOW)[0][2]

    def test_live_is_the_last_of_its_passed_runs_once_each_has_ended(self):
        self.assertIsNone(self.live())                                   # both still run
        history.finish_run("r1", final_state="failed", finished_at=NOW - 7 * HOUR)
        history.finish_run("r2", final_state="pass", finished_at=NOW - 6 * HOUR)
        self.assertIsNone(self.live())                                   # passed, not live yet
        history.update_run("r2", live_at=NOW - 5 * HOUR)
        for run in ("r-before", "r-other", "r-after"):                  # none of them is its
            history.finish_run(run, final_state="pass", finished_at=NOW - 3 * HOUR)
        self.assertEqual(self.live(), NOW - 5 * HOUR)
        with patch.object(scoreboard.time, "time", return_value=NOW):
            self.assertEqual(scoreboard.compute(NOW)["intent"][0],
                             {"measured": 1, "hours": 8.0, "live": 1, "live_hours": 5.0})
            row = [line for line in scoreboard.render() if line.startswith("intent")][0]
        self.assertIn("1 intents measured, median 8.0 hours from the owner's first message to done; "
                      "1 live, median 5.0 hours to live", row)

    def test_an_intent_none_of_whose_runs_passed_is_not_live(self):
        for run in ("r1", "r2"):
            history.finish_run(run, final_state="failed", finished_at=NOW - 7 * HOUR)
        history.update_run("r1", live_at=NOW - 6 * HOUR)    # merged, then erred finishing
        self.assertIsNone(self.live())

    def test_a_history_from_before_done_runs_keeps_its_dones(self):
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute("DROP TABLE done_runs")
        self.assertEqual(history.dones(0, NOW), [(NOW - 2 * HOUR, NOW - 10 * HOUR, None)])


if __name__ == "__main__":
    unittest.main()
