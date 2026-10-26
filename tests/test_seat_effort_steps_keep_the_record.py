"""A seat's effort step and `r` on its `c` set their keys on its record as it stands, so a key
saved since the screen opened is kept, and the open screen then holds what was saved.

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

    def test_a_step_keeps_a_key_saved_since(self):
        note = menu.config_effort(self.cfg, "opus", 0, role="executor", to=0,
                                  seat=("fix-api", self.selected))
        self.assertEqual(note, "")
        self.assertEqual(self.held()["opus"],
                         {"effort": "xhigh", "review_effort": "high", "exec_effort": "low"})
        self.assertEqual(self.selected["efforts"], self.held())

    def test_r_keeps_a_key_saved_since_and_the_screen_holds_what_it_saved(self):
        note = menu.take_advice(self.cfg, "fix-api", self.selected, {},
                                {"execute": ("Opus 5.5 @ max", "opus", "max")})
        self.assertEqual(note, "")
        self.assertEqual(self.held()["opus"],
                         {"effort": "xhigh", "review_effort": "high", "exec_effort": "max"})
        self.assertEqual(self.selected["efforts"], self.held())


if __name__ == "__main__":
    unittest.main()
