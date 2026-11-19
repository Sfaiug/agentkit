"""On a terminal with fewer rows than a card's screen has lines, no click answers the card.

Black-box, forty by eight, on tests/test_key_removed_subscription_signs_out.py's terminal: before
19 Nov a click on the `esc back` it showed, or on a blank row, removed the subscription, as a
row no longer held the line counted for it.  The rows are the terminal's own, whatever size its
shell exports.  Nor does a click ak reads with a resize still unread; one it reads at a size
the card was not written at, told of no resize, as a warm menu is not before its client says
(agentkit/warm.py), where a key is what draws the card again; or one the terminal sent before it
had the card that key drew.  The terminal's output is stopped (`tcflow`) over what ak is to read
only after its next write.
Go's ak does not claim this file yet (go/keys.txt).
"""

import os
from pathlib import Path
import sys
import termios
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK
from fixtures.akterm import SERVER, Terminal
from test_key_removed_subscription_signs_out import Subscriptions, akconfig

DOWN, UP = "\x1b[<0;3;8M", "\x1b[<0;3;8m"     # the button on column 3 of row 8, as it is sent


class Card(Subscriptions):
    """Claude III's remove card on forty columns by eight rows: `× Remove` on row 4, row 8 blank."""

    ENV = {**Subscriptions.ENV, "COLUMNS": "100", "LINES": "40"}    # the size it started at

    def setUp(self):
        super().setUp()
        tty = self.home.tmux("display-message", "-p", "-t", self.term.pane, "#{pane_tty}",
                             server=SERVER).out.strip()
        self.tty = os.open(tty, os.O_RDONLY | os.O_NOCTTY)      # the terminal's, for its size
        self.addCleanup(os.close, self.tty)
        self.addCleanup(self.stop, False)
        self.term.wait(lambda screen: "add a subscription" in screen)
        self.to("Claude III")
        self.rows(8)
        self.term.keys("Right", "Right", "Enter")          # `− remove`, last on its line
        self.shown = self.term.wait(lambda screen: "› ✓ Keep" in screen and "esc back" in screen)

    def rows(self, rows):
        """The terminal at that many rows, once it says so: tmux shows them a moment before."""
        self.term.resize(40, rows)
        self.term.wait(lambda _: os.get_terminal_size(self.tty).lines == rows)

    def stop(self, stopped=True):
        """The terminal's output stopped: ak waits in its next write, what is typed unread."""
        termios.tcflow(self.tty, termios.TCOOFF if stopped else termios.TCOON)

    def click(self, column, row):
        self.term.type(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")

    def kept(self, row=None, line=None):
        """The subscription is there once `line` is on `row` of the card or, given neither, the
        card is gone: drawn after all that was typed."""
        self.term.wait(lambda screen: line in screen.splitlines()[row - 1] if row
                       else "Keep" not in screen)
        self.assertIn("b2", akconfig.read(self.home)["providers"]["anthropic"]["accounts"])


class AScrolledCard(Card):
    def test_no_click_answers_it_and_down_and_enter_do(self):
        row, line = next(at for at in enumerate(self.shown.splitlines(), 1) if "esc back" in at[1])
        for column, row in [(line.index("esc") + 1, row), *((3, each) for each in range(1, 9))]:
            self.click(column, row)
        self.term.type(DOWN)               # down on the scrolled card, up on Remove's row once
        self.rows(18)                      # the terminal holds the whole of it
        self.term.wait(lambda screen: "× Remove" in screen.splitlines()[7])
        self.term.type(UP + DOWN)          # and down on Remove
        self.stop()                        # ak waits in what Down writes
        self.term.keys("Down")
        self.rows(8)                       # there and back: the terminal moved the card up, and
        self.rows(18)                      # at the size it was drawn for its row 8 is blank
        self.term.type(UP + DOWN)          # up there, and down again
        self.term.keys("Up")
        self.stop(False)                   # both are read before ak reads of either resize
        self.kept(7, "› ✓ Keep")
        self.term.type(UP)                 # and up on Remove's row, the card drawn again
        self.term.keys("Down")
        self.kept(8, "› × Remove")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "Keep" not in screen)
        self.assertNotIn("b2", akconfig.read(self.home)["providers"]["anthropic"]["accounts"])

    def test_the_pointer_on_it_is_on_no_answer(self):
        self.term.type("\x1b[<35;3;8M")    # onto its row 8, the one counted for Remove
        self.term.keys("Enter")            # Keep, as the keys left it
        self.kept()


class ACardToldOfNoResize(Card):
    """The card as the terminal moved it growing to eighteen rows: `× Remove` on row 4 still, its
    row 8 blank, where the card ak draws for that size has it."""

    def setUp(self):
        # the shell that runs ak ignores the terminal's resizes, and so does ak, run by it
        untold = lambda home, **how: Terminal(home, "-c", 'trap "" WINCH; exec "$@"', "sh", AK,
                                              program="sh", **how)
        with patch("test_key_removed_subscription_signs_out.Terminal", untold):
            super().setUp()
        self.rows(18)

    def test_no_click_or_pointer_at_a_size_it_was_not_written_at_answers_it(self):
        self.term.type("\x1b[<35;3;8M")    # the pointer onto row 8, and a click there
        self.click(3, 8)
        self.term.keys("Enter")            # Keep, as the keys left it
        self.kept()

    def test_none_sent_before_the_terminal_had_it_drawn_for_that_size_answers_it(self):
        self.stop()                        # ak waits in the card Down has it draw for the size
        self.term.keys("Down")             # it reads, Remove lit on row 8
        self.click(3, 8)                   # sent before the terminal had that card: a click and
        self.term.type("\x1b[<64;3;8M\x1b[<35;3;8M")    # the pointer there, a notch up between
        self.term.keys("Enter")
        self.stop(False)                   # the notch and Enter alone are read on it: Keep
        self.kept()


if __name__ == "__main__":
    unittest.main()
