"""The menu shows a notice until the owner has read it, and starts again on new code.

A finished background job leaves its lines in `~/.agentkit/state/update-result`; the menu shows
them once, before it draws, and on a terminal waits for Enter or Esc, so a notice that lands
under an open menu is read, not lost behind the next frame.  From a pipe nobody is there to
wait for.  An install newer than the open menu (`~/.agentkit/state/installed-at`, which
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


def shown(screen):
    return [line.rstrip() for line in screen.splitlines() if line.strip()]


def home_with_seats():
    home = Home()
    akconfig.write(home, ["opus"])
    made = int(time.time()) - 900
    for at, name in enumerate(("acme", "beta")):
        Seat(home, name, record={"created": made + 60 * at})
    return home


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Notices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home_with_seats()
        cls.addClassCleanup(cls.home.close)

    def menu(self):
        menu = Terminal(self.home, size=(80, 24))
        self.addCleanup(menu.exit_code)
        self.addCleanup(menu.keys, "Escape")
        return menu

    def test_a_notice_is_shown_before_the_menu_until_enter(self):
        self.home.write(NOTICE, "update: agentkit moved to abc1234\n\nupdate: install.sh passed\n")
        menu = self.menu()
        self.assertEqual(shown(menu.wait("esc back", bound=OPENS)),
                         [" update: agentkit moved to abc1234", " update: install.sh passed",
                          "esc back"])
        self.assertFalse((self.home.path / NOTICE).exists())    # shown once
        menu.keys("Enter")
        self.assertIn(ROWS, menu.wait("esc leave"))

    def test_a_notice_landing_under_the_open_menu_waits_and_esc_goes_back_to_it(self):
        menu = self.menu()
        menu.wait(ROWS, bound=OPENS)
        menu.keys("j")
        menu.wait("› 2  beta")
        # nothing pressed, as a key could come after the notice and be typed at its `esc back`:
        # the open menu draws again by itself (`menu.TICK`), reading its news first
        self.home.write(NOTICE, "update: install.sh failed\n")
        self.assertEqual(shown(menu.wait("esc back"))[-2:],
                         [" update: install.sh failed", "esc back"])
        menu.keys("Escape")
        screen = menu.wait("esc leave")
        self.assertIn("› 2  beta", screen)
        self.assertFalse(menu.status.exists(), "Esc at the notice left the menu")

    def test_from_a_pipe_a_notice_is_printed_whole_at_words_and_waits_for_nobody(self):
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
