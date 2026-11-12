"""A mark fills through its own dim shape, and the spinner turns in cells the terminal draws.

The owner (10 Nov 2026): "in any terminal, on any operating system, ak should always look the
same."  A terminal borrows a character its font lacks from another font, at another size, and
few carry `▣`, `◉` or Braille: so half way, a mark set on `c` is its full shape in the ink its
open one has -- `□`, a dim `■`, `■` -- and one cleared goes the same way back; and the spinner
beside what ak waits on turns through the quadrants a terminal draws itself, `▖▘▝▗`.

Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) with its
colours, its harnesses the fakes of tests/fixtures/fakeadapter.py, Claude Code's catalog held
while the test needs it waited on.  Time is ak's own: the test reads what the pane is written,
in order, from tmux's `pipe-pane`, and a mark's inks from its own draws, never timing anything
off a capture, and it holds the wait until the spinner has turned, so the host's load can slow
what is read but not change it.  Fails against `/bin/false`.
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
BORROWED = re.compile("[▣◉\u2800-\u28ff]")     # the old half marks, and every Braille cell
LISTED = re.compile(r"(?m)^› +([□■]) (.+?) *$")    # the highlight on one of a harness's models
UPDATE = "\x1b[?2026l"     # the end of what the terminal shows at once


def turns(out):
    """The spinner's glyphs as written, the same one again left out."""
    glyphs = [char for char in out if char in TURN]
    return "".join(char for n, char in enumerate(glyphs) if not n or glyphs[n - 1] != char)


def drawn(mark, name):
    """`mark` as a draw writes it beside the model `name`: its ink alone, the group, no fade
    over it."""
    return rf"(\x1b\[[\d;]*m){mark}\x1b\[[\d;]*m {re.escape(name)}"


def shown(out, name, was):
    """The model `name`'s mark as each whole update the pane is written leaves it, from the first
    to change it from `was` -- its ink and the mark, from a draw beside its name or a frame in
    its column -- the same one again left out."""
    mark = re.compile(drawn("([■□])", name) + r"|(\x1b\[[\d;]*m) ([■□]) ")
    found = [was]
    for update in out.split(UPDATE)[:-1]:
        marks = [(ink or framed, glyph or alone)
                 for ink, glyph, framed, alone in mark.findall(update)]
        if marks and found[-1] != marks[-1]:
            found.append(marks[-1])
    return found[1:]


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
        self.term = Terminal(self.home, size=(100, 30))
        self.term.wait("esc leave")
        self.raw = self.home.root / "raw"
        piped = self.home.tmux("pipe-pane", "-O", "-t", self.term.pane, f"cat >>{self.raw}",
                               server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)
        self.term.keys("c", "j", "j", "Enter")
        self.term.wait("› Claude Code")

    def written(self, until, since=0):
        """What the pane was written from byte `since` once it holds `until`, a pattern or a test
        of it."""
        deadline = time.monotonic() + 30
        while True:
            out = (self.raw.read_bytes() if self.raw.exists() else b"")[since:].decode(
                "utf-8", "replace")
            if until(out) if callable(until) else re.search(until, out, re.S):
                return out
            assert time.monotonic() < deadline, f"never written {until!r}; written:\n{out!r}"
            time.sleep(0.05)

    def test_a_wait_turns_its_spinner_through_the_quadrants(self):
        self.held.touch()
        self.addCleanup(self.held.unlink, missing_ok=True)
        since = self.raw.stat().st_size
        self.term.keys("Enter")
        self.term.wait("reading the models claude offers")
        out = self.written(lambda out: TURN in turns(out), since)
        self.assertIsNone(BORROWED.search(out), out)

    def test_a_mark_fills_and_empties_through_its_full_shape_in_its_open_ink(self):
        self.term.keys("Enter")
        on = LISTED.search(self.term.wait(LISTED.search))
        while on[1] != "□":       # down to a model not taken in
            self.term.keys("j")
            on = LISTED.search(self.term.wait(
                lambda screen, at=on[2]: (found := LISTED.search(screen)) and found[2] != at))
        empty = re.findall(drawn("□", on[2]), self.written(drawn("□", on[2])))[-1]
        half = (empty, "■")

        since = self.raw.stat().st_size
        self.term.keys("Space")
        out = self.written(lambda out: half in (got := shown(out, on[2], (empty, "□")))
                           and got[-1] != half, since)
        full = re.findall(drawn("■", on[2]), out)[-1]      # as a draw has it at rest
        self.assertNotEqual(full, empty)
        self.assertEqual(shown(out, on[2], (empty, "□")), [half, (full, "■")])
        self.assertIsNone(BORROWED.search(out), out)

        since = self.raw.stat().st_size
        self.term.keys("Space")
        out = self.written(lambda out: half in (got := shown(out, on[2], (full, "■")))
                           and got[-1] != half, since)
        self.assertEqual(shown(out, on[2], (full, "■")), [half, (empty, "□")])
        self.assertIsNone(BORROWED.search(out), out)


if __name__ == "__main__":
    unittest.main()
