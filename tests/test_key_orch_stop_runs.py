"""A stopped seat ends first, then every run it launched that is still going stops with it.

Stopping a seat is the deliberate stop that takes everything connected to it: a run it launched
would otherwise go on building and hand its result back to a seat the owner closed.  `ak orch
stop NAME` ends the seat, then stops each of its going runs, and each reads stopped by the user,
as `ak run stop` leaves one; the seat's finished runs and every other seat's runs are left as
they were.  Run from outside the seats it prints `stopped <run>` for each, then the seat's own
line; run from that seat it says nothing, as the terminal it would print to went with the seat.
From another seat the stop is refused and the seat's runs go on.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, before seats of tests/fixtures/akseat.py and run records
naming the seat that launched each; this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

RUNS = {"api-retry": ("running", "fix-api"), "api-docs": ("waiting", "fix-api"),
        "api-lint": ("pass", "fix-api"), "beta-cache": ("running", "other")}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class StopOwnedRuns(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        Seat(self.home, "fix-api")
        Seat(self.home, "other")
        self.written = {}
        for run_id, (state, seat) in RUNS.items():
            self.written[run_id] = {"run_id": run_id, "state": state, "launched_session": seat}
            self.home.write(f".agentkit/runs/{run_id}/run.json", self.written[run_id])

    def run_record(self, run_id):
        return json.loads((self.home.path / ".agentkit/runs" / run_id / "run.json").read_text())

    def alive(self, seat):
        return self.home.tmux("has-session", "-t", f"={seat}").code == 0

    def test_from_outside_the_seats_each_going_run_and_the_seat_say_they_stopped(self):
        done = self.home.ak("orch", "stop", "fix-api", env={"AGENTKIT_SESSION": ""})
        self.assertEqual(done.code, 0, done.err)
        lines = done.out.splitlines()
        self.assertEqual(lines[-1:], ["stopped fix-api; its number reopens it"])
        self.assertEqual(sorted(lines[:-1]), ["stopped api-docs", "stopped api-retry"])
        self.assert_stopped_with_its_runs()

    def test_the_seat_itself_stops_without_a_word_into_its_gone_terminal(self):
        done = self.home.ak("orch", "stop", "fix-api", env={"AGENTKIT_SESSION": "fix-api"})
        self.assertEqual((done.code, done.out, done.err), (0, "", ""))
        self.assert_stopped_with_its_runs()

    def assert_stopped_with_its_runs(self):
        for run_id in ("api-retry", "api-docs"):
            with self.subTest(run_id):
                record = self.run_record(run_id)
                self.assertEqual((record["state"], record["verdict"], record["error"]),
                                 ("stopped", "STOPPED", "stopped by the user"))
                self.assertIsInstance(record["finished_at"], (int, float))
                self.assertEqual(record["launched_session"], "fix-api")
        for run_id in ("api-lint", "beta-cache"):
            with self.subTest(run_id):
                self.assertEqual(self.run_record(run_id), self.written[run_id])
        self.assertFalse(self.alive("fix-api"))
        self.assertTrue(self.alive("other"))

    def test_from_another_seat_the_stop_is_refused_and_its_runs_go_on(self):
        done = self.home.ak("orch", "stop", "fix-api", env={"AGENTKIT_SESSION": "other"})
        self.assertEqual((done.code, done.out), (2, ""), done.err)
        self.assertEqual(done.err,
                         "ak orch: owned by seat fix-api; a seat stops only its own runs\n")
        for run_id in RUNS:
            with self.subTest(run_id):
                self.assertEqual(self.run_record(run_id), self.written[run_id])
        self.assertTrue(self.alive("fix-api"))


if __name__ == "__main__":
    unittest.main()
