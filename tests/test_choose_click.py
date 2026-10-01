"""A chooser's displayed Enter action answers just as its key does; other clicks go back.

Read real SGR mouse reports from a pipe against the frame's rendered key line, without
taking a terminal or reading any user state.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import terminal

CHOICES = ["Acme", "Example", "Demo"]


def click(col, row):
    return f"\x1b[<0;{col};{row}M\x1b[<0;{col};{row}m".encode()


def action(spots, key):
    return next((last, row) for row, (_, spans) in spots.items()
                for _, last, cell in spans if cell == key)


class ChooseClick(unittest.TestCase):
    def pick(self, events, keyline="↑↓ move   ⏎ add   esc back", **options):
        read, write = os.pipe()
        with os.fdopen(read, "rb", buffering=0) as stdin, \
                os.fdopen(write, "wb", buffering=0) as writer, \
                patch.object(sys, "stdin", stdin), redirect_stdout(io.StringIO()), \
                patch.multiple(terminal, _TAKEN=types.SimpleNamespace(again=(None, None)),
                               _KEYED=b"", _PRESSED=False, _POINTER=None, _SPOTS={},
                               _POINTED=terminal.Spot(), _NEXT=None, _HELD=None,
                               _MOVED=0.0, _AWAY=False, _UNSEEN=False, _ASKED=False), \
                patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "colour_depth", return_value=0), \
                patch.object(terminal, "utf8", return_value=True):
            def around():
                spots = terminal.frame("config · add a provider", [""] * len(CHOICES), keyline)
                if not writer.closed:
                    writer.write(events(spots))
                    writer.close()
                return 3

            return terminal.choose(CHOICES, around=around, **options)

    def test_clicking_enter_picks_the_highlighted_choice(self):
        for keyline, key in (("↑↓ move   ⏎ add   esc back", "⏎"),
                             ("arrows move   enter add   esc back", "enter")):
            with self.subTest(key=key):
                self.assertEqual(self.pick(lambda spots: click(*action(spots, key)),
                                           keyline, default="Example"), "Example")

    def test_clicking_enter_accepts_the_marked_choices(self):
        self.assertEqual(self.pick(lambda spots: click(*action(spots, "⏎")),
                                   several=True, default=["Demo", "Acme"]), ["Acme", "Demo"])

    def test_hovered_enter_first_restores_the_highlight(self):
        def events(spots):
            col, row = action(spots, "⏎")
            return (f"\x1b[<35;{col};{row}M".encode() + click(col, row)
                    + b"\x1b[B" + click(col, row))

        self.assertEqual(self.pick(events, default="Example"), "Demo")

    def test_clicks_on_choices_and_elsewhere_keep_their_actions(self):
        self.assertEqual(self.pick(lambda spots: click(5, 5)), "Demo")
        self.assertEqual(self.pick(lambda spots: click(5, 3) + b"\r", several=True), ["Acme"])
        self.assertIsNone(self.pick(lambda spots: click(*action(spots, "esc"))))
        self.assertIsNone(self.pick(lambda spots: click(1, 2)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
