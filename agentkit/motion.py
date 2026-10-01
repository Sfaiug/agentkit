"""The one animation clock: which cells move, and what each shows at every frame.

At rest one thing moves, a working session's `●` breathing; news moves once and is then still --
a `!` that turned `needs you` pulses twice, a `✓` that turned `done` settles from bright, a bar
that changed value glides to it, an effort's bar a step filled rises into place and a step onto
a model's highest effort sends a light through its word, a mark set fills and one cleared
empties, one whose change was refused shakes, a row just added glows; a popup's content fades in
once, as it opens; the rule under a screen's header glides while its content is fetched; a light
crosses a usage bar the pointer comes onto -- and every motion runs on this same clock
(docs/cli-design.md, Motion).  A screen says which cells
animate and how when it draws (`Clock.start`), asking first which of its values are news
(`Clock.look`); the wait loop asks how long until the next frame (`Clock.wait`) and what to
write then (`Clock.frame`), and a key ends what moves on its last frame (`Clock.settle`).  No
screen keeps a timer: time, easing and the running animations live here, and cells animated
alike are in one phase because each reads one clock.
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
SWEEP = 0.4         # ... the light takes across a bar that reached full, after the glide, or
                    # one the pointer came onto
RISE = 0.15         # ... an effort's bar a step filled takes to rise into place, or to lower
SHIMMER = 0.6       # ... the light takes through an effort's word that a step took to its highest
TOGGLE = 0.08       # ... a mark takes to fill or to empty, half way for the first half of it
SHAKE = 0.24        # ... a mark whose change was refused takes to nudge left, right, left and back
GLOW = 1.0          # ... a row just added takes to fade from its glow into the highlight
GLOWING = 0.6       # that glow at first: the accent that far toward the background
HALF = {"□": "▣", "■": "▣", "○": "◉", "●": "◉"}     # a mark half way between empty and full
BRIGHTER = 0.5      # how lit news is: half way from its colour to the foreground
FADE = 0.12         # seconds a popup's content takes to come up out of the background
WAIT = 0.15         # ... a screen's content is fetched for before its rule says so
LAP = 1.2           # ... the segment on that rule takes along it, and again, until it lands
SEGMENT = 8         # cells that segment is long
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


def rising(bar, up, began, bright=False):
    """One of an effort's bars (terminal.signal), `bar` its glyph, that a step at `began` filled
    -- `up` -- or emptied: it rises from nothing into place in RISE seconds, or lowers from its
    height to nothing, and is then as the draw wrote it, dim where it is empty; and when it is
    still.  `bright` on the highlighted row."""
    height = terminal.SIGNAL.index(bar) + 1

    def at(now):
        x = eased((now - began) / RISE)
        if x >= 1:
            text = bar if up else terminal.styled(bar, "dim")
        else:
            eighths = round(height * (x if up else 1 - x))
            text = terminal.SIGNAL[eighths - 1] if eighths else " "
        return terminal.highlight(text, mark=False) if bright else text
    return at, began + RISE


def shimmering(word, began, kind=None, bright=False):
    """An effort's `word` that a step at `began` took to its model's highest: one light through
    it, a letter at a time left to right, in SHIMMER seconds, and then as the draw wrote it; and
    when it is still.  The word is written whole from its first cell, so a letter two cells wide
    keeps both.  `kind` is how the draw styled it -- `reverse` where the highlight's cell is,
    `dim` on a spent model's row -- and `bright` is the highlighted row."""
    light = terminal.faded("working", -BRIGHTER)

    def at(now):
        lit = int(len(word) * (now - began) / SHIMMER)
        dark, shone, rest = word[:lit], terminal.styled(word[lit:lit + 1], light), word[lit + 1:]
        if kind:
            dark, rest = terminal.styled(dark, kind), terminal.styled(rest, kind)
        if kind == "reverse":
            shone = terminal.styled(shone, kind)
        text = dark + shone + rest
        return terminal.highlight(text, mark=False) if bright else text
    return at, began + SHIMMER


def toggled(mark, width, kind, bright, column):
    """How a mark drawn `mark` -- terminal.toggle's, `width` cells from the screen's `column`, in
    `kind` -- moves on a screen's clock once it is news: one set or cleared fills or empties
    through its half (`□ ▣ ■`, `○ ◉ ●`) in TOGGLE seconds, two frames; one whose change was
    refused, news that changed nothing (`Clock.touch`), nudges a cell left, right, left and back
    in SHAKE seconds.  `bright` is the highlighted row, and the pointer's cell is lit as the draw
    lit it (terminal.pointed).  A function of the clock, the screen row, when the news came and
    the mark before it."""
    def start(clock, row, since, before):
        def drawn(text, first):     # as a draw shows it from column `first`
            return terminal.pointed(row, first,
                                    terminal.highlight(text, mark=False) if bright else text)
        if before == mark:
            def at(now):
                shift = (-1, 1, -1, 0)[min(3, int(4 * (now - since) / SHAKE))]
                return drawn(" " * (1 + shift) + terminal.toggle(mark, width, kind)
                             + " " * (1 - shift), column - 1)
            clock.start([(row, column - 1)], at, since + SHAKE)
        elif before in HALF and mark in HALF:
            def at(now):
                return drawn(terminal.toggle(HALF[mark] if now - since < TOGGLE / 2 else mark,
                                             width, kind), column)
            clock.start([(row, column)], at, since + TOGGLE)
    return start


