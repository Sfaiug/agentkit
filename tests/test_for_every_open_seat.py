"""`c`'s For row on `new and open seats`: a flip is [defaults] and every open seat's at once,
asking nothing, and a seat that cannot take it keeps what it had and is named under the rows,
as many as the screen holds.  The owner (20 Oct 2026): "should also be able to bulk change
models for all active sessions".  Offline: test_config_for_row's throwaway HOME and faked
switch, the keys fed in.
"""

from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_config_for_row import Keyboard, SEATS, Seats  # noqa: E402
from agentkit import config, menu, orch, terminal  # noqa: E402
from agentkit.terminal import Key  # noqa: E402

EVERY = ("up", "right", "down")       # from the first model to the For row, turned on, and back


class EveryOpenSeat(Seats):
    def frames(self, seats, *keys):
        """Each frame's body and key line on `c` opened on new seats over `seats`."""
        frames = []
        real = terminal.frame

        def frame(title, body=(), keyline="esc back", **kw):
            frames.append(([terminal.plain(line) for line in body], keyline))
            return real(title, body, keyline, **kw)
        with patch.object(terminal, "frame", side_effect=frame), \
                patch.object(terminal, "read_key", side_effect=[*map(Key, keys), Key("esc")]), \
                redirect_stdout(io.StringIO()):
            menu.show_config(False, Keyboard(), None, list(seats))
        return frames

    def test_a_flip_is_the_defaults_and_every_open_seats_asking_nothing(self):
        said = self.frames(SEATS, *EVERY)[-1][0]
        self.assertIn("A change here goes to new seats and to the 2 open seats.", " ".join(said))
        self.frames(SEATS, *EVERY, "enter")            # fable's orchestrator mark
        self.assertEqual(self.orchestrators(), ["fable", "fable", "fable"])
        self.assertEqual(self.moved, [("fix-api", "fable"), ("acme", "fable")])
        self.frames(SEATS, *EVERY, "right", "down", "down", "down", "enter")    # spark builds
        for marks in (config.load()["defaults"],
                      *(config.load_session(config.load(), name) for name in SEATS)):
            self.assertIn("spark", marks["workers"])

    def test_only_open_seats_with_a_record_take_it(self):
        self.assertEqual(menu.open_seats([{"name": "fix-api"}, {"name": "old", "closed": True},
                                          *({"name": key, key: True} for key in orch.CLOSED)]),
                         ["fix-api"])
        refused = {}
        selected = menu.for_selected(self.cfg, menu.FOR_SCOPES[1])[0]
        self.assertEqual(menu.defaults_mark(self.cfg, selected, "fable", 0, {}, refused,
                                            ["fix-api", "gone", "acme"]), "")
        self.assertEqual((self.moved, refused), ([("fix-api", "fable"), ("acme", "fable")], {}))

    def test_a_seat_that_cannot_take_it_keeps_its_model_and_is_named_with_why(self):
        def switch(cfg, name, model, providers=None):
            if name == "acme":
                return "acme stays on opus while a draft or a question is on its screen"
            config.update_session(name, orchestrator=model)
            return ""
        with patch.object(orch, "switch_orchestrator", side_effect=switch):
            said = " ".join(self.frames(SEATS, *EVERY, "enter")[-1][0])
        self.assertIn("acme: stays on opus while a draft or a question is on its screen", said)
        self.assertEqual(self.orchestrators(), ["fable", "fable", "opus"])

    def test_on_a_phone_the_seats_it_names_never_push_the_keys_off(self):
        seats = [f"acme-{n}" for n in range(1, 7)]
        for name in seats:
            config.save_session(self.cfg, name, "opus", ["opus"], {"cwd": "/", "created": 0})

        def switch(cfg, name, model, providers=None):
            return f"{name} stays on opus: its harness refused the move for reason {name}"
        with patch.object(orch, "switch_orchestrator", side_effect=switch), \
                patch.object(terminal, "height", return_value=24), \
                patch.object(terminal, "layout_width", return_value=40):
            body, keys = self.frames(seats, *EVERY, "enter")[-1]
        said = " ".join(body)
        self.assertIn("acme-1: stays on opus", said)
        self.assertIn("more", said)
        self.assertLessEqual(len(body) + 5 + len(terminal.key_line(keys)), 24)


if __name__ == "__main__":
    unittest.main()
