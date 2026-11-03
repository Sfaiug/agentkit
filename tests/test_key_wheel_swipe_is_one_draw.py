"""A swipe and the key after it reach the menu in a handful of frames, even past a list's end.

Black-box: `AK_BIN` in a person's terminal over live seats.  tmux pastes the reports and the
following key together, and pipe-pane keeps the program's bytes: each synchronized update is
a frame, counted through Esc's exit, so neither the terminal's capture rate nor a transient
highlight can hide hundreds of draws.
"""

import re
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

HOLD, LEAVE = b"\x1b[?2026h", b"\x1b[?1049l"
STYLE = re.compile(r"\x1b\[[\d;]*m")
HIGHLIGHT = re.compile(r"› +\d+  (atoll-\d+)  ")
SEATS = [f"atoll-{number:02d}" for number in range(1, 14)]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WheelSwipe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        atoll = home.path / "code" / "atoll"
        done = home.run("git", "init", "-q", str(atoll))
        assert done.code == 0, done.err
        for name in SEATS:
            Seat(home, name, cwd=atoll, record={"repo": str(atoll)})

    def test_a_swipe_clamps_at_each_end_and_the_next_key_moves_back(self):
        for button, key, want in ((65, "k", SEATS[-2]), (64, "j", SEATS[1])):
            with self.subTest(button=button):
                menu = Terminal(self.home, size=(117, 54))
                menu.wait(lambda screen: "esc leave" in screen and SEATS[-1] in screen
                          and screen.count("idle") == len(SEATS))
                raw = self.home.root / f"swipe-{button}"
                raw.touch()
                # send-keys types a byte at a time; a paste writes this whole swipe and k/j.
                swipe = f"\x1b[<{button};10;10M" * 300 + key
                menu._ask("set-buffer", "-b", "swipe", "--", swipe)
                menu._ask("pipe-pane", "-O", "-t", menu.pane,
                          f"cat >{shlex.quote(str(raw))}", ";",
                          "paste-buffer", "-d", "-r", "-b", "swipe", "-t", menu.pane, ";",
                          "send-keys", "-t", menu.pane, "Escape")
                self.assertEqual(menu.exit_code(), 0)
                menu.wait(lambda _: LEAVE in raw.read_bytes())
                said = raw.read_bytes().split(LEAVE)[0]
                marked = HIGHLIGHT.findall(STYLE.sub("", said.decode("utf-8")))
                self.assertTrue(marked, said)
                self.assertEqual(marked[-1], want)
                self.assertLessEqual(said.count(HOLD), 6, "a swipe drew a frame per report")


if __name__ == "__main__":
    unittest.main()
