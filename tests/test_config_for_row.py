"""`c`'s For row says whom its marks are for -- new seats ([defaults]) or one seat -- and a flip
goes there at once, asking nothing.  Offline: a throwaway HOME, the keys fed in, and the switch
faked to write the record alone, as test_switch_orchestrator proves it.
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


class Seats(Sandbox):
    """Two seats on opus, and a switch that writes the record alone."""

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
        """Whom the For row named, in turn, on `c` opened on `session` and read with `keys`."""
        drawn = io.StringIO()
        with patch.object(terminal, "read_key", side_effect=[*map(Key, keys), Key("esc")]), \
                redirect_stdout(drawn):
            menu.show_config(False, Keyboard(), session, list(SEATS))
        named = [next(scope for scope in (*menu.FOR_SCOPES, *SEATS)
                      if " ".join(menu.for_text(scope).split()) in frame)
                 for frame in terminal.plain(drawn.getvalue()).split("agentkit · config ")[1:]]
        return [scope for at, scope in enumerate(named) if not at or scope != named[at - 1]]

    def orchestrators(self):
        return [config.load()["defaults"]["orchestrator"],
                *(config.load_session(config.load(), name)["orchestrator"] for name in SEATS)]


class ForRow(Seats):
    def test_it_turns_from_new_seats_or_the_seat_it_opened_on_round_the_seats(self):
        # ↑ from the first model is the row; → turns it on, round the end, and ← back
        self.assertEqual(self.screen("up", *["right"] * 4, "left"),
                         ["new seats", "new and open seats", "fix-api", "acme", "new seats",
                          "acme"])
        self.assertEqual(self.screen("up", "left", "left", *["right"] * 3, session="acme"),
                         ["acme", "new and open seats", "new seats", "new and open seats",
                          "acme", "fix-api"])

    def test_on_new_seats_a_flip_is_the_defaults_and_no_seat_moves(self):
        self.screen("enter")                    # the first model's orchestrator mark: fable's
        self.screen("right", "down", "down", "down", "enter")    # spark builds
        self.assertEqual(self.orchestrators(), ["fable", "opus", "opus"])
        self.assertEqual(config.load()["defaults"]["workers"], ["opus", "astra", "spark"])
        self.assertEqual(config.load_session(config.load(), "acme")["workers"], ["opus", "astra"])
        self.assertEqual(self.moved, [])

    def test_on_a_seat_a_flip_moves_that_seat_alone_asking_nothing(self):
        self.screen("up", "right", "right", "down", "enter")
        self.assertEqual(self.moved, [("fix-api", "fable")])
        self.assertEqual(self.orchestrators(), ["opus", "fable", "opus"])


if __name__ == "__main__":
    unittest.main()
