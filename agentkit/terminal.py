"""Small terminal layouts shared by the menu, runs and subscription meters."""

import os
import re
import select
import shutil
import signal
import sys
import termios
import threading
import time
import unicodedata
from collections import namedtuple
from functools import lru_cache, wraps


# glyph, ASCII glyph, Mocha RGB, eight-colour tone, emphasis. Words remain the contract
# with the classifier; every presentation (including tmux formats) comes from this table.
# The three words a session reads, and the two presentation-only kinds the screens ask for
# by name: `dim` for a note beside a row, `FAIL` for a verdict, which is no session state.
STATE_STYLES = {
    "needs you": ("!", "!", "f9e2af", "33", "1"),
    "working": ("●", "*", "89b4fa", "36", ""),
    "done": ("✓", "v", "a6e3a1", "32", ""),
    "FAIL": ("✗", "x", "f38ba8", "31", ""),
    "dim": ("·", ".", "6c7086", "37", "2"),
    # Not a fourth state: a run parked on something that lifts by itself says what it waits
    # for instead of a word, and the open circle is what says nobody has to act on it.
    "waiting": ("○", "o", "6c7086", "37", "2"),
}
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def utf8():
    # Python may coerce LC_CTYPE to C.UTF-8 at startup even when the caller said LANG=C.
    # Keep that caller's requested ASCII display unless LC_ALL explicitly overrides it.
    if not os.environ.get("LC_ALL") and os.environ.get("LANG") in ("C", "POSIX"):
        return False
    locale = (os.environ.get("LC_ALL") or os.environ.get("LC_CTYPE") or
              os.environ.get("LANG") or "")
    return "utf8" in locale.lower().replace("-", "") if locale else (
        "utf8" in (sys.stdout.encoding or "").lower().replace("-", ""))


def style_of(word):
    """The style a word takes: its own, else the one its first word names, else none.

    A phrase is how a parked run says what it waits for -- `waiting for claude login` --
    and it takes `waiting`'s glyph and colour, so no screen has to spell either out.
    """
    return STATE_STYLES.get(word) or STATE_STYLES.get(str(word).split(" ")[0])


def glyph(word):
    style = style_of(word)
    return style[0 if utf8() else 1] if style else ""


def state_label(word):
    return f"{glyph(word)} {word}" if style_of(word) else word


def colour_depth():
    term = os.environ.get("TERM", "")
    if not sys.stdout.isatty() or not term or term == "dumb" or "NO_COLOR" in os.environ:
        return 0
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return 24
    try:
        import curses
        curses.setupterm(term=term)
        colours = curses.tigetnum("colors")
        return 256 if colours >= 256 else 8 if colours >= 8 else 0
    except ImportError:
        return 0
    except curses.error:
        return 0


@lru_cache(maxsize=None)
def xterm_colour(rgb):
    """Nearest fixed xterm colour; the first sixteen depend on the user's palette."""
    wanted = tuple(int(rgb[i:i + 2], 16) for i in (0, 2, 4))
    levels = (0, 95, 135, 175, 215, 255)
    colours = [(16 + 36 * r + 6 * g + b, (red, green, blue))
               for r, red in enumerate(levels) for g, green in enumerate(levels)
               for b, blue in enumerate(levels)]
    colours += [(232 + i, (8 + 10 * i,) * 3) for i in range(24)]
    return min(colours, key=lambda item: sum((a - b) ** 2
               for a, b in zip(wanted, item[1])))[0]


def basic_colour(rgb):
    """Nearest of the eight basic colours: each channel on where it is nearer full than off."""
    return str(30 + sum(1 << i for i in range(3) if int(rgb[2 * i:2 * i + 2], 16) >= 128))


def tmux_state(option, colour=False):
    """A dynamic label for a plain-word tmux option; tmux adapts RGB to its client."""
    result = f"#{{{option}}}"
    for word in reversed(STATES):
        _, _, rgb, _, emphasis = STATE_STYLES[word]
        label = state_label(word)
        if colour and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb":
            attrs = ",bold" if emphasis == "1" else ",dim" if emphasis == "2" else ""
            # Commas inside a conditional's result must be escaped as tmux format literals.
            label = f"#[fg=#{rgb}{attrs}]{label}#[default]".replace(",", "#,")
        matches = f"#{{==:#{{{option}}},{word}}}"
        result = f"#{{?{matches},{label},{result}}}"
    return result


def tmux_runs(option):
    """A dynamic tally label for a plain-words tmux option, read when the bar is drawn.

    A tally is unbounded -- `2 running · 1 needs you` for every count -- so no table
    maps it the way `tmux_state` maps one word; instead the whole tally takes the
    attention colour while it carries a figure that needs the owner, exactly the figure
    the menu draws in it, and stays plain otherwise.
    """
    plain = f"#{{{option}}}"
    rgb = STATE_STYLES["needs you"][2]
    if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return plain
    # Commas inside a conditional's result must be escaped as tmux format literals.
    coloured = f"#[fg=#{rgb},bold]{plain}#[default]".replace(",", "#,")
    return f"#{{?#{{m:*needs you*,{plain}}},{coloured},{plain}}}"


