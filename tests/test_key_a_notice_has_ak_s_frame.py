"""A notice is drawn in ak's own frame, as everything else the menu says while it holds the screen.

The owner, 10 Nov 2026, over a notice printed at the shell's prompt above a bare `esc back`:
"Should always have the same pretty design and icons everywhere".  A job's result
(`~/.agentkit/state/update-result`) is the screen `agentkit · note`: its lines wrapped two spaces
in, `esc back` on the key line, Enter and Esc going on to the menu, which keeps its highlight;
one taller than the screen turns its pages with ↓ and ↑, so none of it is lost.  Left before the
menu opens or landing under it, it is shown once and on the menu's own screen, so leaving the
menu leaves none of it on the shell's.  Black-box: the program `AK_BIN` names, in
a person's terminal (tests/fixtures/akterm.py), beside tests/fixtures/akseat.py's seats; this
test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX
from fixtures.akterm import Terminal
from test_key_menu_notices import NOTICE, OPENS, ROWS, home_with_seats

WIDTH = 80
# Long enough to wrap at 80 columns.
LONG = ("update: agentkit moved to abc1234, and each seat takes the new code at its next turn "
        "without being stopped")


def shown(screen):
    return [line.rstrip() for line in screen.splitlines() if line.strip()]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ANoticeHasAksFrame(unittest.TestCase):
    def setUp(self):
        self.home = home_with_seats()
        self.addCleanup(self.home.close)

    def open(self):
        self.menu = Terminal(self.home, size=(WIDTH, 24))

    def leave(self, text):
        """Write the notice aside and move it into place, as orch.py does, so an open menu
        cannot read and remove an empty file mid-write."""
        self.home.write(NOTICE + ".part", text).replace(self.home.path / NOTICE)

    def note_frame(self):
        """One whole `agentkit · note` frame: header through `esc back`, with any rows of an
        earlier screen below it cleared."""
        return shown(self.menu.wait(
            lambda screen: (lines := shown(screen)) and lines[0].startswith("agentkit · note")
            and lines[-1] == "  esc back", bound=OPENS))

    def menu_back(self):
        """The main menu whole again after a note: header through `esc leave`, with any rows of
        the note below it cleared."""
        return self.menu.wait(
            lambda screen: (lines := shown(screen)) and lines[0].startswith("agentkit")
            and "agentkit · note" not in lines[0] and lines[-1].endswith("esc leave"))

    def note(self, said):
        """The note frame once up, read: `said` wrapped two spaces in under the header and its
        rule, `esc back` the key line."""
        lines = self.note_frame()
        self.assertRegex(lines[0], r"^agentkit · note +\d\d:\d\d$")
        self.assertEqual(set(lines[1]), {"─"})
        body, keys = lines[2:-1], lines[-1]
        self.assertTrue(all(line.startswith("  ") and len(line) <= WIDTH for line in body), body)
        self.assertEqual(" ".join(line.strip() for line in body), " ".join(said))
        self.assertEqual(keys, "  esc back")

    def left(self, said):
        """Esc on the menu: it ends, and the shell's screen holds no line of the notice `said`."""
        self.menu.keys("Escape")
        self.assertEqual(self.menu.exit_code(), 0)
        screen = self.menu.wait(lambda screen: "esc leave" not in screen)
        self.assertFalse([line for line in said if line in screen], screen)

    def test_a_result_left_before_the_menu_opens_is_its_first_screen_and_enter_goes_on(self):
        self.leave(f"{LONG}\n\nupdate: install.sh passed\n")
        self.open()
        self.note([LONG, "update: install.sh passed"])
        self.assertFalse((self.home.path / NOTICE).exists())    # shown once
        self.menu.keys("Enter")
        screen = self.menu_back()
        self.assertIn(ROWS, screen)
        self.assertNotIn("abc1234", screen)
        self.left(["update: install.sh passed"])

    def test_one_landing_under_the_open_menu_is_drawn_alike_and_esc_goes_back_to_its_row(self):
        self.open()
        self.menu.wait(ROWS, bound=OPENS)
        self.menu.keys("j")
        self.menu.wait("› 2  beta")
        # nothing pressed: the open menu reads its news as it draws again by itself
        self.leave("update: install.sh failed\n")
        self.note(["update: install.sh failed"])
        self.menu.keys("Escape")
        screen = self.menu_back()
        self.assertIn("› 2  beta", screen)
        self.assertFalse(self.menu.status.exists(), "Esc at the notice left the menu")
        self.left(["update: install.sh failed"])

    def test_a_notice_taller_than_the_screen_turns_its_pages_to_its_last_line_and_back(self):
        said = [f"WARN notice {n:02}: acme could not finish" for n in range(30)]
        self.leave("\n".join(said) + "\n")
        self.open()
        first = self.note_frame()
        self.assertEqual(first[2], "  " + said[0])
        self.assertNotIn("  " + said[-1], first)
        self.menu.keys(*["Down"] * len(said))      # a page at a time, never past the last
        self.menu.wait(lambda screen: shown(screen)[-2:] == ["  " + said[-1], "  esc back"])
        self.menu.keys(*["Up"] * len(said))        # and back to its first
        self.menu.wait(lambda screen: shown(screen)[1:] == first[1:])
        self.menu.keys("Enter")
        self.assertIn(ROWS, self.menu_back())
        self.left(said)


if __name__ == "__main__":
    unittest.main()
