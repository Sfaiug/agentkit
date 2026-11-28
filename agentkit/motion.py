"""The one animation clock: which cells move, and what each shows at every frame.

At rest only what a model works on moves, breathing: a working session's `●` and the tip of its
line (`menu.tips`), a light going round its line while it has no plan
yet; news moves once and is then still --
a `!` that turned `needs you` pulses twice, a `✓` that turned `done` settles from bright and a
light crosses its line, either's row glowing in its word's colour as it fades; the line a row
opens comes up as the highlight comes to it, and a page's rows as it is turned to; each
progress line grows to its length as the menu opens and glides to a new one as its plan moves,
its count counting up with it, as a usage meter does to a new reading (menu.gliding); an effort's
bar a step filled rises into place and a step onto a model's highest effort sends a light
through its word, a mark set fills and one cleared empties, one whose change was refused shakes;
a popup's content fades in once, as it opens, a card as it is asked, and a page's under its
header as it opens, its name writing itself out in the header; the rule under a screen's
header glides while its content is fetched and a light passes once along it when a count ends
(`Clock.sweep`), a spinner turning beside what ak waits on;
the highlight comes from toward the accent and fades where it left (`Clock.light`) -- and
every motion runs on this same clock, every light that travels in the theme's rainbow (`lit`)
(docs/cli-design.md, Motion).  A screen says which cells animate and how when it draws
(`Clock.start`), asking first which of its values are news
(`Clock.look`); the wait loop asks how long until the next frame (`Clock.wait`) and what to
write then (`Clock.frame`), and a key ends what moves on its last frame (`Clock.settle`).  No
screen keeps a timer: time, easing and the running animations live here, and cells animated
alike are in one phase because each reads one clock.
"""

import math
import os
from pathlib import Path
import re
import time

from . import terminal
from .themes import RAINBOW

FRAME = 1 / 20      # at most twenty frames a second
# Each kind of motion takes one time wherever it is drawn (docs/cli-design.md, Motion).
FADE = 0.15         # seconds what comes up out of the background takes: a row's line, page, popup
FILL = 0.1          # ... a cell takes to fill or empty: a mark, an effort's cell
SWEEP = 0.45        # ... a light takes to pass once: across a done seat's line, an effort's word, a rule
BREATH = 2.0        # ... a breathing cell out to its dimmer tone and back, and a light's round
DIMMER = 0.5        # ... that tone: half way from its colour to the background
PULSE = 0.3         # seconds each of the two pulses of a `!` that turned `needs you` takes
SETTLE = 0.4        # ... a `✓` that turned `done` takes from bright to its colour
SHAKE = 0.24        # ... a mark whose change was refused takes to nudge left, right, left and back
GLOW = 1.0          # ... a seat's row on news takes to fade from its glow
NEWS = 0.7          # ... and a seat's row on news: its word's colour that far toward it
GROW = 0.45         # ... a seat's progress line takes to grow to its length as ak opens
STAGGER = 0.04      # ... and each row after the one above it
GLIDE = 0.7         # ... and to glide to a new length as its plan moves, a light at its head
HALF = {"□": "■", "■": "■", "○": "●", "●": "●"}     # a mark half way: full, in its open one's colour
BRIGHTER = 0.5      # how lit news is: half way from its colour to the foreground
WAIT = 0.15         # seconds a screen's content is fetched for before its rule says so
SPIN = 2 * FRAME    # seconds each of the spinner's glyphs shows beside what ak waits on
SPINNER = "▖▘▝▗"     # quadrants, which a terminal draws itself, and `|/-\` without UTF-8
LANDS = 0.25        # ... the highlight takes to settle onto the selection where it comes
LEAVES = 0.2        # ... and to fade into the background where it left, or a removed row
# The highlight's colours as shares of the theme's selection, accent and background, drawn in the
# theme in force whenever it changes (`painted`): where it comes it starts 45% of the way to the
# accent.
SELECTED, COMES, BACKGROUND = (1, 0, 0), (0.55, 0.45, 0), (0, 0, 1)


def breath(now):
    """0 at the colour, 1 at its dimmer tone, and back once every BREATH seconds of the clock:
    a sine, so the colour eases into every turn instead of bouncing off it."""
    return (1 - math.cos(2 * math.pi * now / BREATH)) / 2


def eased(x):
    """0 to 1 as `x` goes from 0 to 1, slow out of the one and into the other."""
    return (1 - math.cos(math.pi * min(1, max(0, x)))) / 2