def width():
    return max(1, shutil.get_terminal_size((100, 24)).columns)


def height():
    return max(1, shutil.get_terminal_size((100, 24)).lines)


def plain(text):
    text = ANSI.sub("", str(text))
    return " ".join("".join(c for c in text if c.isspace() or
                            not unicodedata.category(c).startswith("C")).split())


def cells(text):
    return sum(0 if unicodedata.combining(c) else
               2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in ANSI.sub("", text))


def cut(text, room):
    """One ellipsis, preferring a word boundary at most four columns before the cut."""
    text = plain(text)
    if cells(text) <= room:
        return text
    if room <= 0:
        return ""
    end, used = 0, 0
    for c in text:
        used += cells(c)
        if used > room - 1:
            break
        end += 1
    prefix = text[:end]
    boundary = prefix.rfind(" ")
    if (end < len(text) and text[end] != " " and boundary > 0
            and cells(prefix[boundary:]) <= 4):
        prefix = prefix[:boundary]
    return prefix.rstrip() + "…"


def pad(text, room, right=False):
    text = cut(text, room)
    space = " " * max(0, room - cells(text))
    return space + text if right else text + space


def prompt_lines(prompt, room):
    """The prompt wrapped on spaces so each line fits, the cursor's space kept.

    `readline` draws only the last line; the lines above it are printed first.
    A bracket that names every worker is otherwise broken mid-word by the
    terminal once six names no longer fit forty columns.
    """
    room = max(1, room)
    if cells(prompt) <= room:
        return [prompt]
    pad = prompt.endswith(" ")
    body = prompt[:-1] if pad else prompt
    lines = wrap(body, room) or [body]
    if pad:
        if cells(lines[-1]) + 1 <= room:
            lines[-1] += " "
        else:
            lines.append(" ")
    return lines


def wrap(text, room):
    """Word wrapping, splitting only a word that cannot fit on a line by itself."""
    room = max(1, room)
    lines, line = [], ""
    for word in plain(text).split():
        if line and cells(line + " " + word) > room:
            lines.append(line)
            line = ""
        while cells(word) > room:
            end, used = 0, 0
            for c in word:
                if used + cells(c) > room:
                    break
                used += cells(c)
                end += 1
            if not end:  # a wide glyph cannot fit in a one-column terminal
                end = 1
            lines.append(word[:end] if used else "…")
            word = word[end:]
        if word:
            line = f"{line} {word}" if line else word
    return lines + ([line] if line else [])


def hang(line, room):
    """`label   text` wrapped at a word under its text's first column, so two columns stay two
    on a phone; a line with no three-space gutter is `wrap`'s."""
    found = re.match(r"(.*?\S)( {3,})(\S.*)", line)
    if cells(line) <= room or not found:
        return [line] if cells(line) <= room else wrap(line, room)
    head = found.group(1) + found.group(2)
    return [(head if number == 0 else " " * cells(head)) + part
            for number, part in enumerate(wrap(found.group(3), room - cells(head)))]


def styled(text, kind):
    depth = colour_depth()
    if not depth or not text:
        return text
    word = {"accent": "working", "ok": "done", "amber": "needs you",
            "attention": "needs you", "good": "done"}.get(kind, kind)
    if kind in ("bold", "reverse"):
        code = "1" if kind == "bold" else "7"
    else:
        # `#RRGGBB` is a colour of the caller's own -- a provider's, on its usage bar -- and
        # takes the nearest the terminal has, as a state's colour does
        _, _, rgb, tone, emphasis = (("", "", kind[1:], basic_colour(kind[1:]), "")
                                     if kind.startswith("#") else STATE_STYLES[word])
        code = ("38;2;" + ";".join(str(int(rgb[i:i + 2], 16)) for i in (0, 2, 4))
                if depth == 24 else f"38;5;{xterm_colour(rgb)}" if depth == 256 else tone)
        if kind == "dim" and depth == 8:
            code = "2"  # the existing eight-colour notes
        elif emphasis:
            code = emphasis + ";" + code
    return f"\033[{code}m{text}\033[0m"


def keys(text, room):
    """Keep each key beside its verb phrase whenever the whole phrase fits."""
    lines, line = [], ""
    for phrase in text.split("   "):
        if line and cells(line + "   " + phrase) > room:
            lines.append(line)
            line = ""
        pieces = wrap(phrase, room)
        lines.extend(pieces[:-1])
        if pieces:
            line = f"{line}   {pieces[-1]}" if line else pieces[-1]
    return lines + ([line] if line else [])


def state_tone(word):
    """One meaning for each state colour; anything else reads dim."""
    return word if word in STATE_STYLES else "dim"   # a phrase reads dim, as `waiting` does


