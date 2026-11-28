"""Every page comes up as a page `c` opens does (motion.Clock.rise): the company list, its
`add a company`, `why`, the list a harness adds a model from, a card, a new seat's row, its caret,
and the line under it, a working seat's plan line beside them, are each written, as they open,
a frame whose text is part way from the background, or the highlight it is on, to its colour
before the one at rest; a key that changes nothing read half way is answered at rest, and one
read at rest, a resize or a way back from the screen it opened draws it only at rest.  A mark
turned on or off on the company list is written half way before it is on or off: a dim `■` in
the open one's ink, the owner's font rule's for the task's `▣`
(tests/test_key_motion_every_font_carries.py).  The owner (10 Nov 2026): "make it animation
consistent. [...] We want ak to feel like one app."

Black-box: `AK_BIN`'s menu in a person's terminal (tests/fixtures/akterm.py) in every colour,
over tests/test_key_models_company_list.py's boards and harnesses and the OpenCode of
tests/test_key_lists_name_what_enter_does.py; its clock injected as in
tests/test_key_c_pages_come_up.py, each update's colours read from tmux's `pipe-pane`.  Fails
against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal
from test_key_a_screen_is_painted import BLACK
from test_key_lists_name_what_enter_does import OPENCODE
from fixtures.akboards import ENV
from test_key_models_company_list import boards
from test_key_models_on import MODELS

HALF = 0.075    # seconds: half the 0.15 a screen takes to come up (motion.FADE)
UPDATE = "\x1b[?2026l"      # a synchronized update's end: what it wrote shows at once
HIGHLIGHT = tuple(bytes.fromhex(BLACK[2]))      # the theme's selection, (r, g, b)
SIZES = (100, 40), (100, 41)    # the terminal's, a resize from one to the other
ENV = {**{name: value for name, value in ENV.items() if name != "NO_COLOR"},
       "COLORTERM": "truecolor"}      # every colour as it is, and no network but a dead proxy


def inks(out, text):
    """The colour, (r, g, b), each synchronized update in `out` that writes `text` leaves it in:
    its last write's in the update, which a person sees; None for the terminal's own."""
    fore, found, update = None, [], 0
    for part in re.finditer(rf"\x1b\[([\d;]*)m|({re.escape(UPDATE)})|({re.escape(text)})", out):
        if part[1] is not None:
            codes = [int(code or 0) for code in part[1].split(";")]
            while codes:
                code = codes.pop(0)
                if code in (0, 39):
                    fore = None
                elif code in (38, 48):      # a colour, its numbers after it
                    size = 4 if codes[:1] == [2] else 2
                    fore, codes = (tuple(codes[1:size]) if code == 38 else fore), codes[size:]
        elif part[2]:
            update = len(found)     # where the next update's goes
        else:
            found[update:] = [fore]
    return found


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EveryScreenComesUp(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakes = fakeadapter.install(self.home, claude="pass", codex="pass", opencode="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        fakes["codex"].answer("models", "bolt-3\tBolt 3\tlow medium high\ncrux-2\tCrux 2\tlow\n"
                                        "crux-flash-1\tCrux Flash 1\thigh\n")
        fakes["opencode"].script.write_text(fakes["opencode"].script.read_text().replace(
            "#!/bin/sh\n", "#!/bin/sh\n" + OPENCODE, 1))
        self.home.write(".agentkit/state/boards.json", boards())
        akconfig.write(self.home, {name: MODELS[name] for name in ("mid", "bolt", "flash")},
                       orchestrator="mid", workers=["flash"])
        self.clock, self.raw = self.home.root / "clock", self.home.root / "raw"
        self.at(1000)
        self.term = Terminal(self.home, size=SIZES[0],
                             env={"AK_MOTION_CLOCK": str(self.clock), **ENV})
        self.sized = 0
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        piped = self.home.tmux("pipe-pane", "-O", "-t", self.term.pane, f"cat >>{self.raw}",
                               server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)
        self.term.wait("esc leave")

    def at(self, seconds):
        """ak's motion at `seconds` from now on: its clock's file swapped whole, never read half
        written."""
        self.now = seconds
        new = self.clock.with_name("clock.new")
        new.write_text(repr(seconds))
        new.replace(self.clock)

    def inks(self, text, since, test=bool):
        """`inks` of `text` in what the pane was written from byte `since`, once it is written and
        `test` holds of them."""
        deadline = time.monotonic() + 30
        while not ((found := inks(self.raw.read_bytes()[since:].decode("utf-8", "replace"), text))
                   and test(found)):
            assert time.monotonic() < deadline, f"{text!r} never so; written in {found}"
            time.sleep(0.05)
        return found

    def comes_up(self, keys, text, still="x", lit=False):
        """`keys` pressed, the clock standing: `text` written in the background first, or the
        highlight's where it is `lit` on it, half way through the motion part way to its colour,
        and, once `still`, a key that changes nothing, is pressed there, in its colour, which it
        returns; `still` pressed again, and the screen then written whole on a resize, it is
        written only in that colour."""
        self.at(self.now + 100)
        since = self.raw.stat().st_size
        self.term.keys(*keys)
        background = self.inks(text, since)[0]
        self.at(self.now + HALF)
        half = self.inks(text, since, lambda found: found[-1] != background)[-1]
        self.term.keys(still)         # the clock still half way: the key ends the motion
        found = self.inks(text, since, lambda found: found[-1] != half)
        # the screen's background, every write's first colour, or the highlight it is lit on
        self.assertEqual(background, HIGHLIGHT if lit else tuple(map(int, re.search(
            rb"\x1b\[48;2;(\d+);(\d+);(\d+)", self.raw.read_bytes()).groups())), found)
        self.assertNotIn(found[-1], found[:found.index(half)])     # never at rest before
        self.assertTrue(all(min(b, r) <= h <= max(b, r)
                            for b, h, r in zip(background, half, found[-1])), found)
        self.assertNotIn(half, (background, found[-1]))
        # a key read before the resize is answered before it (terminal.read_key), so the whole
        # screen the resize writes is written after whatever that key's draw wrote
        self.as_it_is([still], text, found[-1], resized=True)
        return found[-1]

    def as_it_is(self, keys, text, ink, resized=False):
        """`keys` pressed, and the terminal then `resized`: `text` written again, only ever in
        `ink`."""
        since = self.raw.stat().st_size
        self.term.keys(*keys)
        if resized:
            self.sized = 1 - self.sized
            self.term.resize(*SIZES[self.sized])
        self.assertEqual(set(self.inks(text, since)), {ink})

    def test_the_company_list_and_your_runs_come_up_and_the_lists_marks_move_as_cs(self):
        self.term.keys("c")
        self.term.wait("r your runs")
        runs = self.comes_up(["r"], "Your team now")
        listed = self.comes_up(["p"], "Crux 2")
        since = self.raw.stat().st_size
        self.term.keys("Right", "Space")          # Acme Max 5 off, drawn half way
        self.inks("■", since)
        self.at(self.now + 10)
        empty = self.inks("□", since)[-1]
        for mark, ink in (("■", listed), ("□", empty)):       # on, and off again
            since = self.raw.stat().st_size
            self.term.keys("Space")
            # half way while the clock stands: the full shape in the open one's ink
            self.inks("■", since, lambda found: found[-1] == empty)
            self.at(self.now + 10)
            self.inks(mark, since, lambda found: found[-1] == ink)
        self.comes_up(["a"], "1 model")
        self.as_it_is(["Escape"], "Crux 2", listed)
        self.as_it_is(["Escape"], "Your team now", runs)

    def test_the_list_a_harness_adds_a_model_from_comes_up(self):
        self.term.keys("c")
        self.term.wait("r your runs")
        self.term.keys(*["Down"] * 4, "Enter")       # past the three models and `Models`
        self.term.wait("+ add a subscription")
        self.term.keys("Down", "Down")          # past ChatGPT
        self.term.wait("› + add a subscription")
        self.term.keys("Enter")
        self.term.wait("Claude II")
        self.term.keys(*["Down"] * 5)           # OpenCode's, the last
        self.term.wait("› another provider")
        self.comes_up(["Enter"], "Zeta Cloud")

    def test_a_card_asked_comes_up(self):
        self.term.keys("c")
        self.term.wait("r your runs")
        self.term.keys(*["Down"] * 4, "Enter")       # the page `+ add a subscription` is on
        self.term.wait("+ add a subscription")
        self.comes_up(["Right", "Right", "Enter"], "× Remove")   # `− remove` under the first

    def test_a_new_seats_row_comes_up(self):
        Seat(self.home, "acme", model="mid", screen="claude-working-pane.txt", planned=True)
        self.term.wait("0 of 1")      # its plan's line on screen, set up again on every draw
        # the row `n` makes, and the line it opens, on the highlight
        for text in ("▏", "build and review"):
            with self.subTest(text=text):
                self.comes_up(["n"], text, "Down", lit=True)
                self.term.keys("Escape")    # the row dropped, for `n` to make it again


if __name__ == "__main__":
    unittest.main()