def mixed(one, other, x):
    """The highlight's colour `x` (0 to 1) of the way from `one` to `other` (SELECTED)."""
    return tuple(a + (b - a) * x for a, b in zip(one, other))


def painted(shares):
    """The highlight's colour of `shares` (SELECTED) as `rrggbb` in the theme in force."""
    rgbs = [bytes.fromhex(terminal.colour(role)) for role in ("selection", "accent", "background")]
    return "".join(f"{round(sum(share * rgb[n] for share, rgb in zip(shares, rgbs))):02x}"
                   for n in range(3))


def lit(text, behind):
    """`text`, a cell as it shows, its head-most cell `behind` cells back from the head of a light
    that travels: as it shows, bold on the highlighted row, but in the rainbow's colour that far
    down it, where the light covers every cell its glyph takes, one at least (a mark's is its
    letter's); else None."""
    glyph = terminal.plain(text)
    if not 0 <= behind <= len(RAINBOW) - max(1, terminal.cells(glyph)):
        return None
    drawn = re.match(f"(?:{terminal.ANSI.pattern})*", text).group()
    return drawn + terminal.styled(glyph, "#" + terminal.colour(RAINBOW[behind]))


def tinted(glyph, word, amount, bright=False):
    """`glyph` in `word`'s colour `amount` of the way to the background, or toward the foreground
    where `amount` is below 0: bold where the word is, and `bright` on the highlighted row,
    where every cell is, and there toward the highlight where the look reads (`terminal.LOOK`)."""
    ground = "selection" if bright and terminal.LOOK else "background"
    text = terminal.styled(glyph, terminal.faded(word, amount, ground))
    bold = bright or terminal.STATE_STYLES[word][4] == "1"
    return terminal.bright(text) if bold else text


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
    its turn at `began`: as it was until then, for the first half of FILL seconds a filled one
    lit and an emptied one still full but dim, and then as the draw wrote it; and when it is
    still."""
    full, empty = terminal.effort_cells(2, 1)        # each as a draw writes it
    shown = terminal.plain(full)
    middle = terminal.styled(shown, terminal.faded("working", -BRIGHTER) if up else "dim")

    def at(now):
        text = ((empty if up else full) if now < began else
                middle if now < began + FILL / 2 else full if up else empty)
        return terminal.bright(text) if bright else text
    return at, began + FILL


def shimmering(word, began, kind=None, bright=False):
    """An effort's `word` that a step at `began` took to its model's highest: one light through
    it (`lit`), left to right, in SWEEP seconds, and then as the draw wrote it; and
    when it is still.  The word is written whole from its first cell, so a letter two cells wide
    keeps both, and the light's head steps onto both at once.  `kind` is how the draw styled it
    -- `dim` on a spent model's row -- and `bright` is the highlighted row."""
    ends = [terminal.cells(word[:n + 1]) for n in range(len(word))]
    # a letter is lit only while the light covers it whole (`lit`): the last's first cell ends it
    size = terminal.cells(word) + 1 - max(1, terminal.cells(word[-1:]))

    def at(now):
        head = passing(size, began, now)
        head = next((end - 1 for end in ends if end > head), head)
        text = ""
        for letter, end in zip(word, ends):
            text += lit(letter, head + 1 - end) or kind and terminal.styled(letter, kind) or letter
        return terminal.bright(text) if bright else text
    return at, began + SWEEP


def toggled(mark, width, kind, bright, column):
    """How a mark drawn `mark` -- terminal.toggle's, `width` cells from the screen's `column`, in
    `kind` -- moves on a screen's clock once it is news: one set or cleared fills or empties
    through its half (`□`, a dim `■`, `■`) in FILL seconds, two frames; one whose change was
    refused, news that changed nothing (`Clock.touch`), nudges a cell left, right, left and back
    in SHAKE seconds, the light its column is on staying where the draw put it
    (terminal.pointed).  `bright` is the highlighted row.  A function of the clock, the screen
    row, when the news came and the mark before it."""
    def start(clock, row, since, before):
        shown = terminal.toggle(mark, width, kind)
        if before == mark:
            clock.start([(row, column - 1)], *nudging(shown, since, bright))
        elif before in HALF and mark in HALF:       # its open one is dim
            half = terminal.toggle(HALF[mark], width, "dim")
            clock.start([(row, column)], *halving(shown, half, since, bright))
    return start