# One state table for the whole CLI, and the whole vocabulary: a session -- and a run,
# and a project -- is working, needs you, or done, and nothing else exists.
# `menu.py`, `ak run status` and `ak orch list` read this; no screen invents its own.
# `watch.session_state` is what decides which of the three a session is.
STATES = {
    "working": ("●", "accent"),
    "needs you": ("!", "attention"),
    "done": ("✓", "good"),
}


def state_glyph(word):
    """The glyph for a state word, ASCII fallback where the locale asks for it."""
    if word not in STATES:
        return glyph(word)
    mark, _ = STATES[word]
    if not utf8():
        return {"●": "*", "✓": "v", "!": "!"}.get(mark, mark)
    return mark


def state_colour(word):
    """One of accent, attention, good for every state word."""
    if word in STATES:
        return STATES[word][1]
    return state_tone(word)


def state_text(word):
    """`glyph word` for any state, read from STATES where it is known."""
    if word in STATES:
        return f"{state_glyph(word)} {word}"
    return state_label(word)


def state_cell(word):
    """A state column cell: `glyph word` in the state's colour."""
    return styled(state_text(word), state_colour(word))


def title_lines(text, room):
    """The title in at most two lines: wrapped once at a word onto an indented
    continuation, cut with ` …` only past that."""
    room = max(1, room)
    lines = wrap(text, room)
    if len(lines) <= 2:
        return lines
    tail = cut(" ".join(lines[1:]), room - 1)
    tail = tail[:-1].rstrip() + " …" if tail.endswith("…") else tail
    return [lines[0], tail]


def format_age(seconds):
    """`<1m`, `5m`, `2h`, `3d`: never seconds, one helper for every screen."""
    try:
        secs = max(0, int(seconds))
    except (TypeError, ValueError):
        return "-"
    if secs < 60:
        return "<1m"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def layout_width(term_width=None):
    """The layout is min(terminal width, 120); beyond that the margin grows, never the text."""
    room = term_width if term_width is not None else width()
    return max(1, min(int(room), 120))


def content_width(term_width=None):
    """Seat rows never stretch to the edge: content is capped at 100 columns."""
    room = term_width if term_width is not None else width()
    return max(1, min(int(room), 100))


def header_line(screen, clock, term_width=None):
    """`agentkit` at the left, the screen name after it, the clock at the right."""
    room = layout_width(term_width)
    title = "agentkit" if not screen else f"agentkit · {screen}"
    gap = max(1, room - cells(title) - cells(clock))
    return title + " " * gap + clock


def rule_line(term_width=None):
    """One dim rule the width of the layout."""
    return styled("─" * layout_width(term_width), "dim")


def key_parts(text):
    """(key, word) pairs for the key line: each key dim, its word plain."""
    parts = []
    for phrase in text.split("   "):
        phrase = phrase.strip()
        if not phrase:
            continue
        key, _, word = phrase.partition(" ")
        parts.append((key.strip(), word.strip()))
    return parts


def key_line(text, term_width=None):
    """The key line: each key dim, its word plain, wrapped to the layout."""
    room = layout_width(term_width) - 2
    rendered = []
    for key, word in key_parts(text):
        rendered.append(styled(key, "dim") + (f" {word}" if word else ""))
    lines, line = [], ""
    for piece in rendered:
        join = "   " + piece if line else piece
        if line and cells(line + "   " + piece) > room:
            lines.append(line)
            line = piece
        else:
            line = line + join if line else piece
    if line:
        lines.append(line)
    return ["  " + line for line in lines]


def progress_bar(done, total, narrow=False):
    """`████░░░░ 4/7`: tasks merged, passed or skipped of all tasks. No fake bar."""
    total = max(0, int(total or 0))
    done = max(0, min(int(done or 0), total)) if total else 0
    size = 4 if narrow else 8
    filled = (round(size * done / total) if total else 0)
    filled = max(0, min(size, filled))
    if utf8():
        bar = "█" * filled + "░" * (size - filled)
    else:
        bar = "#" * filled + "-" * (size - filled)
    return f"{bar} {done}/{total}"


ESC = "\x1b"   # what Esc alone reads as: the single byte with nothing after it


def is_esc(answer):
    """A lone Esc reads as going back, the same as `q`."""
    return answer == ESC


def is_sequence(answer):
    """An arrow key or other escape sequence is not Esc, and not a key either.

    `readline` delivers both as text -- Esc+Enter reads as the single byte, a key
    that sends more bytes reads longer -- so the distinction is what follows it.
    """
    return isinstance(answer, str) and answer.startswith(ESC) and answer != ESC


