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
            # And on the bar: a menu draws its first frame before it tells the bar, which would
            # then change under the stranger.  A bar is told whole, in one tmux call.
            menu.wait(lambda _: "working" in bar())
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

    def test_its_own_home_writes_whatever_tmux_shows_a_client_outside_a_utf8_locale(self):
        with Home() as home:
            own = home.root / "élise"       # which tmux shows that client as `_lise`
            own.symlink_to(home.path)
            home.env.update(HOME=str(own), LANG="C", LC_ALL="C")
            Seat(home, "s-one", screen="claude-working-pane.txt")
            Terminal(home).wait(lambda _: "s-one" in home.tmux("show-options", "-t", "=s-one:").out)


if __name__ == "__main__":
    unittest.main()