def refused(text, value, column, bright=False):
    """How a knob drawn `text` from the screen's `column`, showing `value`, moves on a screen's
    clock once a step of it was refused, news that changed nothing (`Clock.touch`): it nudges a
    cell left, right, left and back in SHAKE seconds (`nudging`), `bright` on the highlighted
    row."""
    def start(clock, row, since, before):
        if before == value:
            clock.start([(row, column - 1)], *nudging(text, since, bright))
    return start


def glowing(line, kind, amount):
    """How a seat's row on news moves on a screen's clock, `line` as the draw wrote it: its cells on
    a soft glow of `kind`'s colour, `amount` of the way to the background, that fades into the
    background in GLOW seconds, and then as drawn, the highlight where it was drawn
    (terminal.pointed).  A function of the clock, the screen row, when it was news and what it
    was before."""
    def start(clock, row, since, _):
        def at(now):
            x = eased((now - since) / GLOW)
            rgb = terminal.faded(kind, amount + (1 - amount) * x)[1:]
            return line if x >= 1 else terminal.backed(line, rgb, 1, terminal.cells(line))
        clock.start([(row, 1)], at, since + GLOW)
    return start


def fading(line):
    """How a row comes up out of the background on a screen's clock, `line` as the draw wrote
    it: in FADE seconds from when it is news, then as drawn, the highlight where it was drawn
    (terminal.pointed) -- the line a row opens as the highlight comes to it, the rows of a page
    turned to.  A function of the clock, the screen row, since when and what it was before."""
    def start(clock, row, since, _):
        def at(now, text=line):
            amount = 1 - eased((now - since) / FADE)
            return terminal.fade(text, amount)
        clock.start([(row, 1)], at, since + FADE, effect=at)
    return start


def titled(header, x):
    """A screen's header, `agentkit · <its name>` and the time, with that name written out to
    `x` of it, 0 to 1, as its page opens: the cells after it blank, every style kept.  One with
    no name as drawn."""
    named = re.fullmatch(r"(agentkit)( · .*?)( +\S+)", terminal.ANSI.sub("", header))
    if not named:
        return header
    keep, end = named.start(2) + round(len(named[2]) * max(0, min(1, x))), named.end(2)
    out, at = "", 0
    for token in re.findall(f"{terminal.ANSI.pattern}|.", header, re.S):
        if not token.startswith("\033"):
            token, at = " " * terminal.cells(token) if keep <= at < end else token, at + 1
        out += token
    return out


def growing(cells, began, took=GROW, start=0, light=None):
    """A progress line, `cells` each of its cells as the draw wrote it: its done part grows or
    shrinks from its first `start` cells to its length in `took` seconds from `began` -- from
    nothing as a screen opens, from its old length as its plan moves, then with a light (`lit`)
    at its head and the cells it shrinks from in `light`'s colour -- the rest of it the
    empty track, and each cell is then as drawn; an animation for each cell, and when it is
    still."""
    done = sum(1 for text in cells if terminal.plain(text) in ("━", "╸", "="))
    full, empty = "━─" if terminal.utf8() else "=-"
    track = terminal.styled(empty, "border")

    def cell(n, text):
        filled = terminal.plain(text) in ("━", "╸", "=")

        def at(now):
            head = round(start + (done - start) * eased((now - began) / took))
            if n >= head:
                return track if filled else text
            shown = ((text.replace("╸", full) if n < head - 1 else text) if filled else
                     terminal.styled(full, light))
            return light and now < began + took and lit(shown, head - 1 - n) or shown
        return at
    return [cell(n, text) for n, text in enumerate(cells)], began + took


def circling(cells):
    """A working seat's line with no plan yet, `cells` each of its cells as the draw wrote it: a
    light (`lit`) goes along it left to right in BREATH seconds, in at the left and
    out at the right, and round again, its place the clock's alone, so every such line moves in one
    phase; an animation for each cell, for as long as it is drawn."""
    def cell(n, text):
        def at(now):
            head = int(now % BREATH / BREATH * (len(cells) + len(RAINBOW)))
            return lit(text, head - n) or text
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


def halving(text, half, began, bright=False):
    """A mark, `text` as drawn, that just filled or emptied -- a toggle set or cleared, a task's
    next square: `half`, its full shape in the colour its open one has (`□`, a dim `■`, `■`), for
    the first half of FILL seconds from `began`, then as drawn; and when it is still.  `bright`
    on the highlighted row."""
    def at(now):
        shown = half if now < began + FILL / 2 else text
        return terminal.bright(shown) if bright else shown
    return at, began + FILL