def frame(name, body=(), keyline="q back"):
    """One sub-screen in the shared frame: the landed docs/cli-design.md chrome,
    then the caller's prompt.

    Built on header_line, rule_line and key_line over layout_width -- never
    re-implemented per screen -- so a sub-screen keeps the menu's widths (capped
    at 120) and its keys read exactly like the menu's, with `q back` first. The
    body sits between the rule and the blank line; the caller reads the prompt,
    so every screen ends the same way.  Over a screen read with the keys it is written over
    in place, in one write, the way the menu is, so moving through it never flickers.
    """
    lines = [header_line(name, time.strftime("%H:%M")), rule_line(), *body, "",
             *key_line(keyline)]
    if taken():
        sys.stdout.write("\033[H" + "".join(f"{line}\033[K\n" for line in lines) + "\033[J")
        sys.stdout.flush()
        return
    if (sys.stdout.isatty() and os.environ.get("TERM", "dumb") != "dumb"
            and "NO_COLOR" not in os.environ):
        print("\033[2J\033[H", end="")
    for line in lines:
        print(line)


_HALF_TYPED = b""   # what a bounded wait had to take off a pipe before it knew where the line ended


def _own_stdin():
    """The descriptor this process reads itself, or None when the line is `input()`'s to take.

    Only a stdin with no descriptor at all -- a StringIO under a test -- is `input()`'s, for
    want of anything else to read.  A pipe, a file or a terminal is read here, byte by byte, and
    nowhere else: Python's buffer would happily swallow the *next* answer along with this one,
    and a line stranded in it is invisible to `select` and lost to the screen waiting for it.
    A terminal is no exception: its line discipline, switched back on under keys the menu had
    not read yet, hands them all over in one read, and a key held in Python's buffer is one the
    menu never sees.  Its echo and its line editing are the line discipline's, not `input()`'s.
    """
    try:
        return sys.stdin.fileno()
    except (OSError, ValueError):
        return None


def readline(prompt=""):
    """One line from stdin, or None at its end; the prompt goes up first either way.

    The one place a line is taken off stdin, so the menu's bounded wait and every question
    under it read the same stdin one after another with nothing stranded between them.

    The gathering is in bytes and the decoding is here, once the line is whole: half of an
    `é` is not a character, and decoding a byte at a time would turn a `café` typed into a
    pipe into `caf??` on its way to a project's name.

    A mouse report is never part of a line: one reaches a keyboard's line when the menu gave
    the terminal over in the middle of a click (`Keyboard.give`), however late it comes.
    """
    global _HALF_TYPED
    keyboard = _own_stdin()
    if keyboard is None:
        half, _HALF_TYPED = _HALF_TYPED.decode("utf-8", "replace"), b""
        try:      # anything a wait took without finding its newline is still this line's
            return half + input(prompt)
        except EOFError:
            return half or None
    sys.stdout.write(prompt)
    sys.stdout.flush()
    while b"\n" not in _HALF_TYPED:
        byte = os.read(keyboard, 1)
        if not byte:
            line, _HALF_TYPED = _HALF_TYPED, b""
            return _REPORT.sub("", line.decode("utf-8", "replace")) or None
        _HALF_TYPED += byte
    line, _, _HALF_TYPED = _HALF_TYPED.partition(b"\n")
    return _REPORT.sub("", line.decode("utf-8", "replace"))


def wait_line(timeout, wake=None):
    """Wait up to `timeout` seconds for a whole line to be there, on a stdin that is no terminal.

    A pipe hands over whatever has been written, and a writer that stops mid-line must not be
    able to stop the menu's clock -- so the line is gathered a byte at a time with the
    deadline checked between them, and what the clock interrupts stays in `_HALF_TYPED` for
    the next wait and for `readline` after it -- as bytes, because a multibyte character the
    clock lands in the middle of is still that character.  Nothing typed is ever lost, and
    nothing is taken beyond the line's end, which is what leaves the next answer for whoever
    asks next.

    True once there is a line to read (or stdin has ended, which `readline` answers with
    None), False when the clock ran out first and the caller should come round again.
    """
    global _HALF_TYPED
    keyboard = _own_stdin()
    deadline = time.monotonic() + timeout
    watching = [keyboard] + ([wake] if wake is not None else [])
    while b"\n" not in _HALF_TYPED:
        left = deadline - time.monotonic()
        if left <= 0 or keyboard not in select.select(watching, [], [], left)[0]:
            return False
        byte = os.read(keyboard, 1)
        if not byte:
            return True            # end of input, which is how a script says `q`
        _HALF_TYPED += byte
    return True


class Key(namedtuple("Key", "name char col row", defaults=("", 0, 0))):
    """One key off a keyboard read a key at a time: `name` says which.

    up, down, left, right, home, end, enter, esc, backspace, tab, space; `char`, the one that
    carries a character; `click`, a left click at `col` and `row`, counted from 1 the way the
    terminal counts them, read when the button comes up; `wheel-up` and `wheel-down`; `eof`, a
    keyboard that is gone or ^D; and `other` for a sequence no screen asks about.
    """
    __slots__ = ()


