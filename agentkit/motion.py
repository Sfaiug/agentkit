"""The one animation clock: which cells move, and what each shows at every frame.

At rest only what a model works on moves, breathing: a working session's `●`, the tip of its line
and its moving tasks' squares (`menu.tips`), a light going round its line while it has no plan
yet; news moves once and is then still --
a `!` that turned `needs you` pulses twice, a `✓` that turned `done` settles from bright and a
light crosses its line, either's row glowing in its word's colour as it fades; the line a row
opens comes up as the highlight comes to it, a question the first time it is shown writing
itself out, and a page's rows as it is turned to; each
progress line grows to its length as the menu opens and glides to a new one as its plan moves,
its count counting up with it, a task's next square fills through its half and one that failed
nudges; an effort's bar a step filled rises into place and a step onto a model's highest effort sends a light
through its word, a mark set fills and one cleared empties, one whose change was refused shakes;
a popup's content fades in once, as it opens, and a page's under its
header as it opens, its name writing itself out in the header; the rule under a screen's
header glides while its content is fetched, a spinner turning beside what ak waits on; a
subscription the pointer comes onto washes into its company's colour, its models with it, and
drains when it leaves -- and every motion runs on this same clock
(docs/cli-design.md, Motion).  A screen says which cells animate and how when it draws
(`Clock.start`), asking first which of its values are news
(`Clock.look`); the wait loop asks how long until the next frame (`Clock.wait`) and what to
write then (`Clock.frame`), and a key ends what moves on its last frame (`Clock.settle`).  No
screen keeps a timer: time, easing and the running animations live here, and cells animated
alike are in one phase because each reads one clock.
"""

import math
import re
import time

from . import terminal

FRAME = 1 / 20      # at most twenty frames a second
BREATH = 2.0        # seconds a breathing cell takes out to its dimmer tone and back
DIMMER = 0.5        # ... that tone: half way from its colour to the background
PULSE = 0.3         # seconds each of the two pulses of a `!` that turned `needs you` takes
SETTLE = 0.4        # ... a `✓` that turned `done` takes from bright to its colour
RISE = 0.15         # ... an effort's cell a step filled takes to light and settle, or to empty
SHIMMER = 0.6       # ... the light takes through an effort's word that a step took to its highest
TOGGLE = 0.08       # ... a mark takes to fill or to empty, half way for the first half of it
SHAKE = 0.24        # ... a mark whose change was refused takes to nudge left, right, left and back
GLOW = 1.0          # ... a seat's row on news takes to fade from its glow
NEWS = 0.7          # ... and a seat's row on news: its word's colour that far toward it
SWEEP = 0.4         # seconds a light takes across a done seat's line
OPEN = 0.12         # ... the line under a row the highlight came to takes to come up
TURN = 0.15         # ... and the rows of a page turned to
WRITE = 0.33        # ... a question shown the first time takes to write itself out
GROW = 0.45         # ... a seat's progress line takes to grow to its length as ak opens
STAGGER = 0.04      # ... and each row after the one above it
GLIDE = 0.7         # ... and to glide to a new length as its plan moves, a light at its head
ROUND = 2.0         # ... a light takes along a working seat's line with no plan yet, and again
STEP = 0.15         # ... a task's next square takes to fill, through its half
HALF = {"□": "▣", "■": "▣", "○": "◉", "●": "◉"}     # a mark half way between empty and full
BRIGHTER = 0.5      # how lit news is: half way from its colour to the foreground
FADE = 0.12         # seconds a popup's content takes to come up out of the background
WAIT = 0.15         # ... a screen's content is fetched for before its rule says so
LAP = 1.2           # ... the segment on that rule takes along it, and again, until it lands
SEGMENT = 8         # cells that segment is long
SPIN = 2 * FRAME    # seconds each of the spinner's glyphs shows beside what ak waits on
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"   # cli-spinners' dots, and `|/-\` without UTF-8
WASH = 0.3          # seconds a subscription's colour takes to wash in under the pointer
DRAIN = 0.2         # ... and to drain once the pointer leaves it
EDGE = 0.4          # how lit the edge of that wash is: that far toward the foreground


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


