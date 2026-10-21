"""Another model's orchestrator mark on the `c` screen moves the seat at once, asking nothing.

The owner (20 Oct): "When I chose a different orch ... No question should be asked."  Enter,
space or a click on that mark moves the seat there and then (menu.session_mark); no question
card is drawn, and the mark of the model the seat is already on moves nothing.

Offline: a throwaway HOME, the keys fed in, the question card faked to record any ask, and the
switch itself faked to write the record alone.
"""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import config, menu, orch, terminal, update, usage
from agentkit.terminal import Key


class Keyboard:
    def take(self):
        return True


class OrchestratorMarkAsksNothing(Sandbox):
    def setUp(self):
        super().setUp()
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"],
                            {"reviewers": ["astra"], "cwd": "/", "created": 0})
        self.asked, self.moved = [], []

        def switch(cfg, name, model, providers=None):
            # as the real one: the seat's own model is no move
            if config.load_session(cfg, name)["orchestrator"] == model:
                return ""
            self.moved.append((name, model))
            config.update_session(name, orchestrator=model)
            return ""
        self.stack.enter_context(patch.object(
            terminal, "confirm", side_effect=lambda question, *_a, **_kw: self.asked.append(
                question)))
        self.stack.enter_context(patch.object(orch, "switch_orchestrator", side_effect=switch))
        self.stack.enter_context(patch.object(update, "agentkit_version", return_value="abc1234"))
        self.stack.enter_context(patch.object(usage, "collect",
                                              return_value=usage.Readings({})))

    def screen(self, keys):
        with patch.object(terminal, "read_key", side_effect=keys), \
                redirect_stdout(io.StringIO()):
            menu.show_config(False, Keyboard(), "fix-api")

    def test_enter_moves_the_seat_at_once_and_its_own_model_s_mark_moves_nothing(self):
        # the highlight opens on the first model's orchestrator mark: fable's, while the seat
        # is on opus; Enter again is on the seat's own model
        self.screen([Key("enter"), Key("enter"), Key("esc")])
        self.assertEqual(self.asked, [])
        self.assertEqual(self.moved, [("fix-api", "fable")])
        self.assertEqual(config.load_session(self.cfg, "fix-api")["orchestrator"], "fable")


if __name__ == "__main__":
    unittest.main()