# The alternate screen, the cursor hidden, and clicks and the wheel reported in SGR form (1006);
# and all of it undone, in the reverse order.
TAKE = "\033[?1049h\033[?25l\033[?1000h\033[?1006h"
GIVE = "\033[?1006l\033[?1000l\033[?25h\033[?1049l"
_TAKEN = None      # the Keyboard that has the terminal now, or None
_KEYED = b""       # what a keyboard sent past the key it was read for: a byte at most
_PRESSED = False   # the left button went down and has not been read coming up
_REPORT = re.compile(r"\x1b\[<\d+;\d+;\d+[Mm]")   # a mouse report, as mode 1006 sends one


def taken():
    """Whether a `Keyboard` has the terminal, so keys are read one at a time and not in lines."""
    return _TAKEN is not None


class Keyboard:
    """The terminal, a key at a time while the main menu waits on it, and whole again otherwise.

    On a terminal -- stdin and stdout both, and a TERM that is not `dumb` -- `take` switches off
    the line discipline's gathering and its echo (cbreak: ^C still interrupts), moves to the
    alternate screen, hides the cursor and asks for clicks, so a key acts the moment it is
    pressed and no redraw can wipe, merge or drop one.  `give` undoes all of it, down to the
    very attributes `take` found, and the menu gives before anything else touches the terminal:
    a session, `ak update`, a sub-screen that reads a line.  A signal gives it back as well --
    a kill, a hang-up, ^\\, and ^Z, which takes it again on `fg` -- and a resize asks for a draw.
    Anything else -- a pipe, a file, the smoke suite, a test's StringIO -- is never taken, and
    the menu reads it a line at a time, as it always has.
    """

    def __init__(self):
        self.fd = self.out = self.saved = None
        self.kept = {}           # the signal handlers `take` stood in for, for `give` to put back
        self.again = None        # a pipe a resize or a return from ^Z writes to: draw again
        try:
            if (sys.stdin.isatty() and sys.stdout.isatty()
                    and os.environ.get("TERM", "dumb") != "dumb"):
                termios.tcgetattr(sys.stdin.fileno())
                self.fd, self.out = sys.stdin.fileno(), sys.stdout.fileno()
        except (OSError, ValueError, termios.error):
            self.fd = self.out = None
        if self.fd is not None:
            self.again = os.pipe()
            for end in self.again:
                os.set_blocking(end, False)

    def take(self):
        """Keys one at a time from here on; True when there is a terminal to take at all."""
        global _TAKEN
        if self.fd is None:
            return False
        if _TAKEN is self:
            return True
        self.saved = termios.tcgetattr(self.fd)
        _TAKEN = self            # before anything changes, so a signal from here on gives it back
        self._handle()
        attrs = termios.tcgetattr(self.fd)
        attrs[3] &= ~(termios.ICANON | termios.ECHO)
        attrs[6][termios.VMIN], attrs[6][termios.VTIME] = 1, 0
        termios.tcsetattr(self.fd, termios.TCSADRAIN, attrs)
        self._send(TAKE)
        return True

    def give(self):
        """The terminal back exactly as `take` found it: its attributes, its screen, its cursor.

        Nothing past the key that gives it is read, so what he typed after that key is there
        for whoever takes the terminal.  A button still down comes up as no click: the rest of
        it reaches a line `readline` drops it from, or a session's tmux, which reads it as the
        mouse report it is, or the menu again, which never saw that button go down.
        """
        global _TAKEN, _PRESSED
        if _TAKEN is not self:
            return
        self._send(GIVE)
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        _TAKEN, _PRESSED = None, False
        for number, handler in self.kept.items():
            signal.signal(number, handler)
        self.kept = {}

    def close(self):
        self.give()
        for end in self.again or ():
            os.close(end)
        self.again = None

    def _send(self, text):
        try:
            sys.stdout.flush()   # what the screen was sent before this goes out before it
        except (OSError, ValueError, RuntimeError):
            pass                 # a signal landed inside a write; the sequence still goes out
        try:
            os.write(self.out, text.encode())
        except OSError:
            pass

    def _handle(self):
        """Stand in for the signals that would leave the terminal taken; only where nobody else has."""
        if threading.current_thread() is not threading.main_thread():
            return
        for name, handler in (("SIGTERM", self._end), ("SIGHUP", self._end),
                              ("SIGQUIT", self._end), ("SIGTSTP", self._stop),
                              ("SIGWINCH", self._resize)):
            number = getattr(signal, name, None)
            if number is not None and signal.getsignal(number) == signal.SIG_DFL:
                self.kept[number] = signal.signal(number, handler)

    def _end(self, number, frame):
        self.give()                        # which puts the default back, so this ends us
        os.kill(os.getpid(), number)

    def _stop(self, number, frame):
        self.give()
        os.kill(os.getpid(), number)       # stopped here until `fg`
        self.take()
        self._resize(number, frame)

    def _resize(self, number, frame):
        try:
            os.write(self.again[1], b".")
        except (OSError, TypeError):
            pass


