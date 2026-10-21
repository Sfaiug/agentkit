"""The answer key's terminals are tmux as a person meets ak in one.

A screen test reads what a terminal shows; it holds only if tests/fixtures/akterm.py does.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Terminals(unittest.TestCase):
    def test_a_terminal_shows_the_program_and_keeps_its_exit_status(self):
        with Home() as home:
            term = Terminal(home, "--help", size=(100, 50))
            self.assertEqual(term.exit_code(), 0)
            self.assertIn("usage: ak [command]", term.wait("usage:"))
            self.assertEqual(home.tmux("list-sessions").code, 1)   # ak's own server never started

    def test_the_program_draws_its_colours_as_on_a_person_s_terminal(self):
        with Home() as home:
            term = Terminal(home, "--help", size=(100, 50))
            term.wait("usage:")
            self.assertRegex(term.screen(colours=True), "\x1b\\[[0-9;]*m")

    def test_a_program_ended_by_ctrl_c_leaves_its_exit_status_and_its_screen(self):
        with Home() as home:
            menu = Terminal(home, size=(100, 40))
            menu.wait("no login")      # the menu is up: no harness has a login in a Home
            menu.keys("C-c")
            self.assertNotEqual(menu.exit_code(), 0)
            self.assertEqual(home.tmux("list-panes", "-a", server="agentkit-term").code, 0)


if __name__ == "__main__":
    unittest.main()
