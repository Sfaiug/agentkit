"""`c`'s For row names whom its marks are for -- new seats ([defaults], test_new_seats_marks) or
the seat `c` opened on -- and never turns, the keys passing over it; a flip is for whom it names,
asking nothing.
Offline: a throwaway HOME, the keys fed in, the switch faked as test_switch_orchestrator proves.
"""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, orch, terminal, update, usage  # noqa: E402
from agentkit.terminal import Key  # noqa: E402

SEATS = ("fix-api", "acme")


class ForRow(Sandbox):
    def setUp(self):
        super().setUp()
        for name in SEATS:
            config.save_session(self.cfg, name, "opus", ["opus", "astra"],
                                {"reviewers": ["astra"], "cwd": "/", "created": 0})
        self.moved = []

        def switch(cfg, name, model, providers=None):
            self.moved.append((name, model))
            config.update_session(name, orchestrator=model)
            return ""
        for target, name, value in ((orch, "switch_orchestrator", switch),
                                    (terminal, "confirm", AssertionError),     # nothing asks
                                    (update, "agentkit_version", lambda: "abc1234"),
                                    (usage, "collect", lambda *_a, **_k: usage.Readings({}))):
            self.stack.enter_context(patch.object(target, name, side_effect=value))

    def screen(self, *keys, session=None):
        """Whom the For row named, as it changed, on `c` opened on `session` and read `keys`."""
        drawn, keyboard = io.StringIO(), type("Keyboard", (), {"take": lambda _: True})()
        with patch.object(terminal, "read_key", side_effect=[*map(Key, keys), Key("esc")]), \
                redirect_stdout(drawn):
            menu.show_config(False, keyboard, session)
        named = [next(scope for scope in (menu.NEW_SEATS, *SEATS) if f"For {scope} orch" in frame)
                 for frame in terminal.plain(drawn.getvalue()).split("agentkit · config ")[1:]]
        return [scope for at, scope in enumerate(named) if not at or scope != named[at - 1]]

    def test_it_never_turns(self):
        # ↑ from the first model is past the row, on a meter, and ←, → and ↓ there turn nothing
        self.assertEqual(self.screen("up", "right", "left", "down", session="fix-api"),
                         ["fix-api"])
        self.assertEqual(self.screen("up", "right", "left", "down"), ["new seats"])

    def test_a_flip_is_for_whom_the_row_names_asking_nothing(self):
        self.screen("enter")                                             # new seats': fable
        self.assertEqual((config.load()["defaults"]["orchestrator"], self.moved), ("fable", []))
        self.screen("enter", session="acme")                             # acme's own
        self.assertEqual(self.moved, [("acme", "fable")])


if __name__ == "__main__":
    unittest.main()
