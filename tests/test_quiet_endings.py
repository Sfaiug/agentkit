"""An ending waiting on a seat that is off its prompt costs one log line and one read.

The tick offers every unheard ending again each pass (`watch.offer_endings`).  A seat found
off its prompt is read once a pass, for all the endings waiting on it, and a waiting ending is
named in the log once, as it is first deferred, and again as its line is in: a seat off its
prompt for three days had the tick read it and write the same line for each of 36 runs, every
three minutes, 22,000 lines in all (13 Oct).  Offline, on `test_handback`'s fake seat.
"""

import sys
import unittest
from unittest.mock import patch

from test_handback import SEAT, HandBack
from agentkit import record, run, watch


class QuietEndings(HandBack):
    def deferred(self, name):
        """An ending that needs the seat's decision, announced while the seat is mid-turn."""
        directory = self.ended(name, owner=SEAT, no_merge=True)
        run.announce(record.read_state(directory), directory, self.logs.append)
        self.assertTrue(record.read_state(directory)["handback_pending"])
        self.runs = {**getattr(self, "runs", {}), name: directory}
        return directory

    def waiting_lines(self):
        return [line for line in self.logs if "is not at its prompt" in line]

    def test_a_waiting_ending_is_logged_once_not_once_a_pass(self):
        self.rows = [self.live()]
        self.screen = "working"
        self.deferred("run-1")
        self.assertEqual(len(self.waiting_lines()), 1)
        self.tick()
        self.tick()
        self.assertEqual(len(self.waiting_lines()), 1)       # the later passes say nothing new
        self.assertEqual(self.typed, [])
        self.screen = "at_prompt"
        self.tick()
        self.assertEqual([seat for seat, _ in self.typed], [SEAT])

    def test_a_seat_off_its_prompt_is_read_once_a_pass_for_all_its_endings(self):
        self.rows = [self.live()]
        self.screen = "working"
        for name in ("run-1", "run-2", "run-3"):
            self.deferred(name)
        reads = []
        with patch.object(watch, "type_at_prompt",
                          side_effect=lambda session, *a, **k: reads.append(session["name"]) or False):
            self.tick()
        self.assertEqual(reads, [SEAT])                         # one read, three endings waiting
        self.assertEqual(len(self.waiting_lines()), 3)          # each named once, as deferred

    def test_endings_held_for_a_busy_seat_go_in_once_it_is_back(self):
        self.rows = [self.live()]
        self.screen = "working"
        for name in ("run-1", "run-2"):
            self.deferred(name)
        self.screen = "at_prompt"
        self.tick()
        self.assertEqual(sorted(text.split()[1] for _, text in self.typed), ["run-1", "run-2"])
        for directory in self.runs.values():
            self.assertNotIn("handback_pending", record.read_state(directory))

    def test_an_ending_first_seen_behind_a_busy_seat_is_still_marked_waiting(self):
        # held back unmarked, the history sweep an hour on took it for history, never typed
        self.rows = [self.live()]
        self.screen = "working"
        self.deferred("run-1")
        self.ended("run-2", owner=SEAT, no_merge=True)
        watch.offer_endings(self.logs.append)
        with patch.object(watch.time, "time", return_value=14000):
            watch.sweep_preexisting(self.logs.append)
            self.screen = "at_prompt"
            watch.offer_endings(self.logs.append)
        self.assertEqual(sorted(text.split()[1] for _, text in self.typed), ["run-1", "run-2"])

    def test_endings_first_seen_behind_a_busy_seat_are_marked_waiting_for_one_read(self):
        self.rows = [self.live()]
        self.screen = "working"
        self.deferred("run-1")
        later = [self.ended(name, owner=SEAT, no_merge=True) for name in ("run-2", "run-3")]
        with patch.object(watch, "type_at_prompt", wraps=watch.type_at_prompt) as reads:
            watch.offer_endings(self.logs.append)
        self.assertEqual(reads.call_count, 1)
        for directory in later:
            self.assertTrue(record.read_state(directory)["handback_pending"])

    def test_a_routine_ending_is_recorded_while_its_seat_is_busy(self):
        self.rows = [self.live()]
        self.screen = "working"
        self.deferred("run-1")
        merged = self.ended("run-2", owner=SEAT, merged=True)
        watch.offer_endings(self.logs.append)
        self.assertTrue(record.read_state(merged).get("reported"))

    def test_a_line_already_typed_gets_its_enter_behind_an_older_waiting_ending(self):
        # run-1 reads run-2's unsent line as a draft; only run-2's own offer sends it
        self.rows = [self.live()]
        self.screen = "working"
        self.deferred("run-1")
        self.screen = "at_prompt"
        seat = self.claude()
        second = self.ended("run-2", owner=SEAT, no_merge=True)
        seat.fails = True
        run.announce(record.read_state(second), second, self.logs.append)
        self.assertIn("run-2", seat.composer)
        for _ in range(3):
            watch.offer_endings(self.logs.append)
        self.assertEqual(seat.composer, "")
        self.assertEqual(sorted(line.split()[1] for line in seat.read), ["run-1", "run-2"])


def load_tests(loader, tests, pattern):
    """Only this file's own tests: the fixture it inherits comes with `test_handback`'s."""
    suite = unittest.TestSuite()
    for name in loader.getTestCaseNames(QuietEndings):
        if name in QuietEndings.__dict__:
            suite.addTest(QuietEndings(name))
    return suite


if __name__ == "__main__":
    sys.exit(unittest.main())
