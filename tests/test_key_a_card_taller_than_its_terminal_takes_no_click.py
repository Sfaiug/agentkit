"""A card on a screen of more lines than its terminal has rows is answered by the keys alone.

A click is read against the rows a screen counted for its lines.  `− remove`'s card is on a
screen of eleven lines at forty columns, so a terminal of eight rows scrolls it, and before
19 Nov a click on a blank row under `× Remove` removed the subscription.  The pointer answers
nothing there now (terminal.choose): no click does, the pointer on the highlighted answer
leaves Enter its answer, and a button that went down there is no click once the terminal is
tall enough, where a click answers again.  Down and Enter remove as always.  The rows and
columns are the terminal's own: LINES or COLUMNS, exported at the size it had, say nothing of
the one it has, and one that says no rows has none for the card.  Nor does a click answer
where a newline returns no carriage, each line begun where the last ended.

Black-box: `− remove` under `Claude III` on tests/test_key_removed_subscription_signs_out.py's
terminal, made forty columns wide before the card is asked.  Judged by what the terminal shows
and config.toml under a temporary HOME; Go's ak does not claim this file yet (go/keys.txt).
"""

from pathlib import Path
import sys
import termios
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akterm import SERVER
from test_key_removed_subscription_signs_out import Subscriptions


class Card(Subscriptions):
    height = 8          # the terminal's rows as the card is asked

    def accounts(self):
        return akconfig.read(self.home)["providers"]["anthropic"]["accounts"]

    def tell(self, tty):
        """What the terminal, resized, is told of itself before the card is asked: nothing."""

    def ask(self):
        self.term.wait(lambda screen: "add a subscription" in screen)
        self.to("Claude III")
        self.term.resize(40, self.height)  # ak reads the size as it draws the card
        tty = self.home.tmux("display", "-p", "-t", self.term.pane, "#{pane_tty}", server=SERVER)
        with open(tty.out.strip(), "wb", buffering=0) as tty:
            self.term.wait(lambda _: termios.tcgetwinsize(tty) == (self.height, 40))
            self.tell(tty)
        self.term.keys("Right", "Right", "Enter")          # `− remove`, last on its line
        self.term.wait(lambda screen: "› ✓ Keep" in screen and "esc back" in screen)

    def grown(self, answer):
        """The row `answer` is on once the terminal, made eighteen rows, shows the card whole:
        its eleven lines from the first row, the keys' the last to be written."""
        self.term.resize(40, 18)
        shown = self.term.wait(lambda screen: "Claude III" in screen.split("\n")[0]
                               and "esc back" in screen.split("\n")[10]).split("\n")
        return next(number for number, line in enumerate(shown, 1) if answer in line)

    def click_every_row(self):
        for row in range(self.height, 0, -1):
            self.term.type(f"\x1b[<0;3;{row}M\x1b[<0;3;{row}m")


class ACardTallerThanItsTerminal(Card):
    def test_no_click_answers_it_and_down_and_enter_do(self):
        self.ask()
        self.click_every_row()
        self.term.keys("Down")
        self.term.wait("› × Remove")       # the card still up: no click answered it
        self.assertEqual(self.accounts(), ["default", "a1", "b2"])
        self.term.keys("Enter")
        self.term.wait(lambda screen: "Keep" not in screen)
        self.assertEqual(self.accounts(), ["default", "a1"])

    def test_the_pointer_on_the_highlighted_answer_leaves_enter_its_answer(self):
        self.ask()
        self.term.keys("Down")
        shown = self.term.wait("› × Remove").split("\n")
        row = next(number for number, line in enumerate(shown, 1) if "› × Remove" in line)
        self.term.type(f"\x1b[<35;{shown[row - 1].index('×') + 1};{row}M")
        self.term.keys("Enter")
        self.term.wait(lambda screen: "Keep" not in screen)
        self.assertEqual(self.accounts(), ["default", "a1"])

    def test_a_button_down_on_it_is_no_click_once_the_terminal_is_tall_enough(self):
        self.ask()
        self.term.type("\x1b[<0;3;8M")     # down on the blank row under the card
        self.term.keys("Down")
        self.term.wait("› × Remove")       # a key read after it
        row = self.grown("› × Remove")
        self.term.type(f"\x1b[<0;3;{row}m")                # and up on `× Remove`
        self.term.keys("Escape")
        self.term.wait(lambda screen: "Keep" not in screen)
        self.assertEqual(self.accounts(), ["default", "a1", "b2"])

    def test_a_click_answers_it_once_the_terminal_is_tall_enough(self):
        self.ask()
        row = self.grown("× Remove")
        self.term.type(f"\x1b[<0;3;{row}M\x1b[<0;3;{row}m")
        self.term.wait(lambda screen: "Keep" not in screen)
        self.assertEqual(self.accounts(), ["default", "a1"])


class ACardOnFewerRowsThanLinesSays(Card):
    exported = {"LINES": "40"}         # the terminal's rows as ak started

    def test_no_click_answers_it(self):
        self.ask()
        self.click_every_row()
        self.term.keys("Escape")
        self.term.wait(lambda screen: "Keep" not in screen)
        self.assertEqual(self.accounts(), ["default", "a1", "b2"])


class ACardOnFewerColumnsThanColumnsSays(ACardOnFewerRowsThanLinesSays):
    # its columns as ak started: laid out a hundred wide the screen is ten lines, which twelve
    # rows would hold, and the terminal wraps them onto more
    exported, height = {"COLUMNS": "100"}, 12


class ACardOnATerminalSayingNoRows(ACardOnFewerRowsThanLinesSays):
    exported = {}       # nothing says its rows: ak lays the card out for twenty-four, a guess

    def tell(self, tty):
        termios.tcsetwinsize(tty, (0, 40))


class ACardOnATerminalReturningNoCarriage(ACardOnFewerRowsThanLinesSays):
    # rows for the screen's eleven lines, were each begun in the first column
    exported, height = {}, 12

    def tell(self, tty):
        told = termios.tcgetattr(tty)
        told[1] &= ~termios.ONLCR          # a newline only moves down a row
        termios.tcsetattr(tty, termios.TCSANOW, told)


if __name__ == "__main__":
    unittest.main()
