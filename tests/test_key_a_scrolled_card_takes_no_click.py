"""On a terminal with fewer rows than a card's screen has lines, no click answers the card.

Black-box, forty by eight, on tests/test_key_removed_subscription_signs_out.py's terminal: before
19 Nov a click on the `esc back` it showed, or on a blank row, removed the subscription, as a
row no longer held the line counted for it.  Go's ak does not claim this file yet (go/keys.txt).
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_removed_subscription_signs_out import Subscriptions, akconfig


class AScrolledCard(Subscriptions):
    def test_no_click_answers_it_and_down_and_enter_do(self):
        self.term.wait(lambda screen: "add a subscription" in screen)
        self.to("Claude III")
        self.term.resize(40, 8)            # ak reads the size as it draws the card
        self.term.keys("Right", "Right", "Enter")          # `− remove`, last on its line
        shown = self.term.wait(lambda screen: "› ✓ Keep" in screen and "esc back" in screen)
        row, line = next(at for at in enumerate(shown.splitlines(), 1) if "esc back" in at[1])
        for column, row in [(line.index("esc") + 1, row), *((3, each) for each in range(1, 9))]:
            self.term.type(f"\x1b[<0;{column};{row}M\x1b[<0;{column};{row}m")
        self.term.type("\x1b[<0;3;8M")     # down on the scrolled card, up on Remove's row once
        self.term.resize(40, 18)           # the terminal holds the whole of it
        self.term.wait(lambda screen: "× Remove" in screen.splitlines()[7])
        self.term.type("\x1b[<0;3;8m")
        self.term.keys("Down")
        self.term.wait("› × Remove")       # the card still up: no click answered it
        self.assertIn("b2", akconfig.read(self.home)["providers"]["anthropic"]["accounts"])
        self.term.keys("Enter")
        self.term.wait(lambda screen: "Keep" not in screen)
        self.assertNotIn("b2", akconfig.read(self.home)["providers"]["anthropic"]["accounts"])


if __name__ == "__main__":
    unittest.main()
