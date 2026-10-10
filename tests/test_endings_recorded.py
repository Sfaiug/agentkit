"""Routine run endings are recorded, not typed; a seat hears only what needs its decision.

A merged run, a run not needed and a change going live are recorded on the run (handed
back with the routine note, reported, its checkout dropped) and typed into no seat, live or
gone: nothing in them is the seat's to decide, and `ak run status` and the seat's plan have
them.  A fail, a blocked and a pass not merged are still typed, at a quiet prompt and never
into a running turn: a turn in flight leaves the line pending for the tick.  Offline, on the
hand-back stage (`test_handback.HandBack`) and the after-merge probe stage
(`test_health_after_merge.HealthAfterMerge`).
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_handback import SEAT, HandBack
from test_health_after_merge import NOW, HealthAfterMerge
from agentkit import run
from agentkit import record


class RoutineEndings(HandBack):
    def recorded(self, directory):
        state = record.read_state(directory)
        self.assertTrue(state["handed_back"])
        self.assertTrue(state["reported"])
        self.assertEqual(state["handback_note"], run.ROUTINE_NOTE)
        self.assertNotIn("handback_pending", state)

    def test_a_merged_ending_is_recorded_and_never_typed(self):
        directory = self.ended("run-m", owner=SEAT, merged=True, pr="https://github.com/o/r/pull/7")
        self.rows = [self.live()]
        run.announce(record.read_state(directory), directory, self.logs.append)
        self.assertEqual((self.typed, self.cards, self.reopened), ([], [], []))
        self.recorded(directory)
        self.tick()                                         # nothing is left for the tick
        self.assertEqual(self.typed, [])

    def test_a_not_needed_ending_is_recorded_too(self):
        directory = self.ended("run-n", owner=SEAT, state="not_needed", verdict=None)
        self.rows = [self.live()]
        run.announce(record.read_state(directory), directory, self.logs.append)
        self.assertEqual((self.typed, self.cards), ([], []))
        self.recorded(directory)

    def test_a_gone_seats_merged_ending_wakes_nobody(self):
        directory = self.ended("run-g", owner=SEAT, merged=True, pr="https://github.com/o/r/pull/7")
        self.rows = []
        run.announce(record.read_state(directory), directory, self.logs.append)
        self.assertEqual((self.typed, self.cards, self.reopened), ([], [], []))
        self.recorded(directory)

    def test_what_needs_a_decision_is_typed_at_a_quiet_prompt_and_never_into_a_turn(self):
        failed, unmerged = self.failed("run-f"), self.ended("run-u", owner=SEAT, no_merge=True)
        self.rows = [self.live()]
        self.screen = "working"                             # a turn in flight
        for directory in (failed, unmerged):
            run.announce(record.read_state(directory), directory, self.logs.append)
        self.assertEqual(self.typed, [])
        self.assertTrue(record.read_state(failed)["handback_pending"])
        self.screen = "at_prompt"
        self.tick()
        self.assertEqual([text.split()[1] for _, text in self.typed], ["run-f", "run-u"])
        self.assertIn("finished FAIL", self.typed[0][1])
        self.assertIn("finished PASS not merged", self.typed[1][1])
        self.tick()
        self.assertEqual(len(self.typed), 2)                # once


class LiveRecorded(HealthAfterMerge):
    def test_a_change_going_live_is_recorded_and_never_typed(self):
        directory = self.merged(self.declare("exit 0"))
        self.tick()
        state = record.read_state(directory)
        self.assertEqual((state["live_at"], state["live_notified"]), (NOW, NOW))
        self.assertEqual(self.lines, [])
        self.tick(now=NOW + 60)
        self.assertEqual(self.lines, [])


def load_tests(loader, tests, pattern):
    """Only this file's own cases: the stages it builds on run their tests from their own files."""
    suite = unittest.TestSuite()
    for case in (RoutineEndings, LiveRecorded):
        suite.addTests(case(name) for name in loader.getTestCaseNames(case) if name in vars(case))
    return suite


if __name__ == "__main__":
    unittest.main()
