"""A terminal in a seat is titled with the seat's name and its word, `acme · needs you`.

The owner keeps seats open in terminal windows and tabs, and reads which seat each is and what
it is doing from the title, without switching to it.  Every read of a seat sets its title from
the word it found, so the title follows the word, and each seat's title is its own.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, before
seats of tests/fixtures/akseat.py, each with a person's terminal of tests/fixtures/akterm.py
attached by `ak orch NAME`; judged by the title that terminal was given.
"""

import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WindowTitle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.seats = {name: Seat(cls.home, name) for name in ("acme", "beta")}
        cls.terminals = {name: Terminal(cls.home, "orch", name) for name in cls.seats}

    def assert_title(self, name, want, bound=30):
        """That seat's terminal is titled `want`: a client takes a title a moment after tmux
        has it."""
        deadline = time.monotonic() + bound
        while True:
            shown = self.home.tmux("display-message", "-p", "-t", self.terminals[name].pane,
                                   "#{pane_title}", server=SERVER).out.rstrip("\n")
            if shown == want or time.monotonic() > deadline:
                break
            time.sleep(0.05)
        self.assertEqual(shown, want)

    def read(self, name, screen):
        self.seats[name].show(screen)
        done = self.home.ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.err)

    def test_each_seat_s_terminal_is_titled_with_its_own_name_and_word(self):
        self.read("acme", "claude-question-pane.txt")
        self.read("beta", "claude-working-pane.txt")
        self.assert_title("acme", "acme · needs you")
        self.assert_title("beta", "beta · working")

    def test_the_title_follows_the_word_at_each_read(self):
        for screen, word in (("claude-prompt-pane.txt", "idle"),
                             ("claude-working-pane.txt", "working"),
                             ("claude-question-pane.txt", "needs you"),
                             ("claude-prompt-pane.txt", "idle")):
            with self.subTest(word=word):
                self.read("acme", screen)
                self.assert_title("acme", f"acme · {word}")


if __name__ == "__main__":
    unittest.main()