def nudging(text, began, bright=False):
    """Marks, `text` as drawn, from the cell before them, whose change was refused: they nudge
    a cell left, right, left and back in SHAKE seconds; and when they are still.  `bright` on
    the highlighted row."""
    def at(now):
        shift = (-1, 1, -1, 0)[min(3, int(4 * (now - began) / SHAKE))]
        moved = " " * (1 + shift) + text + " " * (1 - shift)
        return terminal.bright(moved) if bright else moved
    return at, began + SHAKE


def passing(size, began, now):
    """The head of a light passing once along `size` cells from `began`, at `now` (`lit`): a cell
    at a time from the first, its last colour leaving the last cell as SWEEP ends, past it then."""
    if now >= began + SWEEP:       # its end exactly, however `now - began` rounds
        return size + len(RAINBOW)
    return int((size + len(RAINBOW) - 1) * (now - began) / SWEEP)


def sweeping(cells, began):
    """A line just done, `cells` each of its cells as the draw wrote it, from `began`: one light
    (`lit`) crosses it left to right in SWEEP seconds, and each cell is then as
    drawn; an animation for each cell, and when it is still."""
    def cell(n, text):
        def at(now):
            return lit(text, passing(len(cells), began, now) - n) or text
        return at
    return [cell(n, text) for n, text in enumerate(cells)], began + SWEEP


def fetching(clock, began):
    """The rule under a screen's header, its second row, animated on `clock` while the screen's
    content is fetched from `began`, a cell each; `clock`.

    For WAIT seconds it is the rule as drawn -- a wait shorter than that shows nothing -- then a
    light (`lit`) glides along it, in from the left and out at the right in
    BREATH seconds, and again; the screen draws the rule still once what it waits on has landed.
    """
    still, size = terminal.rule_line(1), terminal.layout_width()

    def cell(n):
        def at(now):
            t = now - began - WAIT
            head = int(eased(t % BREATH / BREATH) * (size + len(RAINBOW)))
            return t >= 0 and lit(still, head - n) or still
        return at
    for n in range(size):
        clock.start([(2, 1 + n)], cell(n))
    return clock


def lighting(glow, now):
    """The colour the highlight has at `now` where it moves (`Clock.light`), as `mixed`."""
    since, took, start, end, _ = glow
    return mixed(start, end, eased((now - since) / took))


def moment():
    """The time every motion is drawn at, in seconds.  An answer key names its clock in
    `AK_MOTION_CLOCK`, a file of seconds read anew each time, so it reaches the program the key
    runs and moves only as the key moves it; unset, the monotonic clock.  Frames still come on
    real time (`Clock.wait`), each showing the moment it reads."""
    clock = os.environ.get("AK_MOTION_CLOCK")
    return float(Path(clock).read_text()) if clock else time.monotonic()


