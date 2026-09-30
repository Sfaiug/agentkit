"""The one animation clock: which cells move, and what each shows at every frame.

At rest one thing moves, a working session's `●` breathing, and every motion after it runs on
this same clock (docs/cli-design.md, Motion).  A screen says which cells animate and how when
it draws (`Clock.start`); the wait loop asks how long until the next frame (`Clock.wait`) and
what to write then (`Clock.frame`).  No screen keeps a timer: time, easing and the running
animations live here, and cells animated alike are in one phase because each reads one clock.
"""

import math
import time

from . import terminal

FRAME = 1 / 20      # at most twenty frames a second
BREATH = 2.0        # seconds a breathing cell takes out to its dimmer tone and back
DIMMER = 0.5        # ... that tone: half way from its colour to the background


def breath(now):
    """0 at the colour, 1 at its dimmer tone, and back once every BREATH seconds of the clock:
    a sine, so the colour eases into every turn instead of bouncing off it."""
    return (1 - math.cos(2 * math.pi * now / BREATH)) / 2


def breathing(glyph, word, bright=False):
    """The animation of a cell that breathes: `glyph` in `word`'s colour, `bright` on the
    highlighted row, where every cell is."""
    def at(now):
        text = terminal.styled(glyph, terminal.faded(word, DIMMER * breath(now)))
        return terminal.highlight(text, mark=False) if bright else text
    return at


class Clock:
    """The running animations, each cell's, and what was last written in each."""

    def __init__(self):
        self.cells = {}     # (row, column), counted from 1 -> its animation: a time to its text
        self.shown = {}     # (row, column) -> the text last written there
        self.last = None    # when the last frame was made

    def start(self, cells, animation):
        """Animate `cells` by `animation`, a function of the clock's time to what a cell shows.

        Nothing moves where colour cannot: off a terminal, under NO_COLOR, at eight colours.
        """
        if terminal.colour_depth() > 8:
            self.cells.update(dict.fromkeys(cells, animation))

    def clear(self):
        """Nothing animates and nothing is shown: a draw has written every cell over."""
        self.cells, self.shown = {}, {}

    def wait(self):
        """Seconds until the next frame is due, or None while nothing animates."""
        if not self.cells:
            return None
        return 0 if self.last is None else max(0, self.last + FRAME - time.monotonic())

    def frame(self):
        """What to write now: each cell whose text moved since it was last written, no other."""
        now = self.last = time.monotonic()
        out = ""
        for (row, column), animation in self.cells.items():
            text = animation(now)
            if self.shown.get((row, column)) != text:
                self.shown[row, column] = text
                out += f"\033[{row};{column}H{text}"
        return out
