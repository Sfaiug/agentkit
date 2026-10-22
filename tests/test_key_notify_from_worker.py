"""A worker's `ak notify` is suppressed: it exits 0, says why, logs it, and nothing pages.

Only an orchestrator seat asks the owner anything.  A worker a run started is nobody's seat, and
a question from it would page the owner about a seat that never asked, so `ak notify` inside a
run's worker (`AK_RUN_ROLE=worker`, handed down to everything the worker starts) records no
question and no card, says why on stdout and in the run's own log, and succeeds, before the
question's shape is judged: a worker asks nothing, well or badly put.  A tick in that
environment writes no seat's card either.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, beside seats of tests/fixtures/akseat.py, paging
tests/fixtures/sink.py.
"""

import json
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.sink import Sink

SUPPRESSED = "notify: needs suppressed: AK_RUN_ROLE=worker; only an orchestrator may notify"
# its "?" past the first 80 characters, which a seat's `ak notify` is refused for
LATE = "The parser and the schema both changed, and the migration reads both of them; which first?"


def state(home, name):
    path = home.path / ".agentkit" / "state" / name
    return json.loads(path.read_text()) if path.is_file() else None


def events(home, seat):
    """The outbox's events about that seat."""
    found = (json.loads(path.read_text())
             for path in (home.path / ".agentkit/state/notification-outbox").glob("*.json"))
    return [event for event in found if event.get("session") == seat]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AWorkersNotify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.sink = Sink(cls.home)
        cls.addClassCleanup(cls.sink.close)
        Seat(cls.home, "fix-api")

    def worker(self, *args, log=None):
        return self.home.ak(*args, env={"AK_RUN_ROLE": "worker",
                                        "AK_RUN_LOG": str(log) if log else None})

    def test_a_worker_s_question_is_said_logged_and_dropped_and_the_command_succeeds(self):
        log = self.home.path / "run.log"
        done = self.worker("notify", "needs", "Which branch?", "--session", "fix-api", log=log)
        self.assertEqual(done.code, 0, done.err)
        self.assertIn(SUPPRESSED, done.out.splitlines())
        self.assertTrue(any(re.fullmatch(r"\[\d\d:\d\d:\d\d\] " + re.escape(SUPPRESSED), line)
                            for line in log.read_text().splitlines()), log.read_text())
        self.assertIsNone(state(self.home, "notify-fix-api.json"))
        self.assertIsNone(state(self.home, "card-fix-api.json"))
        self.assertEqual(events(self.home, "fix-api"), [])
        self.assertEqual(self.sink.requests, [])

    def test_a_worker_s_notify_is_suppressed_before_its_question_is_judged(self):
        refused = self.home.ak("notify", "needs", LATE, "--session", "fix-api")
        self.assertEqual(refused.code, 2, refused.out)
        done = self.worker("notify", "needs", LATE, "--session", "fix-api")
        self.assertEqual(done.code, 0, done.err)
        self.assertIn(SUPPRESSED, done.out.splitlines())
        self.assertIsNone(state(self.home, "notify-fix-api.json"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AWorkersTick(unittest.TestCase):
    def test_a_worker_s_tick_writes_no_card_where_the_owner_s_tick_writes_one(self):
        with Home() as home, Sink(home) as sink:
            Seat(home, "acme", screen="claude-question-pane.txt")
            done = home.ak("watch", env={"AK_RUN_ROLE": "worker"})
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(list((home.path / ".agentkit/state").glob("card-*.json")), [])
            self.assertEqual(events(home, "acme"), [])
            self.assertEqual(sink.requests, [])
            # the same seat, read by a tick nobody's worker runs, is carded
            done = home.ak("watch")
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(state(home, "card-acme.json")["word"], "needs you")


if __name__ == "__main__":
    unittest.main()
