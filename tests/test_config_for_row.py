"""`c`'s For row says whom its marks are for -- new seats ([defaults]), new and open seats, or
one seat -- and a flip goes there at once, asking nothing.  Offline: a throwaway HOME, the keys
fed in, and the switch faked to write the record alone, as test_switch_orchestrator proves it.
"""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import threading
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


def said(scope):
    """The For row on `scope` as terminal.plain reads it, its spaces each one."""
    return " ".join(menu.for_text(scope).split())


class ForRow(Sandbox):
    def setUp(self):
        super().setUp()
        for name in ("fix-api", "acme"):
            config.save_session(self.cfg, name, "opus", ["opus", "astra"],
                                {"reviewers": ["astra"], "cwd": "/", "created": 0})
        self.moved, self.refuse = [], {}

        def switch(cfg, name, model, providers=None):
            # as the real one: the seat's own model is no move
            if config.load_session(cfg, name)["orchestrator"] == model:
                return ""
            if name in self.refuse:
                return self.refuse[name]
            self.moved.append((name, model))
            config.update_session(name, orchestrator=model)
            return ""
        self.stack.enter_context(patch.object(orch, "switch_orchestrator", side_effect=switch))
        self.stack.enter_context(patch.object(terminal, "confirm", side_effect=AssertionError))
        self.stack.enter_context(patch.object(update, "agentkit_version", return_value="abc1234"))
        self.stack.enter_context(patch.object(usage, "collect",
                                              return_value=usage.Readings({})))

    def screen(self, *keys, session=None, seats=("fix-api", "acme")):
        """The `c` screen with `seats` open, opened on `session`'s row, read with `keys` then
        Esc; what it drew."""
        drawn = io.StringIO()
        with patch.object(terminal, "read_key", side_effect=[*map(Key, keys), Key("esc")]), \
                redirect_stdout(drawn):
            menu.show_config(False, Keyboard(), session, list(seats))
        return terminal.plain(drawn.getvalue())

    def turned(self, *keys, session=None):
        """The scopes the For row showed, one each time it changed."""
        frames = self.screen(*keys, session=session).split("agentkit · config")
        turned = [next(scope for scope in (*menu.FOR_SCOPES, "fix-api", "acme")
                       if said(scope) in frame) for frame in frames[1:]]
        return [scope for at, scope in enumerate(turned) if not at or scope != turned[at - 1]]

    def record(self, name):
        return config.load_session(config.load(), name)

    def defaults(self):
        return config.load()["defaults"]

    def test_it_opens_on_new_seats_titled_config_and_turns_round_the_seats(self):
        text = self.screen()
        self.assertIn("agentkit · config", text)
        self.assertNotIn("config · ", text)
        self.assertIn(said("new seats"), text)
        # ↑ from the first model is the row; → turns it on, round the end, and ← back
        self.assertEqual(self.turned("up", *["right"] * 4, "left"),
                         ["new seats", "new and open seats", "fix-api", "acme", "new seats",
                          "acme"])

    def test_opened_on_a_seat_back_twice_is_new_seats(self):
        # acme's row: its own roles first, then the rest on down the screen from it
        self.assertEqual(self.turned("up", "left", "left", *["right"] * 4, session="acme"),
                         ["acme", "new and open seats", "new seats", "new and open seats",
                          "acme", "fix-api", "new seats"])

    def test_on_new_seats_a_flip_is_the_defaults_and_no_seat_moves(self):
        # the highlight opens on the first model's orchestrator mark: fable's
        self.screen("enter")
        self.assertEqual(self.defaults()["orchestrator"], "fable")
        self.assertEqual(self.moved, [])
        self.assertEqual(self.record("fix-api")["orchestrator"], "opus")
        # a builder flipped in goes into [defaults]' builders alone
        self.screen("right", "down", "down", "down", "enter")
        self.assertEqual(self.defaults()["workers"], ["opus", "astra", "spark"])
        self.assertEqual(self.record("acme")["workers"], ["opus", "astra"])

    def test_on_a_seat_a_flip_moves_that_seat_alone_asking_nothing(self):
        before = self.defaults()
        self.screen("up", "right", "right", "down", "enter")
        self.assertEqual(self.moved, [("fix-api", "fable")])
        self.assertEqual(self.record("fix-api")["orchestrator"], "fable")
        self.assertEqual(self.defaults(), before)

    def test_on_new_and_open_seats_every_open_seat_takes_the_flip(self):
        self.screen("up", "right", "down", "enter")
        self.assertEqual(self.defaults()["orchestrator"], "fable")
        self.assertEqual(sorted(self.moved), [("acme", "fable"), ("fix-api", "fable")])
        # a reviewer flipped in goes into every seat's reviewers, the others kept as they were
        text = self.screen("up", "right", "down", "right", "right", "down", "down", "down",
                           "enter")
        self.assertIn("A change here goes to new seats and to the 2 open seats.", text)
        for name in ("fix-api", "acme"):
            self.assertEqual(self.record(name)["reviewers"], ["astra", "spark"])
            self.assertEqual(self.record(name)["workers"], ["opus", "astra"])

    def test_a_seat_that_cannot_move_is_named_and_the_rest_move(self):
        self.refuse["acme"] = "fable: claude is not installed"
        text = self.screen("up", "right", "down", "enter")
        self.assertIn("acme: fable: claude is not installed", text)
        self.assertEqual(self.moved, [("fix-api", "fable")])
        self.assertEqual(self.defaults()["orchestrator"], "fable")
        # the mark already on gives it to the seat that missed it, once it can move
        del self.refuse["acme"]
        self.screen("up", "right", "down", "enter")
        self.assertEqual(self.record("acme")["orchestrator"], "fable")

    def test_each_seat_a_flip_for_all_could_not_change_is_named_and_on_its_for_row(self):
        self.refuse.update(dict.fromkeys(("fix-api", "acme"), "fable: claude is not installed"))
        text = self.screen("up", "right", "down", "enter", "up", "right", "right")
        self.assertIn("fix-api: fable: claude is not installed", text)
        last = text.split("agentkit · config")[-1]     # turned on to acme: its own said again
        self.assertIn(said("acme"), last)
        self.assertIn("acme: fable: claude is not installed", last)

    def test_a_note_taller_than_the_screen_keeps_whole_lines_and_counts_the_rest(self):
        note = "\n".join(f"acme-{n}: fable: claude is not installed" for n in range(30))
        with patch.object(terminal, "height", return_value=24), \
                patch.object(terminal, "layout_width", return_value=40):
            fitted = menu.note_fitted(note, "esc back")
            self.assertLessEqual(len(menu.note_lines(fitted)), 24 - 6 - 1)    # a row stays
        *kept, more = fitted.splitlines()
        self.assertEqual(kept, note.splitlines()[:len(kept)])
        self.assertEqual(more, f"… and {30 - len(kept)} more")

    def test_a_highlighted_seat_that_is_not_open_is_not_among_the_open_seats(self):
        text = self.screen("up", "left", "down", "enter", session="fix-api", seats=["acme"])
        self.assertIn("A change here goes to new seats and to the 1 open seats.", text)
        self.assertEqual(self.moved, [("acme", "fable")])

    def queued(self, *acts):
        """`c` on fix-api read with `acts` (matrix_key's answers), each flip's wait left with Esc
        and fable's orchestrator switch held until the last is made; fix-api's record after."""
        release = threading.Event()

        def switch(cfg, name, model, providers=None):
            if model == "fable":
                release.wait(10)
            config.update_session(name, orchestrator=model)
            return ""
        with patch.object(orch, "switch_orchestrator", side_effect=switch), \
                patch.object(terminal, "taken", return_value=True), \
                patch.object(menu, "moving", return_value=Key("esc")), \
                patch.object(menu, "matrix_key",
                             side_effect=[*acts, ("back", ("model", "fable"), None, 0)]), \
                patch.object(menu, "config_meters", return_value=([], {})), \
                redirect_stdout(io.StringIO()):
            menu.config_matrix(self.cfg, None, "abc1234", "fix-api", self.record("fix-api"),
                               usage.Readings({}), seats=["fix-api"])
            release.set()
            menu.FLIPS(lambda: None)()        # once every flip made before it has ended
        return self.record("fix-api")

    def test_a_flip_made_while_one_goes_behind_the_screen_comes_after_it(self):
        record = self.queued(("enter", ("model", "fable"), 0, 0),
                             ("enter", ("model", "astra"), 0, 0))
        self.assertEqual(record["orchestrator"], "astra")

    def test_a_flip_waiting_behind_another_keeps_what_that_one_did(self):
        # fable built in while the switch holds, the For row turned away and back, spark built in
        record = self.queued(("enter", ("model", "fable"), 0, 0),
                             ("enter", ("model", "fable"), 1, 0), ("left", menu.FOR_ROW, None, 0),
                             ("right", menu.FOR_ROW, None, 0), ("enter", ("model", "spark"), 1, 0))
        self.assertEqual(record["workers"], ["opus", "astra", "fable", "spark"])

if __name__ == "__main__":
    unittest.main()
