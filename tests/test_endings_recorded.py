"""Routine run endings are recorded, not typed; a seat hears only what needs its decision.

A merged run, a run not needed and a change going live are recorded on the run (handed
back with the routine note, reported, its checkout dropped) and typed into no seat, live or
gone, while that seat owes no work: nothing in them is the seat's to decide, and `ak run
status` and the seat's plan have them, a maintainer's merge of a PR of ours among them.  A
seat that owes work (an open plan line) may have ended its turn waiting on that run or its
going live (`stop.recorded_ending`), so it hears them as the end of that wait; a red
target's repair is routine whatever it owes.  A line an earlier pass typed and
never saw sent is sent, never left in the composer to hold later lines back.  A fail, a
blocked and a pass not merged are still typed, at a quiet prompt and never into a running
turn: a turn in flight leaves the line pending for the tick.  Offline, on the hand-back
stage (`test_handback.HandBack`), the composer stage (`test_run_notice_fits_a_composer`)
and the after-merge probe stage (`test_health_after_merge.HealthAfterMerge`).
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_handback import SEAT, HandBack
from test_health_after_merge import NOW, PR, SEAT as MERGED_SEAT, HealthAfterMerge
from test_run_notice_fits_a_composer import RunNotice
from agentkit import config, orch, run, stop, watch
from agentkit import record

OPEN = "- [ ] the parser parses\n"     # a plan line the seat still owes


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

    def test_a_seat_that_owes_work_hears_the_merge_its_turn_waited_on(self):
        config.plan_path(SEAT).write_text(OPEN)
        self.rows = [self.live()]
        directory = self.ended("run-g", owner=SEAT, state="running", verdict=None,
                               finished_at=None)
        self.assertEqual(stop.recorded_ending(SEAT), (True, []))   # its turn ends on the run
        with record.record(directory) as current:
            current.update(state="pass", verdict="PASS", merged=True, finished_at=9990,
                           pr="https://github.com/o/r/pull/7")
        self.screen = "working"                             # never into a turn
        run.announce(record.read_state(directory), directory, self.logs.append)
        self.assertEqual(self.typed, [])
        self.screen = "at_prompt"
        self.tick()
        self.assertEqual([text.split()[1:4] for _, text in self.typed],
                         [["run-g", "finished", "PASS"]])
        self.assertIn("merged", self.typed[0][1])
        self.tick()
        self.assertEqual(len(self.typed), 1)                # once

    def test_a_repairs_merge_is_recorded_whatever_its_seat_owes(self):
        config.plan_path(SEAT).write_text(OPEN)
        self.rows = [self.live()]
        directory = self.ended("run-r", owner=SEAT, merged=True,
                               pr="https://github.com/o/r/pull/7",
                               repair={"target": "main", "command": "false"})
        run.announce(record.read_state(directory), directory, self.logs.append)
        self.assertEqual((self.typed, self.cards, self.reopened), ([], [], []))
        self.recorded(directory)


class InTheComposer(RunNotice):
    def test_a_maintainers_merge_is_recorded_and_never_typed(self):
        for prompt in (True, False):
            with self.subTest(at_prompt=prompt):
                directory, state = self.result(f"run-{prompt}", pr=PR)
                with patch.object(watch, "at_prompt", return_value=prompt), \
                        patch.object(run, "run_for_pr", return_value=(directory, state)):
                    self.assertTrue(watch.say(False, self.logs.append,
                                              "PR #7 Fix api: merged by the maintainer", PR,
                                              "fix-api", merged=True))
                self.assertTrue(run.routine_ending(record.read_state(directory)))
                self.assertEqual((self.keys, self.sent), ([], []))

    def test_a_maintainers_decision_is_never_typed_into_a_running_turn(self):
        directory, state = self.result("run-d", merged=False, pr=PR)
        with patch.object(watch, "at_prompt", return_value=False), \
                patch.object(run, "run_for_pr", return_value=(directory, state)):
            self.assertFalse(watch.say(False, self.logs.append, "The maintainer requested changes",
                                       PR, "fix-api"))
        self.assertEqual((self.keys, self.sent), ([], []))      # the tick retries at a quiet prompt
        with patch.object(watch, "at_prompt", return_value=True), \
                patch.object(run, "run_for_pr", return_value=(directory, state)):
            self.assertTrue(watch.say(False, self.logs.append, "The maintainer requested changes",
                                      PR, "fix-api"))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("The maintainer requested changes", self.sent[0])

    def test_a_merged_line_left_in_the_composer_is_sent_and_holds_no_later_ending_back(self):
        directory, state = self.result("run-m", merged=True, pr=PR, no_merge=False)
        line = run.handback_line(state, directory, self.cfg)
        self.composer = line                                # typed; its Enter never seen land
        run.mark_delivery(directory, state, handback_pending=True,
                          handback_typed={"line": line, "seat": self.seat["created"]})
        run.announce(record.read_state(directory), directory, self.logs.append, self.cfg)
        self.assertEqual(self.sent, [line])                 # its Enter, nothing typed anew
        failed, _ = self.result("run-f", state="fail", verdict="FAIL", merged=False)
        run.announce(record.read_state(failed), failed, self.logs.append, self.cfg)
        self.assertIn("run-f finished FAIL", self.sent[-1])
        run.announce(record.read_state(directory), directory, self.logs.append, self.cfg)
        state = record.read_state(directory)
        self.assertEqual(state["handback_note"], run.ROUTINE_NOTE)
        self.assertNotIn("handback_typed", state)
        self.assertEqual(len(self.sent), 2)


class LiveRecorded(HealthAfterMerge):
    def test_a_change_going_live_is_recorded_and_never_typed(self):
        directory = self.merged(self.declare("exit 0"))
        self.tick()
        self.assertEqual(record.read_state(directory)["live_at"], NOW)
        self.assertEqual(self.lines, [])
        self.tick(now=NOW + 60)
        self.assertEqual(self.lines, [])

    def test_a_seat_that_owes_work_hears_its_change_went_live(self):
        config.plan_path(MERGED_SEAT).write_text(OPEN)
        directory = self.merged(self.declare("test -e deployed"))
        self.tick()
        with patch.object(watch.time, "time", return_value=NOW):
            # its turn ends on the change not yet live
            self.assertEqual(stop.recorded_ending(MERGED_SEAT), (True, []))
        (self.repo / "deployed").touch()
        self.tick(now=NOW + 60)
        self.assertEqual(self.lines, [(MERGED_SEAT, f"run {directory.name} is live: {PR}.")])
        self.tick(now=NOW + 120)
        self.assertEqual(len(self.lines), 1)                # once

    def test_a_repairs_change_going_live_reaches_a_seat_that_owes_work_too(self):
        """Its merge is routine, the runs parked on it retrying by themselves; its going live
        is the wait the hook let the seat's turn end on, and ends it."""
        config.plan_path(MERGED_SEAT).write_text(OPEN)
        directory = self.merged(self.declare("test -e deployed"))
        with record.record(directory) as current:
            current["repair"] = {"target": "main", "command": "false"}
        self.tick()
        with patch.object(watch.time, "time", return_value=NOW):
            self.assertEqual(stop.recorded_ending(MERGED_SEAT), (True, []))
        (self.repo / "deployed").touch()
        self.tick(now=NOW + 60)
        self.assertEqual(self.lines, [(MERGED_SEAT, f"run {directory.name} is live: {PR}.")])

    def test_a_live_line_an_earlier_install_left_unsent_is_sent_never_dropped(self):
        directory = self.merged(self.declare("exit 0"), age=watch.AFTER_MERGE_WINDOW + 60)
        mark = {"line": f"run {directory.name} is live: {PR}.", "seat": 100}
        with record.record(directory) as current:
            current.update(live_at=NOW - 60, live_typed=mark)
        sent = []
        with patch.object(orch, "watching", return_value=True), \
                patch.object(watch, "type_at_prompt", side_effect=lambda seat, line, log, **kw:
                             sent.append((seat["name"], line, kw.get("typed"))) or True):
            self.tick()
            self.assertEqual(sent, [(self.rows[0]["name"], mark["line"], mark)])   # its Enter
            self.assertNotIn("live_typed", record.read_state(directory))
            self.tick(now=NOW + 60)
        self.assertEqual(len(sent), 1)


def load_tests(loader, tests, pattern):
    """Only this file's own cases: the stages it builds on run their tests from their own files."""
    suite = unittest.TestSuite()
    for case in (RoutineEndings, InTheComposer, LiveRecorded):
        suite.addTests(case(name) for name in loader.getTestCaseNames(case) if name in vars(case))
    return suite


if __name__ == "__main__":
    unittest.main()
