"""New code under an open screen that cannot run, or is signalled before it can draw, still gives
the terminal back: what only this Python build can be made to do, so no answer key."""

import os
import signal
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import GIVEN, Terminal

# New code slow to start: told its screen is up, a program says who it is, then takes its time.
SLOW = """import os, time
if "AK_SCREEN_SHOWING" in os.environ:
    with open(os.environ["PID_FILE"], "w") as out:
        out.write(str(os.getpid()))
    time.sleep(1)
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Failing(unittest.TestCase):
    def test_new_code_that_cannot_be_run_says_why_on_the_shells_screen(self):
        with Home() as home:
            Seat(home, "s-one")
            home.write(".agentkit/state/installed-at", str(time.time() - 3600))
            python = home.bin / "python3"       # what the menu execs, gone from under it
            python.symlink_to(os.path.realpath(sys.executable))
            menu = Terminal(home)
            menu.wait("s-one")
            python.unlink()
            home.write(".agentkit/state/installed-at", str(time.time()))
            self.assertEqual(menu.exit_code(bound=60), 1)
            self.assertEqual(menu.modes(), GIVEN)
            self.assertIn("FileNotFoundError", menu.screen())

    def test_a_signal_while_new_code_starts_gives_the_terminal_back(self):
        with Home() as home:
            Seat(home, "s-one")
            home.write(".agentkit/state/installed-at", str(time.time() - 3600))
            home.write("slow/sitecustomize.py", SLOW)
            told = home.root / "pid"
            menu = Terminal(home, env={"PYTHONPATH": home.path / "slow", "PID_FILE": told})
            menu.wait("s-one")
            home.write(".agentkit/state/installed-at", str(time.time()))
            menu.wait(lambda _: told.exists() and told.read_text(), bound=60)
            os.kill(int(told.read_text()), signal.SIGTERM)
            self.assertEqual(menu.exit_code(bound=60), 128 + signal.SIGTERM)
            self.assertEqual(menu.modes(), GIVEN)


if __name__ == "__main__":
    unittest.main()
