"""A seat's build or review effort step its `c` applies sets its
keys on its record as it stands, so a key saved since the screen opened is kept; a step of its
orchestrator's effort writes nothing itself, handing the level to the seat's move; the open
screen then holds what was saved.

In-process, in a throwaway HOME (tests/fixtures/sandbox.py): seat `fix-api` on the shipped
config, its record changed behind an open screen's back.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox
from agentkit import config, menu, usage


class SeatEffortSteps(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(usage, "unready", return_value=None))
        config.save_session(self.cfg, "fix-api", "opus", ["opus"], {"reviewers": ["opus"]})
        self.selected = config.load_session(self.cfg, "fix-api")      # as the screen opened
        config.change_efforts("fix-api", lambda record: {
            **record["efforts"], "opus": {**record["efforts"]["opus"], "review_effort": "high"}})

    def held(self):
        return config.load_session(self.cfg, "fix-api")["efforts"]

    def stepped(self, role):    # Opus's `role` effort on its lowest, held on the page alone
        held, before = {}, self.held()
        note = menu.config_effort(self.cfg, "opus", 0, role=role, to=0, seat=(self.selected, held))
        self.assertEqual((note, self.held()), ("", before))
        return held

    def test_a_step_keeps_a_key_saved_since(self):
        note = menu.apply_held(self.cfg, ("fix-api", self.selected), self.stepped("executor"), None)
        self.assertEqual(note, "")
        self.assertEqual(self.held()["opus"],
                         {"effort": "xhigh", "review_effort": "high", "exec_effort": "low"})
        self.assertEqual(self.selected["efforts"], self.held())

    def test_an_orchestrator_step_writes_nothing_itself_and_moves_the_seat_to_it(self):
        # the move, faked, writes the record as the real one does; the screen then holds it
        handed = []

        def restart(cfg, name, model, effort=None, asked=None, **_kw):
            handed.append((name, model, effort, asked(False), self.held()))
            config.change_efforts(name, lambda record: config.orchestrating_at(
                cfg["models"], record, model, effort))
            return ""
        held, before = self.stepped("orchestrator"), self.held()
        with patch.object(menu.orch, "switch_orchestrator", side_effect=restart):
            note = menu.apply_held(self.cfg, ("fix-api", self.selected), held, lambda *card: True)
        self.assertEqual(note, "")
        self.assertEqual(handed, [("fix-api", "opus", "low", True, before)])
        self.assertEqual(self.held()["opus"],
                         {"effort": "low", "review_effort": "high", "exec_effort": "xhigh"})
        self.assertEqual(self.selected["efforts"], self.held())

    def test_an_orchestrator_step_on_a_record_that_will_not_read_says_why(self):
        held = self.stepped("orchestrator")
        config.session_path("fix-api").write_text("{")
        with patch.object(usage, "collect", return_value={}):
            note = menu.apply_held(self.cfg, ("fix-api", self.selected), held, lambda *card: True)
        self.assertIn("session-fix-api.json", note)


if __name__ == "__main__":
    unittest.main()
