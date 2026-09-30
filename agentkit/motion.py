"""The one animation clock: which cells move, and what each shows at every frame.

At rest one thing moves, a working session's `●` breathing; news moves once and is then still --
a `!` that turned `needs you` pulses twice, a `✓` that turned `done` settles from bright, a bar
that changed value glides to it -- and a popup's content fades in once, as it opens -- and every
motion runs on this same clock (docs/cli-design.md, Motion).  A screen says which cells animate and how when it draws (`Clock.start`), asking first
which of its values are news (`Clock.look`); the wait loop asks how long until the next frame
(`Clock.wait`) and what to write then (`Clock.frame`).  No screen keeps a timer: time, easing
and the running animations live here, and cells animated alike are in one phase because each
reads one clock.
"""

import math
import time

from . import terminal

FRAME = 1 / 20      # at most twenty frames a second
BREATH = 2.0        # seconds a breathing cell takes out to its dimmer tone and back
DIMMER = 0.5        # ... that tone: half way from its colour to the background
PULSE = 0.3         # seconds each of the two pulses of a `!` that turned `needs you` takes
SETTLE = 0.4        # ... a `✓` that turned `done` takes from bright to its colour
GLIDE = 0.3         # ... a bar takes from its old value to its new one
LIT = 0.3           # ... a task bar's newly filled block stays lit after the glide
SWEEP = 0.4         # ... the light takes across a bar that reached full, after the glide
BRIGHTER = 0.5      # how lit news is: half way from its colour to the foreground
FADE = 0.12         # seconds a popup's content takes to come up out of the background
PARTS = "▏▎▍▌▋▊▉"   # a bar's cell one to seven eighths full, as a glide passes through it


def breath(now):
    """0 at the colour, 1 at its dimmer tone, and back once every BREATH seconds of the clock:
    a sine, so the colour eases into every turn instead of bouncing off it."""
    return (1 - math.cos(2 * math.pi * now / BREATH)) / 2


def eased(x):
    """0 to 1 as `x` goes from 0 to 1, slow out of the one and into the other."""
    return (1 - math.cos(math.pi * min(1, max(0, x)))) / 2


def tinted(glyph, word, amount, bright=False):
    """`glyph` in `word`'s colour `amount` of the way to the background, or toward the foreground
    where `amount` is below 0: bold where the word is, and `bright` on the highlighted row,
    where every cell is."""
    text = terminal.styled(glyph, terminal.faded(word, amount))
    bold = bright or terminal.STATE_STYLES[word][4] == "1"
    return terminal.highlight(text, mark=False) if bold else text


def breathing(glyph, word, bright=False):
    """The animation of a cell that breathes: `glyph` in `word`'s colour, `bright` on the
    highlighted row."""
    return lambda now: tinted(glyph, word, DIMMER * breath(now), bright)


def pulsing(glyph, word, began, bright=False):
    """A cell that turned `word` at `began`: two soft pulses toward the light, PULSE seconds
    each, then still in its colour; and when it is still."""
    def at(now):
        pulse = (1 - math.cos(2 * math.pi * min(now - began, 2 * PULSE) / PULSE)) / 2
        return tinted(glyph, word, -BRIGHTER * pulse, bright)
    return at, began + 2 * PULSE


def settling(glyph, word, began, bright=False):
    """A cell that turned `word` at `began`: bright at once, easing to its colour in SETTLE
    seconds; and when it is still."""
    def at(now):
        return tinted(glyph, word, -BRIGHTER * (1 - eased((now - began) / SETTLE)), bright)
    return at, began + SETTLE


def gliding(before, after, began, colour=None, bright=False, sweep=False):
    """A bar drawn `before` and now `after`, each its blocks as a draw writes them (`███░░`),
    from `began`: an animation for each of its cells, left to right, and when it is still.

    Its filled end glides from the one to the other in GLIDE seconds, an eighth of a cell at a
    time where the blocks are `█`.  On a plain bar -- a seat's tasks -- each block it newly
    fills lights, until LIT seconds after the glide; and with `sweep`, its value just reached
    full, one light crosses it a cell at a time left to right in the SWEEP seconds after the
    glide, the only light then.  `colour` is the kind a coloured bar's filled blocks are drawn
    in, its empty ones dim, and None a plain bar's.  Each cell's last frame is that cell as the
    draw wrote it.
    """
    full, empty = "█░" if set(after) <= set("█░") else "#-"
    size, was, filled = len(after), before.count(full), after.count(full)
    new = colour is None and filled > was
    light = terminal.faded(colour or "working", -BRIGHTER)

    def cell(n):
        def at(now):
            t = now - began
            reached = was + (filled - was) * eased(t / GLIDE)
            eighths = round(reached * 8) - 8 * n if full == "█" else 8 * (round(reached) - n)
            block = full if eighths >= 8 else PARTS[eighths - 1] if eighths > 0 else empty
            if (new and was <= n < reached and t < GLIDE + (0 if sweep else LIT)
                    or sweep and GLIDE <= t < GLIDE + SWEEP
                    and n == int(size * (t - GLIDE) / SWEEP)):
                kind = light
            else:
                kind = colour if block != empty else colour and "dim"
            text = terminal.styled(block, kind) if kind else block
            return terminal.highlight(text, mark=False) if bright else text
        return at
    return ([cell(n) for n in range(size)],
            began + GLIDE + (SWEEP if sweep else LIT if new else 0))