def _byte(fd, wait=None):
    """The next byte the keyboard sent: one already read, else one sent within `wait` seconds."""
    global _KEYED
    if not _KEYED:
        if wait is not None and not select.select([fd], [], [], wait)[0]:
            return b""
        _KEYED = os.read(fd, 1)
    byte, _KEYED = _KEYED[:1], _KEYED[1:]
    return byte


def read_key(timeout=None, wake=None):
    """The next key off a taken keyboard, or None when `timeout` seconds pass, when `wake` has
    something to read, or when the screen wants drawing again (a resize, a return from ^Z).

    A key is read a byte at a time and made of as few bytes as it takes, so it leaves nothing
    behind for a screen that reads a line after it.  An Esc alone is told from the start of a
    sequence by what follows it within a twentieth of a second.  A click is read when the
    button comes up, not when it goes down, so whatever the click opens is never handed the
    rest of it.  Waiting for it keeps to `timeout` like any other wait, and a key pressed
    while the button is down is answered at once; should that key give the terminal away,
    the rest of the click is no click (`Keyboard.give`).
    """
    global _PRESSED
    fd = sys.stdin.fileno()
    until = None if timeout is None else time.monotonic() + timeout
    while True:
        if not _KEYED:
            again = _TAKEN.again[0] if _TAKEN is not None else None
            left = None if until is None else max(0, until - time.monotonic())
            ready = select.select([fd] + [end for end in (wake, again) if end is not None],
                                  [], [], left)[0]
            if fd not in ready:
                if again is not None and again in ready:
                    try:
                        os.read(again, 4096)
                    except OSError:
                        pass
                return None
        key = _key(fd)
        if key is None:            # the button went down: the click is when it comes up
            _PRESSED = True
            continue
        if key.name == "click":    # and a button that went down before the keyboard was taken
            key, _PRESSED = key if _PRESSED else Key("other"), False
        return key


def _key(fd):
    """The key the next bytes make, or None for the left button going down."""
    first = _byte(fd)
    if not first:
        return Key("eof")
    if first == b"\x1b":
        return _sequence(fd)
    named = {b"\r": "enter", b"\n": "enter", b"\t": "tab", b" ": "space",
             b"\x7f": "backspace", b"\x08": "backspace", b"\x04": "eof"}
    if first in named:
        return Key(named[first])
    if first[0] < 0x20:
        return Key("other")
    raw = first
    size = 1 if first[0] < 0xc0 else 2 if first[0] < 0xe0 else 3 if first[0] < 0xf0 else 4
    while len(raw) < size:
        more = _byte(fd, 0.05)
        if not more:
            break
        raw += more
    return Key("char", raw.decode("utf-8", "replace"))


def _sequence(fd):
    """What an Esc starts: Esc itself, an arrow, a click, the wheel, or `other`."""
    global _KEYED
    kind = _byte(fd, 0.05)
    if kind not in (b"[", b"O"):
        _KEYED = kind + _KEYED     # the next key's own byte, typed right after the Esc
        return Key("esc")
    body = b""
    while True:
        byte = _byte(fd, 0.05)
        if not byte:
            return Key("other")
        body += byte
        if kind == b"O" or 0x40 <= byte[0] <= 0x7e:
            break
    params, final = body[:-1], body[-1:]
    if params.startswith(b"<") and final in (b"M", b"m"):
        try:
            button, col, row = (int(part) for part in params[1:].split(b";"))
        except ValueError:
            return Key("other")
        if button & 64:
            return Key({0: "wheel-up", 1: "wheel-down"}.get(button & 3, "other"))
        if not button & 99:        # the left button, not a drag: going down is half a click
            return Key("click", "", col, row) if final == b"m" else None
        return Key("other")
    if kind == b"O" and final == b"M":
        return Key("enter")                        # the keypad's own Enter
    return Key({b"A": "up", b"B": "down", b"C": "right", b"D": "left",
                b"H": "home", b"F": "end"}.get(final, "other"))


def step(key):
    """-1, 1 or 0: how far a key moves a highlight -- ↑/↓, k/j and the wheel -- through a list."""
    return ({"up": -1, "wheel-up": -1, "down": 1, "wheel-down": 1}.get(key.name)
            or {"k": -1, "j": 1}.get(key.char, 0))


def highlight(line, mark=True):
    """A list's highlighted row: `›` in the accent colour in its first column, its text bright.

    Every row a list draws starts with a space, so the mark takes it and no column moves; a
    row's second line, on a phone, is brightened without one.  Each colour inside the row ends
    in a reset, and every reset turns the brightness back on.
    """
    if mark:
        line = styled("›" if utf8() else ">", "accent") + line[1:]
    if not colour_depth():
        return line
    return "\033[1m" + line.replace("\033[0m", "\033[0;1m") + "\033[0m"


def key_spans(line):
    """(first column, last column, key) for each item of a drawn key line, counted from 1."""
    text = ANSI.sub("", line)
    return [(cells(text[:item.start()]) + 1, cells(text[:item.end()]),
             item.group().split(" ")[0]) for item in re.finditer(r"\S+(?: \S+)*", text)]


