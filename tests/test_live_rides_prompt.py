"""A change gone live rides on the prompt that starts its seat's turn, once, and is not typed after.

Offline: the real prompt hook, run records and the tick's live pass, in a temporary HOME; the
seat and its send are faked.
"""

import unittest
from unittest.mock import patch

from test_endings_ride_prompt import SEAT, EndingsRidePrompt
from test_health_after_merge import PR, SEAT as MERGED_SEAT, HealthAfterMerge
from agentkit import config, handback, notify, orch, record

OPEN = "- [ ] the parser parses\n"     # a plan line the seat still owes


class LiveRidesPrompt(EndingsRidePrompt):
    def gone_live(self, name, **extra):
        return self.ended(name, owner=SEAT, merged=True, live_at=9995, pr=PR, **extra)

    def test_a_change_gone_live_rides_once_while_its_seat_owes_work(self):
        config.plan_path(SEAT).write_text(OPEN)
        live = self.gone_live("fix-parser")
        self.gone_live("fix-schema", live_typed={"line": "run fix-schema", "seat": 100})
        context = self.hook()
        self.assertIn(f"run fix-parser is live: {PR}.", context)
        self.assertNotIn("fix-schema", context)                # its Enter is the tick's
        self.assertTrue(record.read_state(live)["live_notified"])
        self.assertEqual(self.hook(), "")

    def test_a_seat_owing_nothing_has_it_recorded_by_the_tick(self):
        live = self.gone_live("fix-parser")
        self.assertEqual(self.hook(), "")
        self.assertNotIn("live_notified", record.read_state(live))

    def test_while_ak_types_into_the_seat_or_its_record_is_written_it_stays_the_ticks(self):
        config.plan_path(SEAT).write_text(OPEN)
        live = self.gone_live("fix-parser")
        for held in (lambda: notify.session_lock(SEAT), lambda: record.recovery_lock(live),
                     lambda: handback.delivery_lock(live)):
            with held():
                self.assertEqual(self.hook(), "")
            self.assertNotIn("live_notified", record.read_state(live))
        self.assertIn(f"run fix-parser is live: {PR}.", self.hook())


class TickLeavesWhatRode(HealthAfterMerge):
    def send(self, seat, line, log, stale=lambda held: False, **_kw):
        """The real send's promise: `stale` is asked under the seat's lock before any key."""
        with notify.session_lock(seat["name"]) as held:
            if stale(held):
                return False
            self.lines.append((seat["name"], line))
        return True

    def test_a_live_line_a_prompt_carried_first_is_never_typed(self):
        config.plan_path(MERGED_SEAT).write_text(OPEN)
        directory = self.merged(self.declare("exit 0"))
        seat, carried = self.rows[0], []
        # a prompt starts the seat's turn between the pass reading the run and typing its line
        with patch.object(orch, "find",
                          lambda name: carried.append(handback.riding(name)) or seat):
            self.tick()
        self.assertIn(f"run {directory.name} is live: {PR}.", "".join(carried))
        self.assertEqual(self.lines, [])
        self.assertTrue(record.read_state(directory)["live_notified"])


def load_tests(loader, tests, pattern):
    """Only this file's own cases: the harnesses it builds on run theirs from their own files."""
    return unittest.TestSuite(case(name) for case in (LiveRidesPrompt, TickLeavesWhatRode)
                              for name in vars(case) if name.startswith("test_"))


if __name__ == "__main__":
    unittest.main()
