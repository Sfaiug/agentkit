"""A write that would leave a seat's bar as it is does not happen.

An open screen looks at every seat about every 25 seconds, and each look told tmux the seat's
whole bar again.  What changed is still told within a look, and so is a session given a seat's
name again.  Black-box: an open screen over live seats, each on a real capture, judged by the
tmux options it leaves and the `set-option`s every process in the Home logs.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

LOOK = 90          # an open screen looks about every 25 seconds; a loaded host takes longer
QUIET = 30         # no write for longer than a look has passed: what opening the screen writes is over


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ToldOnlyWhatChanged(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home(tmux_log=True)
        cls.addClassCleanup(cls.home.close)
        cls.seats = {name: Seat(cls.home, name) for name in ("acme", "beta", "gamma")}
        cls.menu = Terminal(cls.home, size=(100, 40))
        cls.menu.wait(lambda screen: all(name in screen for name in cls.seats))
        for name in cls.seats:
            cls.wait(lambda name=name: "idle" in cls.option(name, "@ak_top"))
        cls.settle()

    @classmethod
    def option(cls, name, option):
        """That session's own option as it stands, or nothing while it has none."""
        return cls.home.tmux("show-options", "-qv", "-t", f"={name}:", option).out

    @classmethod
    def wait(cls, holds, bound=LOOK):
        deadline = time.monotonic() + bound
        while not holds():
            if time.monotonic() > deadline:
                raise AssertionError(f"not so within {bound} s:\n{cls.menu.screen()}")
            time.sleep(0.2)

    @classmethod
    def writes(cls):
        """Every tmux call, from any process in the Home, that set an option."""
        return [call for call in cls.home.calls("tmux") if "set-option" in call]

    @classmethod
    def settle(cls):
        """Wait out what opening the screen writes; the still minute says what kept writing."""
        deadline, seen, since = time.monotonic() + 2 * LOOK, -1, time.monotonic()
        while time.monotonic() < deadline and time.monotonic() - since < QUIET:
            if len(cls.writes()) != seen:
                seen, since = len(cls.writes()), time.monotonic()
            time.sleep(1)

    def test_a_still_minute_sets_no_option(self):
        before = len(self.writes())
        time.sleep(60)
        # every look of this minute: the tests below show the screen is looking still
        self.assertEqual(self.writes()[before:], [])

    def test_b_a_seat_that_moves_is_told_within_a_look(self):
        self.seats["acme"].show("claude-working-pane.txt")
        self.wait(lambda: "working" in self.option("acme", "@ak_top"))

    def test_c_a_seat_that_turns_needs_you_is_told_and_every_other_seat_says_so(self):
        self.seats["beta"].show("claude-question-pane.txt")
        self.wait(lambda: "needs you" in self.option("beta", "@ak_top"))
        for name in ("acme", "gamma"):
            self.wait(lambda name=name: "1 other seat needs you" in self.option(name, "@ak_need"))
        self.assertNotIn("need", self.option("beta", "@ak_need"))

    def test_d_a_session_given_a_seats_name_again_has_its_bar_told(self):
        self.assertEqual(self.home.tmux("kill-session", "-t", "=gamma:").code, 0)
        self.seats["gamma"].start()     # a new session: nothing has been told to it yet
        self.wait(lambda: "gamma" in self.option("gamma", "@ak_top"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
