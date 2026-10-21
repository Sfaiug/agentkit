"""A completed turn on a harness without blocking Stop is judged by its own look.

The existing nudge fixture drives real classifiers, records and typing against a fake tmux.
Here the clock never advances: a normal completion must not wait for stall recovery.
"""
import os
import unittest
from unittest.mock import patch

import test_nudge_turn_rule as fixture
from agentkit import config, notify, orch, watch


class StopParity(unittest.TestCase):
    def seat(self, harness):
        f = fixture.NudgeTurnRule()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.harness = harness
        f.stopped()
        watch.seat_write(fixture.SEAT, stop_said_at=10000,
                         stop_said=watch.progress_output(harness, watch.pane_tail(f.pane)))
        return f

    def look(self, f):
        def tmux(*args, **kwargs):
            if args[0] == "display-message" and args[-1] == "#{socket_path}\t#{session_name}":
                return 0, f"/test/socket\t{fixture.SEAT}"
            return f.tmux(*args, **kwargs)

        with patch.dict(os.environ, {"TMUX": "/test/socket,1,0", "TMUX_PANE": "%1"}), \
                patch.object(orch, "tmux_out", side_effect=tmux):
            return watch.hook_look(fixture.SEAT)

    def test_the_completion_look_resumes_open_work_without_a_tick_or_stall_wait(self):
        for harness in fixture.HARNESSES:
            with self.subTest(harness=harness):
                f = self.seat(harness)
                self.look(f)
                self.assertEqual(f.sent, ["continue"])
                self.look(f)
                self.assertEqual(f.sent, ["continue"])

    def test_a_tick_can_also_judge_a_just_completed_turn(self):
        for harness in fixture.HARNESSES:
            with self.subTest(harness=harness):
                f = self.seat(harness)
                self.assertEqual(f.tick(), ["continue"])

    def test_the_completion_look_preserves_questions_drafts_waits_and_closed_seats(self):
        for harness in fixture.HARNESSES:
            for held in ("question", "draft", "run", "closed", "finished"):
                with self.subTest(harness=harness, held=held):
                    f = self.seat(harness)
                    if held == "question":
                        notify.record(fixture.SEAT, "needs", "Which region should acme use?")
                    elif held == "draft":
                        empty, row = fixture.TYPED[harness]
                        f.pane = f.pane.replace(empty, row.format("owner is typing"))
                    elif held == "run":
                        f.receipt(fixture.THEIRS, fixture.SEAT, "running")
                    elif held == "closed":
                        watch.seat_write(fixture.SEAT, closed_by_owner=True)
                    else:
                        config.plan_path(fixture.SEAT).write_text("- [x] acme works\n")
                    self.look(f)
                    self.assertEqual(f.sent, [])

    def test_an_interruption_is_never_a_completion_to_resume(self):
        for harness in fixture.HARNESSES:
            with self.subTest(harness=harness):
                f = self.seat(harness)
                watch.seat_write(fixture.SEAT, interrupted=True)
                self.assertEqual(f.tick(), [])

    def test_errors_stay_with_error_recovery(self):
        for harness in fixture.HARNESSES:
            for detector in ("auth_expired_on", "stuck_on", "stall_mark"):
                with self.subTest(harness=harness, detector=detector):
                    f = self.seat(harness)
                    with patch.object(watch, detector, return_value="error"):
                        self.look(f)
                    self.assertEqual(f.sent, [])


if __name__ == "__main__":
    unittest.main()