def filling(up, began, bright=False):
    """One of an effort's cells (terminal.effort_cells) that a step filled -- `up` -- or emptied,
    its turn at `began`: as it was until then, for the first half of RISE seconds a filled one
    lit and an emptied one still full but dim, and then as the draw wrote it; and when it is
    still.  `bright` on the highlighted row."""
    full, empty = terminal.effort_cells(2, 1)        # each as a draw writes it
    shown = terminal.plain(full)
    middle = terminal.styled(shown, terminal.faded("working", -BRIGHTER) if up else "dim")

    def at(now):
        text = ((empty if up else full) if now < began else
                middle if now < began + RISE / 2 else full if up else empty)
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
        def drawn(first, at, until):     # as a draw shows it from column `first`
            clock.start([(row, first)], lambda now: terminal.pointed(row, first, at(now)), until)
        shown = terminal.toggle(mark, width, kind)
        if before == mark:
            drawn(column - 1, *nudging(shown, since, bright))
        elif before in HALF and mark in HALF:
            drawn(column, *halving(shown, since, TOGGLE, bright))
    return start


def refused(text, value, column):
    """How a knob drawn `text` from the screen's `column`, showing `value`, moves on a screen's
    clock once a step of it was refused, news that changed nothing (`Clock.touch`): it nudges a
    cell left, right, left and back in SHAKE seconds (`nudging`)."""
    def start(clock, row, since, before):
        if before == value:
            clock.start([(row, column - 1)], *nudging(text, since))
    return start


def glowing(line, kind, amount):
    """How a seat's row on news moves on a screen's clock, `line` as the draw wrote it: its cells on
    a soft glow of `kind`'s colour, `amount` of the way to the background, that fades into the
    background in GLOW seconds, and then as drawn, the pointer's cell lit (terminal.pointed).
    A function of the clock, the screen row, when it was news and what it was before."""
    def start(clock, row, since, _):
        lit = terminal.pointed(row, 1, line)

        def at(now):
            x = eased((now - since) / GLOW)
            rgb = terminal.faded(kind, amount + (1 - amount) * x)[1:]
            return lit if x >= 1 else terminal.backed(lit, rgb, 1, terminal.cells(lit))
        clock.start([(row, 1)], at, since + GLOW)
    return start


def fading(line, took):
    """How a row comes up out of the background on a screen's clock, `line` as the draw wrote
    it: in `took` seconds from when it is news, then as drawn, the pointer's cell lit -- the line
    a row opens as the highlight comes to it, the rows of a page turned to.  A function of the
    clock, the screen row, since when and what it was before."""
    def start(clock, row, since, _):
        lit = terminal.pointed(row, 1, line)

        def at(now, text=lit):
            amount = 1 - eased((now - since) / took)
            return terminal.fade(text, amount)
        clock.start([(row, 1)], at, since + took, effect=at)
    return start


def titled(header, x):
    """A screen's header, `agentkit · <its name>` and the time, with that name written out to
    `x` of it, 0 to 1, as its page opens: the cells after it blank.  One lit by the pointer, or
    with no name, as drawn."""
    named = "\033" not in header and re.fullmatch(r"(agentkit)( · .*?)( +\S+)", header)
    if not named:
        return header
    name = named[2]
    shown = name[:round(len(name) * max(0, min(1, x)))]
    return named[1] + shown + " " * (terminal.cells(name) - terminal.cells(shown)) + named[3]


def writing(cells, began, before=0, total=None):
    """One line of a question, `cells` each of its cells as the draw wrote it, that writes itself
    out from `began` in WRITE seconds, a cell at a time as typed: after the `before` cells of the
    lines above it, of `total` in all; an animation for each cell, blank as wide as it until it
    is written, and when it is still."""
    total = total or len(cells)

    def cell(n, text):
        def at(now):
            written = before + n < total * (now - began) / WRITE
            return text if written else " " * terminal.cells(text)
        return at
    return [cell(n, text) for n, text in enumerate(cells)], began + WRITE


