"""A yes-or-no card is answered by the pointer as every screen is: a click on `✓ Keep` keeps
and a click on `× Remove` removes.

On 20 Nov 2026 the owner kept this over a card only the keys answer; why is at
`terminal.confirm`.

Black-box: the program `AK_BIN` names, its menu in a person's terminal that holds the card
(tests/fixtures/akterm.py), judged by what the terminal shows and config.toml under a temporary
HOME; this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_removed_subscription_signs_out import Subscriptions, akconfig


class ACardThatFits(Subscriptions):
    def clicked(self, answer):
        """Claude's subscriptions once Claude III's remove card took a click on `answer`."""
        self.to("Claude III")
        self.term.keys("Right", "Right", "Enter")
        screen = self.term.wait(lambda text: "› ✓ Keep" in text and "esc back" in text)
        row, line = next(at for at in enumerate(screen.splitlines(), 1) if answer in at[1])
        at = f"{line.index(answer) + 1};{row}"
        self.term.type(f"\x1b[<0;{at}M\x1b[<0;{at}m")
        self.term.wait(lambda text: "✓ Keep" not in text)
        return akconfig.read(self.home)["providers"]["anthropic"]["accounts"]

    def test_a_click_on_keep_keeps_and_a_click_on_remove_removes(self):
        self.term.wait("add a subscription")
        self.assertIn("b2", self.clicked("✓ Keep"))
        self.assertNotIn("b2", self.clicked("× Remove"))


if __name__ == "__main__":
    unittest.main()
