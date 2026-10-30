"""A rename, a looked-at mark or a sweep written as a notice is told keeps its told mark: the notice is said once.

Offline: real run records, the real prompt delivery and the real writers, in a temporary HOME;
the prompt tells the notice just after the other writer read the record under its recovery lock.
"""

import unittest
from unittest.mock import patch

from test_endings_ride_prompt import PR, SEAT, EndingsRidePrompt
from agentkit import config, handback, orch, record, transitions, turns, watch

RENAMED = "fix-widget"
LINE = f"run fix-parser is live: {PR}."


class DeliveredMarkSurvives(EndingsRidePrompt):
    def setUp(self):
        super().setUp()
        config.plan_path(SEAT).write_text("- [ ] the parser parses\n")    # it owes work: told
        self.run = self.live("fix-parser")

    def told_during(self, write, seat=SEAT):
        """Run `write`, a prompt in `seat` telling the notice right after `write` read the record."""
        real, armed, carried = record.read_state, [True], []

        def reading(run_dir):
            state = real(run_dir)
            if (armed and run_dir == self.run
                    and str(run_dir) in getattr(record._RECOVERY_HELD, "paths", ())):
                armed.clear()
                carried.append(handback.riding(seat))
            return state

        with patch.object(record, "read_state", reading):
            write()
        self.assertIn(LINE, carried[0])             # the notice was told inside the writer's stretch
        return record.read_state(self.run)

    def test_a_rename_keeps_the_told_mark(self):
        def find(name):
            return {"name": name, "created": 100, "exited": False}

        with patch.object(orch, "find", side_effect=find), \
                patch.object(orch, "tmux_out", return_value=(0, "")), \
                patch.object(orch, "on_own_server", return_value=False), \
                patch.object(watch, "sync_title", return_value=False):
            # the seat answers to its new name before its runs are rewritten
            state = self.told_during(lambda: orch.rename(SEAT, RENAMED, log=lambda _line: None),
                                     RENAMED)
        self.assertEqual(state["launched_session"], RENAMED)
        self.assertTrue(state.get("live_notified"))
        self.assertEqual(handback.riding(RENAMED), "")

    def test_a_looked_at_mark_keeps_the_told_mark(self):
        state = self.told_during(lambda: self.assertTrue(transitions.mark_looked_at(self.run)))
        self.assertTrue(state["recovery_acknowledged_at"])
        self.assertTrue(state.get("live_notified"))
        self.assertEqual(handback.riding(SEAT), "")

    def test_a_sweep_of_what_an_ended_run_left_keeps_the_told_mark(self):
        ended, carried = self.waiting("fix-schema"), []

        def sweep(_state, **_kw):
            carried.append(handback.riding(SEAT))   # the owner's prompt, while leftovers are ended

        with patch.object(turns, "stop_run_tree", sweep):
            handback.reap(ended, record.read_state(ended))
        self.assertIn("run fix-schema FAIL (", carried[0])
        state = record.read_state(ended)
        self.assertEqual(state["tree_stopped"], [None, None])
        self.assertTrue(handback.already_handed_back(state))
        self.assertEqual(handback.riding(SEAT), "")


def load_tests(loader, tests, pattern):
    """Only this file's own cases: the harness it builds on runs its own from its own file."""
    return unittest.TestSuite(DeliveredMarkSurvives(name) for name in vars(DeliveredMarkSurvives)
                              if name.startswith("test_"))


if __name__ == "__main__":
    unittest.main()