def glowing(line):
    """How a row just added moves on a screen's clock, `line` as the draw wrote it: its cells on
    a soft glow of the accent that fades into the background in GLOW seconds, and then as
    drawn, the pointer's cell lit (terminal.pointed).  A function of the clock, the screen row,
    when it was added and what it was before."""
    def start(clock, row, since, _):
        lit = terminal.pointed(row, 1, line)

        def at(now):
            x = eased((now - since) / GLOW)
            rgb = terminal.faded("accent", GLOWING + (1 - GLOWING) * x)[1:]
            return lit if x >= 1 else terminal.backed(lit, rgb, 1, terminal.cells(lit))
        clock.start([(row, 1)], at, since + GLOW)
    return start


def glinting(bar, began, colour):
    """A usage bar the pointer came onto at `began`, `bar` its cells as the draw wrote each: one
    light crosses it a cell at a time left to right in SWEEP seconds, then each cell is as drawn;
    an animation for each cell, and when it is still.  `colour` is the kind its filled cells are
    drawn in, which the light is a brighter tone of."""
    light = terminal.faded(colour, -BRIGHTER)

    def cell(n, text):
        return lambda now: (terminal.styled(terminal.plain(text), light)
                            if n == int(len(bar) * (now - began) / SWEEP) else text)
    return [cell(n, text) for n, text in enumerate(bar)], began + SWEEP


def fetching(clock, began):
    """The rule under a screen's header, its second row, animated on `clock` while the screen's
    content is fetched from `began`, a cell each; `clock`.

    For WAIT seconds it is the rule as drawn -- a wait shorter than that shows nothing -- then a
    bright segment SEGMENT cells long glides along it, in from the left and out at the right in
    LAP seconds, and again; the screen draws the rule still once what it waits on has landed.
    """
    lit = terminal.styled("━", terminal.faded("working", -BRIGHTER))
    still, size = terminal.rule_line(1), terminal.layout_width()

    def cell(n):
        def at(now):
            t = now - began - WAIT
            head = eased(t % LAP / LAP) * (size + SEGMENT)
            return lit if t >= 0 and head - SEGMENT <= n < head else still
        return at
    for n in range(size):
        clock.start([(2, 1 + n)], cell(n))
    return clock


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
        self.touched = {}   # key -> since when it is news that changed nothing (`touch`)
        self.fade = fade    # what is drawn fades in over the first FADE seconds (`rise`): a popup
        self.opened = None  # ... from its first draw
        self.rising = None  # ... the lines drawn, top down, and that time, while they come up

    def look(self, values):
        """Which of `values` -- key -> what a draw shows for it -- are news, each key -> (since
        when, what it showed before): changed since the draw before this one, or still moving
        from a change before that.

        At first and after `forget` -- a resize, another screen -- every value is taken as it
        is, and so is one no draw before showed: only a change seen while the menu is up moves.
        A key touched is news since then, what it showed before being what it shows.
        """
        now, seen, self.seen = time.monotonic(), self.seen or {}, {}
        for key, value in values.items():
            was = seen.get(key)
            self.seen[key] = ((value, None, None) if was is None else was if was[0] == value
                              else (value, now, was[0]))
        news = {key: (since, before) for key, (_, since, before) in self.seen.items()
                if since is not None}
        news.update((key, (since, values[key])) for key, since in self.touched.items()
                    if key in values)
        return news

    def touch(self, key):
        """News at `key` from now that changed nothing: a mark whose change was refused, a row
        just added."""
        self.touched[key] = time.monotonic()

    def settle(self):
        """A key: whatever moves ends on its last frame, the next draw showing it still, and
        only what the key itself changes is news."""
        self.seen = self.seen and {key: (value, None, None)
                                   for key, (value, _, _) in self.seen.items()}
        self.touched = {}

    def drawn(self, moves, row):
        """A draw's frame: every cell it wrote over still, then each of its `moves` -- (line,
        key, value, start) -- that is news (`look`) started on the screen row `row(line)` puts
        it on, by `start(clock, row, since, before)`, None where it is not shown; the first
        frame, at the clock's phase so nothing jumps."""
        self.clear()
        news = self.look({key: value for _, key, value, _ in moves})
        for line, key, _, start in moves:
            if key in news and row(line) is not None:
                start(self, row(line), *news[key])
        return self.frame()

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
        self.seen, self.touched = None, {}

    def wait(self):
        """Seconds until the next frame is due, or None while nothing animates."""
        if not self.cells and not self.rising:
            return None
        return 0 if self.last is None else max(0, self.last + FRAME - time.monotonic())

    def frame(self):
        """What to write now: the lines still rising, or each cell whose text moved since it
        was last written, no other, with the pointer's light where it is (`terminal.pointed`)."""
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
                out += f"\033[{row};{column}H{terminal.pointed(row, column, text)}"
            if until is not None and now >= until:
                del self.cells[row, column]         # its last frame is out: still from here
        return out