def clicks_its_own(read):
    """A screen read with the keys over the menu's own: a click belongs to the screen it began
    on, so a button that went down before this one was drawn, or goes down on it and comes up
    after it, is no click -- nothing is picked, closed or opened by a press meant elsewhere."""
    @wraps(read)
    def reading(*args, **kwargs):
        global _PRESSED
        _PRESSED = False
        try:
            return read(*args, **kwargs)
        finally:
            _PRESSED = False
    return reading


@clicks_its_own
def choose(choices, default=None, several=False, around=None):
    """One of `choices` picked with the keys, or with `several` a list of them; None on Esc or `q`.

    The list is drawn where the cursor is and drawn over in place as the highlight moves.
    ↑/↓, k/j and the wheel move it; Enter picks the highlighted choice, or with `several` the
    ones marked, which space marks and unmarks.  `default` -- a choice, or with `several` a
    list of them -- starts highlighted, or marked.  The keys are `read_key`'s, so the terminal
    is a `Keyboard`'s already; the main menu is what takes one, and so far nothing else does.

    `around` draws the screen a list is asked inside and returns the row its first choice goes
    on, and is called again whenever the screen wants drawing again -- a resize -- so the list
    and the rows a click is read against are always where that screen now puts them.  There a
    click on a choice picks it, or with `several` marks it, and a click anywhere else goes back.
    """
    marked = set(default or ()) if several else set()
    at = choices.index(default) if not several and default in choices else 0
    drawn, top, again = 0, None, around is not None
    while True:
        if again:
            top, again = around(), False
            if not top:
                return None       # the screen it is asked on has no row for it any more
        lines = []
        for number, choice in enumerate(choices):
            box = ("[x] " if choice in marked else "[ ] ") if several else ""
            line = "  " + cut(box + str(choice), width() - 3)
            lines.append(highlight(line) if number == at else line)
        sys.stdout.write((f"\033[{top};1H" if top else f"\033[{drawn}A" if drawn else "") +
                         "".join(f"\r{line}\033[K\n" for line in lines))
        sys.stdout.flush()
        drawn = len(lines)
        key = read_key()
        if key is None:
            again = around is not None
            continue
        if key.name == "click" and top:
            if not 0 <= key.row - top < len(choices):
                return None
            at = key.row - top
            if not several:
                return choices[at]
            marked ^= {choices[at]}
        elif step(key):
            at = min(max(at + step(key), 0), len(choices) - 1)
        elif key.name == "space" and several and choices:
            marked ^= {choices[at]}
        elif key.name == "enter" and choices:
            return [choice for choice in choices if choice in marked] if several else choices[at]
        elif key.name in ("esc", "eof") or key.char in ("q", "Q"):
            return None


@clicks_its_own
def scroll(name, body, keyline="esc back"):
    """One sub-screen read with the keys, never a line: `frame`'s chrome over the taken screen.

    `body` is the screen's lines for a layout that many columns wide, asked again on every
    draw, so a resize wraps them anew and the rows a click is read against are the drawn ones.
    It is written over in place, the way the main menu is, and when the body runs past the
    screen ↑/↓, k/j and the wheel scroll it, the key line saying so; the height is budgeted
    the menu's way, so the key line is never the part that goes.  Esc, `q` and a click on the
    key line's `esc` go back.  With no keyboard taken -- a pipe, a file -- it is `frame`, and
    reads nothing.
    """
    if not taken():
        frame(name, body(layout_width()), keyline)
        return
    at = 0
    while True:
        text, keys = body(layout_width()), keyline
        room = max(1, height() - 5 - len(key_line(keys)))
        if len(text) > room:
            keys = f"{'↑↓' if utf8() else 'j/k'} scroll   {keyline}"
            room = max(1, height() - 5 - len(key_line(keys)))
        at = min(max(at, 0), max(0, len(text) - room))
        lines = [header_line(name, time.strftime("%H:%M")), rule_line(), *text[at:at + room], ""]
        spans = [(len(lines) + number, first, last, key)
                 for number, line in enumerate(key_line(keys), 1)
                 for first, last, key in key_spans(line)]
        lines += key_line(keys)
        sys.stdout.write("\033[H" + "".join(f"{line}\033[K\n" for line in lines) + "\033[J")
        sys.stdout.flush()
        key = read_key()
        if key is None:
            continue
        clicked = key.name == "click" and any(
            (row, item) == (key.row, "esc") and first <= key.col <= last
            for row, first, last, item in spans)
        if step(key):
            at += step(key)
        elif key.name in ("esc", "eof") or key.char in ("q", "Q") or clicked:
            return


def _read(prompt):
    """One stripped line for `ask` when the caller hands it no reader of its own."""
    answer = readline(prompt)
    if not sys.stdout.isatty():
        print()    # the prompt was answered from a pipe: keep the transcript on separate lines
    return None if answer is None else answer.strip()