def growing(cells, began, took=GROW, start=0, light=None):
    """A progress line, `cells` each of its cells as the draw wrote it: its done part grows or
    shrinks from its first `start` cells to its length in `took` seconds from `began` -- from
    nothing as a screen opens, from its old length as its plan moves, then with one cell of
    `light` at its head and the cells it shrinks from in `light`'s colour -- the rest of it the
    empty track, and each cell is then as drawn; an animation for each cell, and when it is
    still."""
    done = sum(1 for text in cells if terminal.plain(text) in ("━", "╸", "="))
    full, empty = "━─" if terminal.utf8() else "=-"
    track = terminal.styled(empty, "dim")

    def cell(n, text):
        filled = terminal.plain(text) in ("━", "╸", "=")

        def at(now):
            head = round(start + (done - start) * eased((now - began) / took))
            if n >= head:
                return track if filled else text
            if light and n == head - 1 and now < began + took:
                return terminal.styled(terminal.plain(text) if filled else full,
                                       terminal.faded(light, -BRIGHTER))
            if filled:
                return text.replace("╸", full) if n < head - 1 else text
            return terminal.styled(full, light)
        return at
    return [cell(n, text) for n, text in enumerate(cells)], began + took


def circling(cells, bright=False):
    """A working seat's line with no plan yet, `cells` each of its cells as the draw wrote it: a
    soft light three cells long goes along it left to right in ROUND seconds, in at the left and
    out at the right, and round again -- its middle brighter than the working colour, its ends
    half way to the background -- its place the clock's alone, so every such line moves in one
    phase; an animation for each cell, for as long as it is drawn.  `bright` on the highlighted
    row."""
    full = "━" if terminal.utf8() else "="
    inks = [terminal.faded("working", amount) for amount in (DIMMER, -BRIGHTER, DIMMER)]

    def cell(n, text):
        def at(now):
            behind = int(now % ROUND / ROUND * (len(cells) + len(inks))) - n
            if not 0 <= behind < len(inks):
                return text
            lit = terminal.styled(full, inks[behind])
            return terminal.highlight(lit, mark=False) if bright else lit
        return at
    return [cell(n, text) for n, text in enumerate(cells)], None


def counting(cells, before, began, took=GROW):
    """A progress line's count, `cells` each of its cells as the draw wrote it -- `3 of 8` --
    counting up from `before` done, of the same total, to what it says in `took` seconds from
    `began`, eased as its line grows (`growing`) so that at every frame it says what the line
    shows, a narrower number at the right of its cells, each in its cell's own style; an
    animation for each cell, and when it is still."""
    drawn = "".join(terminal.ANSI.sub("", text) for text in cells)
    done, total = map(int, drawn.split(" of "))

    def cell(n, text):
        pieces, codes = terminal.ANSI.split(text), terminal.ANSI.findall(text) + [""]

        def at(now):
            shown = round(before + (done - before) * eased((now - began) / took))
            char = f"{shown} of {total}".rjust(len(drawn))[n]
            return "".join((char if piece else "") + code for piece, code in zip(pieces, codes))
        return at
    return [cell(n, text) for n, text in enumerate(cells)], began + took


def halving(text, began, took, bright=False):
    """A mark, `text` as drawn, that just filled or emptied -- a toggle set or cleared, a task's
    next square: through its half (`□ ▣ ■`, `○ ◉ ●`) for the first half of `took` seconds from
    `began`, then as drawn; and when it is still.  `bright` on the highlighted row."""
    half = "".join(HALF.get(char, char) for char in text)

    def at(now):
        shown = half if now - began < took / 2 else text
        return terminal.highlight(shown, mark=False) if bright else shown
    return at, began + took


def nudging(text, began, bright=False):
    """Marks, `text` as drawn, from the cell before them, whose change was refused: they nudge
    a cell left, right, left and back in SHAKE seconds; and when they are still.  `bright` on
    the highlighted row."""
    def at(now):
        shift = (-1, 1, -1, 0)[min(3, int(4 * (now - began) / SHAKE))]
        moved = " " * (1 + shift) + text + " " * (1 - shift)
        return terminal.highlight(moved, mark=False) if bright else moved
    return at, began + SHAKE


def sweeping(cells, began, kind, bright=False):
    """A line just done, `cells` each of its cells as the draw wrote it, from `began`: one light
    of `kind`'s colour crosses it left to right in SWEEP seconds, and each cell is then as
    drawn; an animation for each cell, and when it is still."""
    light = terminal.faded(kind, -BRIGHTER)

    def cell(n, text):
        def at(now):
            if n != int(len(cells) * (now - began) / SWEEP):
                return text
            lit = terminal.styled(terminal.plain(text), light)
            return terminal.highlight(lit, mark=False) if bright else lit
        return at
    return [cell(n, text) for n, text in enumerate(cells)], began + SWEEP


