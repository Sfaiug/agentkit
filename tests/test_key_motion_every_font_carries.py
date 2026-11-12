"""A mark fills through its own dim shape, and the spinner turns in cells the terminal draws.

The owner (10 Nov 2026): "in any terminal, on any operating system, ak should always look the
same."  A terminal borrows a character its font lacks from another font, at another size, and
few carry `▣`, `◉` or Braille: so half way, a mark set on `c` is its full shape in the ink its
open one has -- `□`, a dim `■`, `■` -- and one cleared goes the same way back; and the spinner
beside what ak waits on turns through the quadrants a terminal draws itself, `▖▘▝▗`.

Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) with its
colours, its harnesses the fakes of tests/fixtures/fakeadapter.py, Claude Code's catalog held
while the test needs it waited on.  Its clock injected: `AK_MOTION_CLOCK` names a file of seconds
that stands still until the test moves it, so each motion is read off the screen at the moment
set, however late the host's load makes a frame; every byte the pane is written, from tmux's
`pipe-pane`, is looked through for a borrowed character.  Fails against `/bin/false`.
"""

import re
import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

TURN = "▖▘▝▗"
SPIN = 0.1      # seconds each of the spinner's glyphs shows (motion.SPIN)
BORROWED = re.compile("[▣◉\u2800-\u28ff]")     # the old half marks, and every Braille cell
LISTED = re.compile(r"(?m)^› +([□■]) (.+?) *$")    # the highlight on one of a harness's models
SGR = r"\x1b\[[\d;]*m"


def marked(screen, name):
    """The highlighted mark beside the model `name` on a screen captured in colour, or None: the
    escapes tmux writes before it, which say what changes from the plain space before it in
    every form a mark is drawn in, then the mark."""
    for line in screen.splitlines():
        plain = re.sub(SGR, "", line).rstrip()
        if plain.startswith("› ") and plain.endswith(" " + name):
            found = re.search(rf"((?:{SGR})*) ?([□■])", line)
            return found and found.groups()
    return None


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MotionEveryFontCarries(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        claude = fakeadapter.install(self.home, claude="pass", codex="pass")["claude"]
        self.held = claude.dir / "models.held"      # its catalog waits while this is there
        claude.script.write_text(claude.script.read_text().replace("exec ", (
            f'[ "$1" = models ] && while [ -e {shlex.quote(str(self.held))} ]; do sleep 0.05; '
            "done\nexec "), 1))
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"})
        self.clock = self.home.root / "clock"
        self.at(1000)
        self.term = Terminal(self.home, size=(100, 30), env={"AK_MOTION_CLOCK": str(self.clock)})
        self.term.wait("esc leave")
        self.raw = self.home.root / "raw"
        piped = self.home.tmux("pipe-pane", "-O", "-t", self.term.pane, f"cat >>{self.raw}",
                               server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)
        self.term.keys("c", "j", "j", "Enter")
        self.term.wait("› Claude Code")

    def at(self, seconds):
        """ak's motion at `seconds` from now on: its clock's file swapped whole, never read half
        written."""
        self.now = seconds
        new = self.clock.with_name("clock.new")
        new.write_text(repr(seconds))
        new.replace(self.clock)

    def shows(self, name, test):
        """The highlighted mark beside `name`, as `marked` reads it, once `test` holds of it."""
        deadline = time.monotonic() + 30
        while not ((got := marked(self.term.screen(colours=True), name)) and test(*got)):
            assert time.monotonic() < deadline, f"{name}'s mark never passed; it is {got!r}"
            time.sleep(0.05)
        return got

    def assertNothingBorrowed(self):
        out = self.raw.read_bytes().decode("utf-8", "replace")
        self.assertIsNone(BORROWED.search(out), out)

    def test_a_wait_turns_its_spinner_through_the_quadrants(self):
        self.held.touch()
        self.addCleanup(self.held.unlink, missing_ok=True)
        self.term.keys("Enter")         # the wait begins now, on the clock as it stands
        for n, glyph in enumerate(TURN):
            self.at(1000 + (n + 0.5) * SPIN)
            self.term.wait(f"{glyph} reading the models claude offers")
        self.assertNothingBorrowed()

    def test_a_mark_fills_and_empties_through_its_full_shape_in_its_open_ink(self):
        self.term.keys("Enter")
        on = LISTED.search(self.term.wait(LISTED.search))
        self.at(self.now + 10)          # the page and its list up; the clock moves past each key
        while on[1] != "□":       # down to a model not taken in
            self.term.keys("j")
            on = LISTED.search(self.term.wait(
                lambda screen, at=on[2]: (found := LISTED.search(screen)) and found[2] != at))
        empty, _ = self.shows(on[2], lambda ink, mark: mark == "□")

        self.term.keys("Space")         # half way while the clock stands
        self.shows(on[2], lambda ink, mark: (ink, mark) == (empty, "■"))
        self.at(self.now + 10)
        full, _ = self.shows(on[2], lambda ink, mark: mark == "■" and ink != empty)

        self.term.keys("Space")
        self.shows(on[2], lambda ink, mark: (ink, mark) == (empty, "■"))
        self.at(self.now + 10)
        self.shows(on[2], lambda ink, mark: (ink, mark) == (empty, "□"))
        self.assertNothingBorrowed()


if __name__ == "__main__":
    unittest.main()
