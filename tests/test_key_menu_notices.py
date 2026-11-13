"""The menu shows a notice once, and starts again on new code.

A finished background job leaves its lines in `~/.agentkit/state/update-result`; the menu shows
them once, before it draws: on a terminal in its own frame, until the owner has read them
(test_key_a_notice_has_ak_s_frame.py), and from a pipe whole, as nobody is there to wait
for.  An install newer than the open menu (`~/.agentkit/state/installed-at`, which
install.sh stamps where there is none) makes the menu start again, reading everything afresh, on
the seat it had highlighted, so a menu left open never runs old code.  Black-box: the program
`AK_BIN` names runs in a person's terminal (tests/fixtures/akterm.py) or from a pipe, beside
tests/fixtures/akseat.py's seats, its start again read from the bytes it writes (`pipe-pane`),
and this test fails against `/bin/false`.
"""

import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

NOTICE = ".agentkit/state/update-result"
ROWS = "  2  beta"
TAKEN, UPDATED = b"\x1b[?1049h", b"\x1b[?2026l"    # the screen taken; an update written whole
OPENS = 60      # the first draw looks at every seat, which a loaded host makes slow


def home_with_seats():
    home = Home()
    akconfig.write(home, ["opus"])
    made = int(time.time()) - 900
    for at, name in enumerate(("acme", "beta")):
        Seat(home, name, record={"created": made + 60 * at})
    return home


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Notices(unittest.TestCase):
    def test_from_a_pipe_a_notice_is_printed_whole_at_words_and_waits_for_nobody(self):
        self.home = home_with_seats()
        self.addCleanup(self.home.close)
        words = " ".join(f"word{n}" for n in range(30))
        self.home.write(NOTICE, f"update: {words} {self.home.path}/code/acme\n")
        done = self.home.ak(input="\n", env={"COLUMNS": "60"})
        self.assertEqual(done.code, 0, done.err)
        lines = done.out.splitlines()
        head = lines.index(next(line for line in lines if line.startswith("agentkit")))
        notice = lines[:head]
        self.assertTrue(all(line.startswith(" ") and len(line) <= 59 for line in notice),
                        notice)
        self.assertEqual(" ".join(line.strip() for line in notice),
                         f"update: {words} ~/code/acme")
        self.assertIn(ROWS, done.out)       # the Enter typed was the menu's, not the notice's


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NewCode(unittest.TestCase):
    def test_new_code_under_an_open_menu_starts_it_again_on_the_seat_it_had_highlighted(self):
        with home_with_seats() as home:
            menu = Terminal(home, size=(80, 24))
            menu.wait(ROWS, bound=OPENS)
            drawn = time.time()             # the menu started before it drew
            menu.keys("j")
            menu.wait("› 2  beta")
            # what it writes from here, which tmux shows none of: only a start takes the screen
            said = home.root / "program-bytes"
            done = home.tmux("pipe-pane", "-t", menu.pane, f"cat >{shlex.quote(str(said))}",
                             server=SERVER)
            self.assertEqual(done.code, 0, done.err)
            # install.sh stamps whole seconds: one past the second the menu started in
            while time.time() < int(drawn) + 1:
                time.sleep(0.05)
            home.write(".agentkit/state/installed-at", f"{int(time.time())}\n")
            menu.keys("i")          # a key that does nothing: the menu reads news before a draw
            # started again: the screen taken, the old frame's rows let go, then its first frame
            deadline = time.monotonic() + OPENS
            while (said.read_bytes() if said.exists() else b"").partition(
                    TAKEN)[2].count(UPDATED) < 2:
                self.assertLess(time.monotonic(), deadline, "the menu never started again")
                time.sleep(0.05)
            self.assertIn("› 2  beta", menu.wait("esc leave"))
            menu.keys("Escape")
            self.assertEqual(menu.exit_code(), 0)


if __name__ == "__main__":
    unittest.main()