def colouring(text, began, colour, into, rest=None, bright=False):
    """`text`, cells drawn in `rest` (None: plain) and in a company's `colour` while the pointer
    is on its subscription, from `began`, when the pointer came onto it (`into`) or left it: the
    colour washes in left to right in WASH seconds, a light riding its edge, or drains right to
    left in DRAIN; its animation, and when it is still.  The text is written whole from its
    first cell, so a letter two cells wide keeps both and a combining mark its letter.
    `bright` is the highlighted row's, where every cell is."""
    took, size = WASH if into else DRAIN, terminal.cells(text)
    start, end = terminal.faded(rest or "dim", 0 if rest else -1), terminal.faded(colour, 0)
    lift = terminal.faded("dim", -1)

    def mixed(one, other, amount):
        return "#" + "".join(
            f"{round(int(one[i:i + 2], 16) * (1 - amount) + int(other[i:i + 2], 16) * amount):02x}"
            for i in (1, 3, 5))

    def letter(char, p):
        p = min(1, max(0, p))
        kind = (rest if p <= 0 else colour if p >= 1 else
                mixed(mixed(start, end, p), lift, EDGE * math.sin(math.pi * p)))
        return terminal.styled(char, kind) if kind else char

    def at(now):
        reached = eased((now - began) / took)
        front = (reached if into else 1 - reached) * (size + 2)
        # each letter by the last cell it takes, from 0: a combining mark has its letter's
        drawn = "".join(letter(char, front + 1 - terminal.cells(text[:n + 1]))
                        for n, char in enumerate(text))
        return terminal.highlight(drawn, mark=False) if bright else drawn
    return at, began + took


def washing(cells, colour, bright=False):
    """How a subscription's cells on one row move on a screen's clock as the highlight or the
    pointer comes onto it or leaves it (`colouring`): `cells` are (column, text, what it is
    drawn in at rest).  A function of the clock, the screen row, since when and what it showed
    before, True when it was lit and drains now."""
    def start(clock, row, since, before):
        for column, text, rest in cells:
            clock.start([(row, column)], *colouring(text, since, colour, not before, rest, bright))
    return start


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


def spinning(began):
    """The spinner beside what one of ak's own waits from `began` is for -- a catalog, a
    login, a reset spent -- in the accent, a glyph each SPIN seconds: an animation, for as long
    as it is drawn.  A model at work breathes instead (`breathing`)."""
    glyphs = SPINNER if terminal.utf8() else "|/-\\"
    return lambda now: terminal.styled(glyphs[int((now - began) / SPIN) % len(glyphs)], "accent")