class Clock:
    """The running animations, each cell's, what was last written in each, and what the draws
    showed that may be news."""

    def __init__(self, fade=False):
        self.cells = {}     # (row, column), counted from 1 -> its animation, a time to its text,
                            # and the time it is still from, or None for as long as it is drawn
        self.shown = {}     # (row, column) -> the text last written there
        self.last = None    # when the last frame was made
        self.seen = None    # key -> what the last draw showed, and since when and in place of
                            # what when that was news; None when no draw is to be compared with
        self.fade = fade    # what is drawn fades in over the first FADE seconds (`rise`): a popup
        self.opened = None  # ... from its first draw
        self.rising = None  # ... the lines drawn, top down, and that time, while they come up

    def look(self, values):
        """Which of `values` -- key -> what a draw shows for it -- are news, each key -> (since
        when, what it showed before): changed since the draw before this one, or still moving
        from a change before that.

        At first and after `forget` -- a resize, another screen -- every value is taken as it
        is, and so is one no draw before showed: only a change seen while the menu is up moves.
        """
        now, seen, self.seen = time.monotonic(), self.seen or {}, {}
        for key, value in values.items():
            was = seen.get(key)
            self.seen[key] = ((value, None, None) if was is None else was if was[0] == value
                              else (value, now, was[0]))
        return {key: (since, before) for key, (_, since, before) in self.seen.items()
                if since is not None}

    def start(self, cells, animation, until=None):
        """Animate `cells` by `animation`, a function of the clock's time to what a cell shows,
        until `until` -- then its last frame is written and it is still -- or while it is drawn.

        Nothing moves where colour cannot: off a terminal, under NO_COLOR, at eight colours;
        and news whose time is over does not move again.
        """
        if terminal.colour_depth() > 8 and (until is None or until > time.monotonic()):
            self.cells.update(dict.fromkeys(cells, (animation, until)))

    def rise(self, lines):
        """Whether `lines`, a draw's screen top down, come up out of the background, the frames
        writing them and nothing else until they are up: on a clock made to `fade`, where
        colour can move, whatever is drawn in the FADE seconds from its first draw -- a key's
        draw at once, and news -- each from where the fade has got to.
        """
        now = time.monotonic()
        if self.fade and terminal.colour_depth() > 8:
            self.opened = now if self.opened is None else self.opened
            if now < self.opened + FADE:
                self.rising = (lines, self.opened)
        return self.rising is not None

    def clear(self):
        """Nothing animates and nothing is shown: a draw has written every cell over."""
        self.cells, self.shown, self.rising = {}, {}, None

    def forget(self):
        """Nothing seen: the next draw's values are drawn as they are, no news in them."""
        self.seen = None

    def wait(self):
        """Seconds until the next frame is due, or None while nothing animates."""
        if not self.cells and not self.rising:
            return None
        return 0 if self.last is None else max(0, self.last + FRAME - time.monotonic())

    def frame(self):
        """What to write now: the lines still rising, or each cell whose text moved since it
        was last written, no other."""
        now = self.last = time.monotonic()
        out = ""
        if self.rising:
            lines, began = self.rising
            amount = 1 - eased((now - began) / FADE)
            out = "".join(f"\033[{row};1H{terminal.fade(line, amount)}"
                          for row, line in enumerate(lines, 1))
            if amount > 0:
                return out
            self.rising, self.shown = None, {}      # up, as drawn: every cell is written over it
        for (row, column), (animation, until) in list(self.cells.items()):
            text = animation(now)
            if self.shown.get((row, column)) != text:
                self.shown[row, column] = text
                out += f"\033[{row};{column}H{text}"
            if until is not None and now >= until:
                del self.cells[row, column]         # its last frame is out: still from here
        return out