def ask(question, default, choices, read=None, *, zero=None, allow=None, suffix=""):
    """One shape-(a) question: its default in brackets, its choices dim above it.

    The choices read `<number> <name>` joined by ` · `, wrapped where the screen
    is narrow, and the answer is a number or a name. A prompt that does not fit
    wraps the same way, on a space, so the terminal never breaks a name. `q`,
    Esc and the end of input
    go back (None); an empty Enter reads back as "" so the caller decides what it
    means -- back on a sub-screen, the default on a new-seat question. Anything
    else is one dim `not a choice: ...` line and the question again with its
    choices.

    Three opt-ins extend it without changing the screens that pass none of them:
    `zero` names an optional choice numbered `0` instead of its position;
    `allow` is asked about an answer that matches no number or name and may
    return a parsed value (the Workers question accepts a list this way).
    A single matching choice still returns its name. `suffix` follows the bracket
    before the colon (the orchestrator's skipped-model reason).
    """
    if read is None:
        read = _read
    prompt = f"{question} [{default}]{suffix}: "
    room = width()
    items = [f"{number} {choice}" for number, choice in enumerate(choices, 1)]
    if zero is not None:
        items.append(f"0 {zero}")
    joined, line = [], ""
    for item in items:
        if cells(item) + 2 > room:
            # one choice wider than the screen: wrap it rather than overflow it
            if line:
                joined.append(line)
                line = ""
            joined += wrap(item, room - 2)
            continue
        added = item if not line else line + " · " + item
        if line and cells(added) + 2 > room:
            joined.append(line)
            line = item
        else:
            line = added
    if line:
        joined.append(line)
    shown = prompt_lines(prompt, room)
    while True:
        for line in joined:
            print("  " + styled(line, "dim"))
        for line in shown[:-1]:
            print(line)
        answer = read(shown[-1])
        if answer is None or answer.lower() == "q" or is_esc(answer):
            return None
        if answer == "":
            return ""
        if is_sequence(answer):
            continue    # neither Esc nor a key: ask again, with no word of error
        if zero is not None and answer == "0":
            return zero
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1]
        if answer in choices:
            return answer
        names = list(choices) + ([zero] if zero is not None else [])
        found = [choice for choice in names if choice.lower() == answer.lower()]
        if len(found) == 1:
            return found[0]
        if allow is not None:
            accepted = allow(answer)
            if accepted is not None:
                return accepted
        print(styled(f"not a choice: {answer!r}", "dim"))


def table_row(texts, widths, indent="", kinds=(), right=()):
    """One table row: fixed columns with two-space gutters, no trailing space.

    Columns in `right` (the row number) are right-aligned, the way the menu's
    numbers always read; the rest are left-aligned. Cut, then style, then pad:
    pads land outside the colour escapes, so lines rstrip clean.
    """
    parts = []
    for i, (text, room) in enumerate(zip(texts, widths)):
        kind = kinds[i] if i < len(kinds) else None
        text = cut(text, room)
        if kind:
            text = styled(text, kind)
        space = " " * max(0, room - cells(text))
        parts.append(space + text if i in right else text + space)
    return (indent + "  ".join(parts)).rstrip()



def seats(rows, room):
    """Number, name, orchestrator, state, note, age; note and age below on a phone."""
    if not rows:
        return []
    rows = [[plain(cell) for cell in row] for row in rows]
    words = [row[3] for row in rows]
    rows = [[*row[:3], state_label(row[3]), *row[4:]] for row in rows]
    natural = [max(cells(row[i]) for row in rows) for i in range(6)]
    narrow = room < 60
    widths = [min(natural[0], 4), min(natural[1], 32), min(natural[2], 16),
              min(natural[3], 17), 0, min(natural[5], 5)]   # glyph + longest word whole
    # Preserve the state and age; long names and model/seat names share the remaining room.
    budget = room - 1 - (6 if narrow else 10) - widths[0] - widths[3]
    if not narrow:
        budget -= widths[5] + min(natural[4], 24)  # keep useful detail beside long names
    while widths[1] + widths[2] > max(2, budget):
        index = 1 if widths[1] >= widths[2] else 2
        widths[index] = max(1, widths[index] - 1)
    widths[4] = max(0, room - 1 - 10 - sum(widths))
    lines = []
    for row, word in zip(rows, words):
        indices = range(4) if narrow else range(6)
        parts = []
        for i in indices:
            cell = pad(row[i], widths[i], right=i in (0, 5))
            kind = state_tone(word) if i == 3 else (
                "bold" if i == 1 else "dim" if i in (0, 2, 5) else None)
            parts.append(styled(cell, kind) if kind else cell)
        lines.append(" " + "  ".join(parts).rstrip())
        if narrow:
            note_room = max(0, room - 3 - 2 - widths[5])
            lines.append("   " + pad(row[4], note_room) + "  " +
                         styled(pad(row[5], widths[5], right=True), "dim"))
    return lines
