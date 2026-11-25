"""An open menu's row follows a seat's hooks: a turn begun reads `working`, its composer drawn as
before, and ended `idle`, with no key pressed.

Each hook has the seat looked at, and the look writes its record, what it saw and then its word;
the open screen draws the word recorded.  Black-box: the program `AK_BIN` names runs in a
person's terminal (tests/fixtures/akterm.py) beside a seat of tests/fixtures/akseat.py, Claude's
hooks fired at it as its adapter registers them (tests/fixtures/hookdrive.py).
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal
from fixtures.hookdrive import Hooks
from test_key_idle_screen_reads_only_what_changed import row

BOUND = 120       # seconds: a loaded host's look, and the screen's draw after it


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AnOpenMenuFollowsASeatsOwnLook(unittest.TestCase):
    # The word follows the real change within about 2 seconds, on every harness.
    # [14, 20 Oct 2026]
    def test_the_row_follows_a_turn_begun_and_ended(self):
        with Home() as home:
            akconfig.write(home, ["opus"])
            seat, hooks = Seat(home, "acme"), Hooks(home)
            menu = Terminal(home, size=(100, 24))
            menu.wait(row("acme", "○ idle"), bound=BOUND)
            for event, payload, word in (("UserPromptSubmit", {"prompt": "go"}, "● working"),
                                         ("Stop", {"background_tasks": []}, "○ idle")):
                fired = hooks.fire(event, payload, seat="acme", pane=seat, finished=True)
                self.assertEqual(fired.code, 0, fired.out + fired.err)
                menu.wait(row("acme", word), bound=BOUND)


if __name__ == "__main__":
    unittest.main()
