"""An `ak` under a HOME that did not start a seat leaves that seat's bar as it is: tmux's socket
is the user's, so a scratch HOME's `ak` wrote `idle` over real seats' `working`."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OnlyTheServersHome(unittest.TestCase):
    def test_another_homes_menu_leaves_the_bar_and_its_own_still_writes(self):
        with Home() as home:
            seat = Seat(home, "s-one", screen="claude-working-pane.txt")
            bar = lambda: home.tmux("show-options", "-t", "=s-one:").out
            menu = Terminal(home)
            menu.wait("working")
            told = bar()
            other = home.root / "other"
            (other / ".agentkit" / "state").mkdir(parents=True)
            stranger = Terminal(home, env={"HOME": other})
            stranger.wait("s-one")
            stranger.keys("Down", "Escape")     # one draw more, every row of it told
            stranger.exit_code()
            self.assertEqual(bar(), told)
            seat.show("claude-question-pane.txt")
            menu.wait("needs you")
            self.assertIn("needs you", bar())


if __name__ == "__main__":
    unittest.main()
