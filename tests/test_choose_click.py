"""A chooser's Enter and Esc answer as their keys do; a click on nothing does nothing, nor
does any click on a screen its terminal scrolled, where the pointer's move leaves Enter its
answer.

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
    return next((last, row) for row, (_, spans, *_) in spots.items()
                for _, last, cell in spans if cell == key)


class ChooseClick(unittest.TestCase):
    def pick(self, events, keyline="↑↓←→ move   ⏎ add   esc back", rows=24, pad=0, places=None,
             **options):
        """What the list, a screen of seven lines, answers to `events` on a terminal of `rows`
        rows with `pad` cells blank in from each edge, `places` what else its body has
        (`terminal.frame`)."""
        read, write = os.pipe()
        with os.fdopen(read, "rb", buffering=0) as stdin, \
                os.fdopen(write, "wb", buffering=0) as writer, \
                patch.object(sys, "stdin", stdin), redirect_stdout(io.StringIO()), \
                patch.multiple(terminal, _TAKEN=types.SimpleNamespace(again=(None, None)),
                               _KEYED=b"", _PRESSED=False, _POINTER=None, _SPOTS={},
                               _POINTED=terminal.Spot(), _NEXT=None, _HELD=None,
                               _MOVED=0.0, _AWAY=False, _UNSEEN=False, _ASKED=False,
                               _PAD=pad), \
                patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=rows - 2 * pad), \
                patch.object(terminal, "colour_depth", return_value=0), \
                patch.object(terminal, "utf8", return_value=True):
            def around(lines, _):
                spots = terminal.frame("config · add a subscription", lines, keyline,
                                       places=places)
                if not writer.closed:
                    writer.write(events(spots))
                    writer.close()
                return 3

            return terminal.choose(CHOICES, around=around, **options)

    def test_clicking_enter_picks_the_highlighted_choice(self):
        for keyline, key in (("↑↓←→ move   ⏎ add   esc back", "⏎"),
                             ("arrows move   enter add   esc back", "enter")):
            with self.subTest(key=key):
                self.assertEqual(self.pick(lambda spots: click(*action(spots, key)),
                                           keyline, default="Example"), "Example")

    def test_hovered_enter_first_restores_the_highlight(self):
        def events(spots):
            col, row = action(spots, "⏎")
            return (f"\x1b[<35;{col};{row}M".encode() + click(col, row)
                    + b"\x1b[B" + click(col, row))

        self.assertEqual(self.pick(events, default="Example"), "Demo")

    def test_clicks_on_choices_and_esc_keep_their_actions(self):
        self.assertEqual(self.pick(lambda spots: click(5, 5)), "Demo")
        self.assertIsNone(self.pick(lambda spots: click(*action(spots, "esc"))))

    def test_a_click_on_nothing_leaves_the_list_and_its_highlight(self):
        for col, row in ((1, 2), (40, 3)):     # a blank row, and the empty rest of a choice's
            with self.subTest(col=col, row=row):
                self.assertEqual(self.pick(lambda spots: click(col, row) + b"\x1b[B\r"),
                                 "Example")

    def test_a_screen_filling_a_padded_popup_takes_a_click_and_one_scrolling_it_none(self):
        demo = click(6, 6)                     # `Demo`, the padding's cell further in each way
        self.assertEqual(self.pick(lambda spots: demo, rows=9, pad=1), "Demo")
        self.assertEqual(self.pick(lambda spots: demo + b"\x1b[B\r", rows=8, pad=1), "Example")

    def test_the_pointer_off_every_row_of_a_scrolled_screen_leaves_enter_its_answer(self):
        # off every row the pointer puts the highlight out, Enter only bringing it back; a
        # scrolled screen still has the rows that are its own, a meter's here
        places = {0: (None, [(3, 8, "meter", "meter")])}
        keys = b"\x1b[B\x1b[<35;1;2M\r"        # Down, the pointer onto the rule, Enter
        self.assertIsNone(self.pick(lambda spots: keys, rows=8, places=places))
        self.assertEqual(self.pick(lambda spots: keys, rows=7, places=places), "Example")


if __name__ == "__main__":
    unittest.main(verbosity=2)