class Clock:
    """The running animations, each cell's, what was last written in each, and what the draws
    showed that may be news."""

    def __init__(self, fade=False, page=False):
        self.cells = {}     # (row, column), counted from 1 -> its animation, a time to its text,
                            # and the time it is still from, or None for as long as it is drawn
        self.effects = {}   # cell -> how its animation transforms text written over it
        self.shown = {}     # (row, column) -> the text last written there
        self.last = None    # when the last frame was made
        self.seen = None    # key -> what the last draw showed, and since when and in place of
                            # what when that was news; None when no draw is to be compared with
        self.touched = {}   # key -> since when it is news that changed nothing (`touch`)
        self.asked = {}     # each question shown -> when it began writing itself out, or None
        self.fade = fade    # what is drawn fades in over the first FADE seconds (`rise`): a popup
        self.page = page    # ... or, a page opening, all under its header and rule (`titled`)
        self.opened = None  # ... from its first frame
        self.rising = None  # ... the lines drawn, top down, while they come up
        self.grows = None   # each line the screen's first draw has -> when it grows in from

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
        """News at `key` from now that changed nothing: a mark whose change was refused."""
        self.touched[key] = time.monotonic()

    def settle(self):
        """A key: whatever moves ends on its last frame, the next draw showing it still, and
        only what the key itself changes is news."""
        self.seen = self.seen and {key: (value, None, None)
                                   for key, (value, _, _) in self.seen.items()}
        self.touched, self.asked = {}, dict.fromkeys(self.asked)

    def drawn(self, moves, row):
        """A draw's frame: every cell it wrote over still, then each of its `moves` -- (line,
        key, value, start) -- that is news (`look`) started on the screen row `row(line)` puts
        it on, by `start(clock, row, since, before)`, None where it is not shown; the first
        frame, at the clock's phase so nothing jumps, and whether the screen up comes up in it
        as it opens (`rise`)."""
        self.clear()
        rising = self.rise(terminal.on_screen())
        news = self.look({key: value for _, key, value, _ in moves})
        for line, key, _, start in moves:
            if key in news and row(line) is not None:
                start(self, row(line), *news[key])
        return self.frame(), rising

    def start(self, cells, animation, until=None, effect=None):
        """Animate `cells` by `animation`, a function of the clock's time to what a cell shows,
        until `until` -- then its last frame is written and it is still -- or while it is drawn.
        `effect(now, text)` also transforms animations written inside its span.

        Nothing moves where colour cannot: off a terminal, under NO_COLOR, at eight colours;
        and news whose time is over does not move again.
        """
        if terminal.colour_depth() > 8 and (until is None or until > time.monotonic()):
            for cell in cells:
                self.cells[cell] = animation, until
                self.effects[cell] = effect

    def span(self, row, column, animations, until=None):
        """Animate the cells of a span from `column` of `row`, an animation each, as `start`."""
        for n, animation in enumerate(animations):
            self.start([(row, column + n)], animation, until)

    def rise(self, lines):
        """Whether `lines`, a draw's screen top down, come up out of the background, the frames
        writing them and what moves in them until they are up: on a clock made to `fade`, or a
        `page`'s, where colour can move, whatever is drawn in the FADE seconds from its first
        frame -- a key's draw at once, and news -- each from where the fade has got to.
        """
        now = time.monotonic()
        opened = now if self.opened is None else self.opened    # not yet: by this draw's frame
        if (self.fade or self.page) and terminal.colour_depth() > 8 and now < opened + FADE:
            self.rising = lines
        return self.rising is not None

    def clear(self):
        """Nothing animates and nothing is shown: a draw has written every cell over."""
        self.cells, self.effects, self.shown, self.rising = {}, {}, {}, None

    def forget(self):
        """Nothing seen: the next draw's values are drawn as they are, no news in them, and a
        screen that has opened is up (`rise`)."""
        self.seen, self.touched = None, {}
        self.opened = None if self.opened is None else -math.inf

    def wait(self):
        """Seconds until the next frame is due, or None while nothing animates."""
        if not self.cells and not self.rising:
            return None
        return 0 if self.last is None else max(0, self.last + FRAME - time.monotonic())

    def frame(self):
        """What to write now: the lines still rising and every cell that moves, faded with them,
        or each cell whose text moved since it was last written, no other, with the pointer's
        light where it is (`terminal.pointed`)."""
        now = self.last = time.monotonic()
        out, amount, first = "", 0, 3 if self.page else 1     # where what comes up starts
        if self.rising:
            # from its first frame, not from the draw making it: however long that draw took,
            # what comes up starts at the background
            self.opened = now if self.opened is None else self.opened
            amount = 1 - eased((now - self.opened) / FADE)
            out = "".join(f"\033[{row};1H" + (terminal.fade(line, amount) if row >= first else
                                               titled(line, 1 - amount) if row == 1 else line)
                          for row, line in enumerate(self.rising, 1))
            # every cell that moves written over them again, and once they are up, as drawn
            self.shown, self.rising = {}, self.rising if amount > 0 else None
        # what spans more than its cell -- a whole row's glow -- first, and what moves inside
        # it written again over it in the same frame, on its background and with its effect
        drawn = sorted(((cell, text, terminal.cells(text), until)
                        for cell, (animation, until) in self.cells.items()
                        for text in [animation(now)]), key=lambda one: one[2] < 2)
        wide = [(cell, text, width, self.effects[cell])
                for cell, text, width, _ in drawn if width > 1]
        for (row, column), text, width, until in drawn:
            text = next((terminal.backed_as(effect(now, text) if effect else text,
                                            over, column - at + 1)
                         for (above, at), over, size, effect in wide
                         if above == row and at < column < at + size), text)
            if self.shown.get((row, column)) != text:
                self.shown[row, column] = text
                lit = terminal.pointed(row, column, text)
                out += f"\033[{row};{column}H{terminal.fade(lit, amount if row >= first else 0)}"
                for inside in [cell for cell in self.shown if cell[0] == row
                               and column < cell[1] < column + width]:
                    del self.shown[inside]
            if until is not None and now >= until:
                del self.cells[row, column]         # its last frame is out: still from here
                del self.effects[row, column]
        return out
