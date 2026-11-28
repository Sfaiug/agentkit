"""A reset spent on `Subscriptions` sends one light across its login's bar, as a seat just done.

The owner, 24 Nov 2026: a spent reset fills the bar and a light passes along it, like a seat
that is done.  `spend a reset` on the highlighted login, its adapter answering a Fable reset
spent (which leaves the week as it was): with the clock held inside `motion.SWEEP` of the page
coming back, that login's line differs from the same line once the clock is past it, in its
colours alone and inside its bar alone; past it, the line is the one a page opened afresh on
that home shows.  The adapter answering none spent, the line is that one at each of those
moments.  The screen is judged with the clock held at each of them, in the draw a reading of
login II landing then makes, never a frame between.

Black-box on tests/test_key_a_meter_glides_on_subscriptions.py's home, cache write, held clock
and line readers, and tests/test_key_claude_reset_in_the_menu.py's reset answer.  Fails against
`/bin/false`.
"""

import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import fakeadapter
from fixtures.akbin import REAL_TMUX
import test_key_a_meter_glides_on_subscriptions as glides
import test_key_claude_reset_in_the_menu as resets

SWEEP = 0.45                    # motion.SWEEP
BACK = 1003                     # the moment the page comes back from the spend
MOMENTS = (BACK, BACK + SWEEP / 2, BACK + SWEEP + 0.05)
SGR = re.compile(r"\x1b\[([\d;]*)m|(.)")
PART = re.compile(r"[34]8;(?:5;\d+|2;\d+;\d+;\d+)|\d+")     # of an SGR, a colour whole


def drawn(line):
    """Each cell of `line`, a row as tmux holds it with its colours: (character, the colours and
    attributes in force there).  tmux drops an attribute only by `0`."""
    cells, ink = [], {}
    for codes, char in SGR.findall(line):
        if char:
            cells.append((char, frozenset(ink.items())))
        for part in [] if char else PART.findall(codes) or ["0"]:
            kind = ("fg" if re.fullmatch(r"38;.*|3\d|9[0-7]", part)
                    else "bg" if re.fullmatch(r"48;.*|4\d|10[0-7]", part) else part)
            if part in ("0", "39", "49"):
                ink = {} if part == "0" else {k: v for k, v in ink.items() if k != kind}
            else:
                ink[kind] = part
    return cells


def bar(line):
    """Where login I's bar is on `line`, its cells counted from 0."""
    return range(*glides.FIRST.search(glides.CSI.sub("", line)).span(1))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SpentResetLightsItsMeter(unittest.TestCase):
    glide = glides.MeterGlidesOnSubscriptions
    home, read, at, opened, rows, written, line = (
        glide.home, glide.read, glide.at, glide.opened, glide.rows, glide.written, glide.line)

    def spend(self, answer, said, one=60):
        """`spend a reset` run on login I, `one`% left and holding one, its adapter answering
        `answer`, the clock held at BACK: its home and terminal, once the page back says
        `said`."""
        home = self.home(one, 70)
        fakeadapter.Adapter(Path(home.env["AGENTKIT_ADAPTER_DIR"]), "claude").answer(
            "reset", json.dumps(answer))
        term = self.opened(home)
        term.keys("Right")
        term.wait("⏎ spend a reset")
        self.at(home, BACK)
        term.keys("Enter")
        term.wait(said)
        return home, term

    def held(self, home, term, moment, two, one=60):
        """Login I's line, colours and all, with the clock held at `moment`: once login II, read
        `two`% left then, is said, which only a draw after it can say, and that draw writes its
        first frame in the same update (terminal.written), the screen is of `moment`."""
        self.at(home, moment)
        self.written(home, term, one, two, f"{two}% left")
        return self.line(term, "Claude I", colours=True)

    def afresh(self, home, term):
        """Login I's line on the page opened again on the home as it is, come up whole."""
        term.keys("Escape")
        term.wait("› Subscriptions")
        term.keys("Enter")
        term.wait("› Claude I ")
        self.at(home, BACK + 2)
        term.wait(lambda screen: glides.PAGE in screen.splitlines()[0], bound=10)
        return self.line(term, "Claude I", colours=True)

    def test_a_reset_spent_sends_one_light_across_its_bar(self):
        home, term = self.spend(resets.fable_spent(), "Claude I · 60% left · Fable 100%")
        lit, rest = self.held(home, term, MOMENTS[1], 71), self.held(home, term, MOMENTS[2], 72)
        cells, still = drawn(lit), drawn(rest)
        self.assertEqual([char for char, _ in cells], [char for char, _ in still])
        moved = {n for n, (one, other) in enumerate(zip(cells, still)) if one != other}
        self.assertTrue(moved)
        self.assertLessEqual(moved, set(bar(rest)))
        self.assertEqual(rest, self.afresh(home, term))

    def test_a_spend_answered_none_spent_leaves_the_line_as_a_page_opened_afresh(self):
        home, term = self.spend({"code": "cooldown"}, "Claude I: no reset was spent")
        shown = [self.held(home, term, moment, two) for two, moment in enumerate(MOMENTS, 71)]
        self.assertEqual(shown, [self.afresh(home, term)] * len(MOMENTS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