def movable():
    """Whether anything moves on the screen up (terminal.on_screen): not where colour cannot --
    off a terminal, under NO_COLOR, at eight colours -- nor on a screen as tall as the terminal,
    which scrolls it, no row left where it was drawn (terminal.written)."""
    return terminal.colour_depth() > 8 and len(terminal.on_screen()) < terminal.height()


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
        self.touched = {}   # key -> since when it is news that changed nothing (`touch`), inf
                            # till a frame shows it
        self.later = []     # what the next frame starts as it first shows it (`begin`)
        self.fade = fade    # what is drawn fades in over the first FADE seconds (`rise`): a popup
        self.page = page    # ... or, a page opening, all under its header and rule (`titled`)
        self.opened = None  # ... from its first frame
        self.rising = None  # ... the lines drawn, top down, while they come up
        self.grows = None   # each line the screen's first draw has -> when it grows in from
        self.up = None      # the last draw's screen, top down (`rise`)
        self.lights = {}    # what the last draw lit (terminal.lights)
        self.size = None    # ... and the terminal's size it was drawn at
        self.glows = {}     # ... and what of it, or of what it left, moves: since when, for how
                            # many seconds, from which colour to which, its cells
        self.held = False   # ... and whether the next draw moves it with what it is on (`hold`)
        self.swept = None   # when the header's rule began sweeping (`sweep`), inf till first shown

    def look(self, values):
        """Which of `values` -- key -> what a draw shows for it -- are news, each key -> (since
        when, what it showed before): changed since the draw before this one, or still moving
        from a change before that.

        At first and after `forget` -- a resize, another screen -- every value is taken as it
        is, and so is one no draw before showed: only a change seen while the menu is up moves.
        A key touched is news from the first frame that shows it (`begin`), what it showed
        before being what it shows.
        """
        now, seen, self.seen = moment(), self.seen or {}, {}
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
        """News at `key` that changed nothing -- a mark whose change was refused, the row `n`
        makes -- from the first frame that shows it: however long the draw making that frame
        takes, it moves from there, as a page's rows do."""
        self.touched[key] = math.inf

    def sweep(self):
        """A light passes once along the header's rule from the first frame that shows it
        (`sweeping`), kept across keys that stay on the page until SWEEP ends or `forget`."""
        self.swept = math.inf

    def begin(self, key, start, row, since, before):
        """News at `key` (`look`) started on screen row `row` by `start(clock, row, since,
        before)`, touched news not yet shown by the frame that first shows it."""
        if since == math.inf:
            self.later.append((key, start, row, before))
        else:
            start(self, row, since, before)

    def settle(self):
        """A key: whatever moves ends on its last frame, a screen coming up and the highlight
        too, the next draw showing it still, and only what the key itself changes is news."""
        self.seen = self.seen and {key: (value, None, None)
                                   for key, (value, _, _) in self.seen.items()}
        self.touched, self.glows = {}, {}
        self.opened = None if self.opened is None else -math.inf

    def hold(self):
        """The next draw moves the highlight with what it is on, not by a key -- a card coming up
        or moved by news (menu.asking): what it lights comes up with it, at rest, and a run on
        no row's spot, known by its place alone (terminal.held), neither comes nor leaves."""
        self.held = True

    def drawn(self, moves, row):
        """A draw's frame: every cell it wrote over still, then each of its `moves` -- (line,
        key, value, start) -- that is news (`look`) started on the screen row `row(line)` puts
        it on, by `start(clock, row, since, before)`, None where it is not shown, and the
        header's rule swept once if asked (`sweep`); the first frame, at the clock's phase so
        nothing jumps, and whether the screen up comes up in it as it opens (`rise`)."""
        self.clear()
        rising = self.rise(terminal.on_screen())
        news = self.look({key: value for _, key, value, _ in moves})
        for line, key, _, start in moves:
            if key in news and row(line) is not None:
                self.begin(key, start, row(line), *news[key])
        if self.swept is not None:
            now = moment()
            if self.swept == math.inf:
                self.swept = now
            if self.swept + SWEEP <= now:
                self.swept = None
            else:
                still, size = terminal.rule_line(1), terminal.layout_width()
                self.span(2, 1, *sweeping([still] * size, self.swept))
                # the draw just wrote the plain rule, so this frame writes only its lit cells
                self.shown.update(((2, 1 + n), still) for n in range(size))
        return self.frame(), rising

    def start(self, cells, animation, until=None, effect=None):
        """Animate `cells` by `animation`, a function of the clock's time to what a cell shows,
        until `until` -- then its last frame is written and it is still -- or while it is drawn.
        `effect(now, text)` also transforms animations written inside its span.

        Nothing moves where it cannot (`movable`); news whose time is over does not move again.
        """
        if movable() and (until is None or until > moment()):
            for cell in cells:
                self.cells[cell] = animation, until
                self.effects[cell] = effect

    def span(self, row, column, animations, until=None):
        """Animate the cells of a span from `column` of `row`, an animation each, as `start`."""
        for n, animation in enumerate(animations):
            self.start([(row, column + n)], animation, until)

    def rise(self, lines):
        """Whether `lines`, a draw's screen top down, are the frames' to write, and what moves in
        them, where it can (`movable`).  They come up out of the background on a clock made to
        `fade`, or a `page`'s: whatever is drawn in the FADE seconds from its first frame till a
        key (`settle`), news too, each from where the fade has got to."""
        now, moves = moment(), movable()
        self.light(now, moves)
        self.up = lines
        opened = now if self.opened is None else self.opened    # not yet: by this draw's frame
        if (self.fade or self.page) and moves and now < opened + FADE:
            self.rising = lines
        elif not moves:     # up at once: a later draw where it can move does not open it again
            self.opened = -math.inf
        return self.rising is not None

    def light(self, now, moves):
        """The highlight as a draw at `now` moves it (terminal.lights), by what it is on: where it
        comes, from COMES -- or from where it still fades there -- onto the selection in LANDS
        seconds; where it left, on what is still there, from where it was into the background in
        LEAVES: at rest on a screen up first or at another size, and where nothing can;
        after `hold`, where it comes too."""
        was, self.lights, glows, self.glows = self.lights, terminal.lights(), self.glows, {}
        size, self.size = self.size, (terminal.width(), terminal.height())
        held, self.held = self.held, False
        if self.up is None or not moves or size != self.size:
            return
        if held:        # what it lit by a place alone may be there still or have moved off
            was, glows = ({what: one for what, one in old.items() if what[0] is not None}
                          for old in (was, glows))
            was.update(self.lights)
        for what, spans in self.lights.items():
            glow = glows.get(what)
            if what not in was:
                self.glows[what] = (now, LANDS, lighting(glow, now) if glow else COMES, SELECTED,
                                    spans)
            elif glow:          # still coming
                self.glows[what] = *glow[:4], spans
        for what in (was.keys() | glows.keys()) - self.lights.keys():
            glow = glows.get(what)
            if what in was:
                glow = (now, LEAVES, lighting(glow, now) if glow else SELECTED, BACKGROUND,
                        was[what])
            still = [span for span in glow[4] if terminal.held(*span[:2]) == (what, span[3])]
            if still:
                self.glows[what] = *glow[:4], still

    def rest(self):
        """A key: where the highlight moves, its last frame to write before anything else."""
        self.glows = {what: (-math.inf, *glow[1:]) for what, glow in self.glows.items()}
        return self.frame() if self.glows else ""

    def clear(self):
        """Nothing animates and nothing is shown: a draw has written every cell over."""
        self.cells, self.effects, self.shown, self.rising = {}, {}, {}, None

    def forget(self):
        """Nothing seen: the next draw's values are drawn as they are, no news in them, and a
        screen that has opened is up (`rise`)."""
        self.seen, self.touched, self.up, self.glows, self.swept = None, {}, None, {}, None
        self.opened = None if self.opened is None else -math.inf

    def wait(self):
        """Seconds until the next frame is due, or None while nothing animates."""
        if not self.cells and not self.rising and not self.glows:
            return None
        return 0 if self.last is None else max(0, self.last + FRAME - time.monotonic())

    def frame(self):
        """What to write now: the lines still rising and every cell that moves, faded with them,
        or each cell whose text moved since it was last written, no other, on the background
        the screen has under it, the highlight's where it is (`terminal.pointed`) and the colour it
        has got to where it moves (`light`)."""
        now, self.last = moment(), time.monotonic()
        later, self.later = self.later, []
        for key, start, row, before in later:   # touched news, shown first here (`begin`)
            self.touched[key] = now
            start(self, row, now, before)
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
        screen, moving = terminal.on_screen(), {}     # row -> where the highlight moves on it
        for what, glow in list(self.glows.items()):
            since, took, *_, spans = glow
            x, rgb = (now - since) / took, painted(lighting(glow, now))
            for row, left, right, _ in spans:
                if row > len(screen):
                    continue
                text = terminal.columns(screen[row - 1], left, right)
                if x < 1:
                    moving.setdefault(row, []).append((left, right, rgb))
                    text = terminal.backed(text, rgb, 1, right - left + 1)
                elif terminal.cells(text) <= right - left:
                    text += "\033[K"        # past the line's end, cleared as its draw left it
                if self.shown.get((row, left, right)) != text:
                    self.shown[row, left, right] = text
                    out += f"\033[{row};{left}H{terminal.fade(text, amount if row >= first else 0)}"
                    # what moves inside it written again over it
                    for cell in [cell for cell, was in self.shown.items() if len(cell) == 2
                                 and cell[0] == row and cell[1] <= right
                                 and cell[1] + terminal.cells(was) > left]:
                        del self.shown[cell]
            if x >= 1:
                del self.glows[what]        # its last frame is out, as drawn
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
                # a row's line clearing its tail (`terminal.cleared`), a usage grid gliding,
                # cleared past where the highlight moves, which keeps its blank past the line's
                # end, as at rest
                line = column == 1 and lit.endswith("\033[K")
                lit = lit.removesuffix("\033[K") if line else lit
                for left, right, rgb in moving.get(row, ()):
                    end = right if line else min(right, column + width - 1)
                    if left <= end and right >= column:
                        lit = terminal.backed(lit, rgb, max(left, column) - column + 1,
                                              end - column + 1)
                lit = terminal.cleared(lit) if line else lit
                out += f"\033[{row};{column}H{terminal.fade(lit, amount if row >= first else 0)}"
                for inside in [cell for cell in self.shown if cell[0] == row
                               and column < cell[1] < column + width]:
                    del self.shown[inside]
            if until is not None and now >= until:
                del self.cells[row, column]         # its last frame is out: still from here
                del self.effects[row, column]
        return out
