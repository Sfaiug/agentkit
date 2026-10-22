"""A done measures an intent only when the seat's finished work, its plan's done lines and the
runs it launched that merged, changed since its conversation's last recorded done.  A question
the owner asks about finished work takes the seat to working and back to done: that done
measures nothing, and still bounds the next intent, which is measured from its own first
message whether the seat ticks a line itself or a run of its merges.

Offline: a sandbox HOME with its own history database, a fake seat harness and run records,
git answering nothing.
"""

from pathlib import Path
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, menu, notify, orch, plan, scoreboard, terminal

NOW = 1_800_000_000
HOUR = 3600


class Harness:
    name = "claude"

    def __init__(self):
        self.said = []

    def conversation(self, record, cwd):
        return "c1"

    def seat_token_sources(self, record):
        return None

    def user_messages(self, record, cwd, conversation, *, seat=None):
        return [{"at": at, "text": "words"} for at in self.said]


class IntentOncePerDelivery(Sandbox):
    def setUp(self):
        super().setUp()
        self.harness, self.runs = Harness(), []
        for target, name, value in ((orch, "seat_plugin", lambda record, **_kw: self.harness),
                                    (config, "session_records", lambda: {"fix-api": {"cwd": "/acme"}}),
                                    (menu, "run_records", lambda: [
                                        (Path(run), {"launched_session": "fix-api", "started_at": at,
                                                     "merged": True}) for run, at in self.runs]),
                                    (scoreboard, "_git", lambda *args, **kw: None),
                                    (terminal, "content_width", lambda: 400)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # the first request, finished by a run of the seat's that merged: four hours
        self.harness.said.append(NOW - 20 * HOUR)
        self.runs.append(("r1", NOW - 19 * HOUR))
        self.done(NOW - 16 * HOUR)
        # then a question about it, answered with nothing new finished
        self.harness.said.append(NOW - 15 * HOUR)
        self.done(NOW - 14 * HOUR)

    def done(self, at):
        with notify.session_lock("fix-api") as name:
            notify._intent(name, at)

    def intent(self):
        with patch.object(scoreboard.time, "time", return_value=NOW):
            measured = scoreboard.compute(NOW)["intent"][0]
        return measured["measured"], measured["hours"]

    def test_a_question_over_finished_work_measures_no_intent(self):
        self.assertEqual(self.intent(), (1, 4.0))

    def test_a_request_the_seat_finishes_by_ticking_a_line_is_measured_from_its_first_message(self):
        self.harness.said.append(NOW - 12 * HOUR)
        plan.write("fix-api", ["- [x] dates parse · check: `make test` · acme · written "
                               "2026-10-20 09:00 · done 1a2b3c4 2026-10-20 10:00"])
        self.done(NOW - 10 * HOUR)
        self.assertEqual(self.intent(), (2, 3.0))        # four hours and two

    def test_a_request_whose_run_merges_is_measured_from_its_first_message(self):
        self.harness.said.append(NOW - 8 * HOUR)
        self.runs.append(("r2", NOW - 7 * HOUR))
        self.done(NOW - 2 * HOUR)
        self.assertEqual(self.intent(), (2, 5.0))        # four hours and six

    def test_a_line_from_an_older_plan_is_read_without_waiting_on_the_seat_lock_the_done_holds(self):
        flock = notify.fcntl.flock

        def never_waits(fd, operation):     # nobody else locks this HOME: a wait is on itself
            try:
                return flock(fd, operation | notify.fcntl.LOCK_NB)
            except BlockingIOError:
                raise AssertionError("the done waited on the seat lock it holds") from None
        self.harness.said.append(NOW - 12 * HOUR)
        # its project named bare: asking which run delivered it takes the seat's lock
        plan.write("fix-api", ["- [x] exports finish · check: `make test` · acme · deferred · "
                               "written 2026-10-20 09:00 · done 1a2b3c4 2026-10-20 10:00"])
        with patch.object(notify.fcntl, "flock", never_waits):
            self.done(NOW - 10 * HOUR)
        self.assertEqual(self.intent(), (2, 3.0))        # four hours and two


if __name__ == "__main__":
    unittest.main()
