"""A card on a screen of more lines than its terminal has rows is answered by the keys alone.

A click is read against the rows a screen counted for its lines.  `− remove`'s card is thirteen
rows at forty columns, so a terminal of eight scrolls it, and before 19 Nov a click on a blank
row under `× Remove` removed the subscription.  The pointer answers nothing there now
(terminal.choose), and Down and Enter remove as always.

Black-box: `− remove` under `Claude III` on tests/test_key_removed_subscription_signs_out.py's
terminal, made forty by eight before the card is asked.  Judged by what the terminal shows and
config.toml under a temporary HOME; Go's ak does not claim this file yet (go/keys.txt).
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from test_key_removed_subscription_signs_out import Subscriptions


class ACardTallerThanItsTerminal(Subscriptions):
    def accounts(self):
        return akconfig.read(self.home)["providers"]["anthropic"]["accounts"]

    def test_no_click_answers_it_and_down_and_enter_do(self):
        self.term.wait(lambda screen: "add a subscription" in screen)
        self.to("Claude III")
        self.term.resize(40, 8)            # ak reads the size as it draws the card
        self.term.keys("Right", "Right", "Enter")          # `− remove`, last on its line
        self.term.wait(lambda screen: "› ✓ Keep" in screen and "esc back" in screen)
        for row in range(8, 0, -1):
            self.term.type(f"\x1b[<0;3;{row}M\x1b[<0;3;{row}m")
        self.term.keys("Down")
        self.term.wait("› × Remove")       # the card still up: no click answered it
        self.assertEqual(self.accounts(), ["default", "a1", "b2"])
        self.term.keys("Enter")
        self.term.wait(lambda screen: "Keep" not in screen)
        self.assertEqual(self.accounts(), ["default", "a1"])


if __name__ == "__main__":
    unittest.main()
