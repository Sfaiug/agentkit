"""`c` on a heading marks new seats: a flip is [defaults], what the next `n` starts from, saved
at once and asking nothing, and no open seat changes.

The owner (20 Oct): "When I chose a different orch, all currnet sessions should just stay on
track, and new ones should have the new default set which I have just chosen."

Offline: a throwaway HOME with two seats, the keys fed in, and the question card and the
switch faked to record any ask or move.
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


class Keyboard:
    def take(self):
        return True


class NewSeatsMarks(Sandbox):
    def setUp(self):
        super().setUp()
        for name in SEATS:
            config.save_session(self.cfg, name, "opus", ["opus", "astra"],
                                {"reviewers": ["astra"], "cwd": "/", "created": 0})
        self.asked, self.moved = [], []
        for target, name, value in (
                (orch, "switch_orchestrator", lambda _cfg, *moved, **_kw: self.moved.append(moved)),
                (terminal, "confirm", lambda question, *_a, **_kw: self.asked.append(question)),
                (update, "agentkit_version", lambda: "abc1234"),
                (usage, "collect", lambda *_a, **_kw: usage.Readings({}))):
            self.stack.enter_context(patch.object(target, name, side_effect=value))

    def screen(self, *keys):
        """The `c` screen opened on a heading, read with `keys`, as it was drawn."""
        drawn = io.StringIO()
        with patch.object(terminal, "read_key", side_effect=[*map(Key, keys), Key("esc")]), \
                redirect_stdout(drawn):
            menu.show_config(False, Keyboard(), None)
        return terminal.plain(drawn.getvalue())

    def test_a_flip_is_the_defaults_and_no_seat_changes(self):
        drawn = self.screen("enter")            # the first model's orchestrator mark: fable's
        self.assertIn("For new seats", drawn)       # terminal.plain: one space
        self.screen("right", "down", "down", "down", "enter")    # spark builds
        defaults = config.load()["defaults"]
        self.assertEqual((defaults["orchestrator"], defaults["workers"]),
                         ("fable", ["opus", "astra", "spark"]))
        for name in SEATS:
            seat = config.load_session(config.load(), name)
            self.assertEqual((seat["orchestrator"], seat["workers"]), ("opus", ["opus", "astra"]))
        self.assertEqual((self.asked, self.moved), ([], []))

    def test_a_flip_that_cannot_be_saved_says_why_and_keeps_the_defaults(self):
        before = config.load()["defaults"]
        with patch.object(config, "save", side_effect=OSError("disk full")):
            drawn = self.screen("enter")
        self.assertIn("config: disk full", drawn)
        self.assertEqual(config.load()["defaults"], before)


if __name__ == "__main__":
    unittest.main()
