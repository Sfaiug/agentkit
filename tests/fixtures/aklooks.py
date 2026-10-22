"""How each cell of a Terminal looks: its attributes and colours, read back from tmux.

tmux keeps a cell's look, not the bytes that drew it, and `Terminal.screen(colours=True)` writes
that look back in SGR sequences of its own.  So a test asks what a cell looks like, in SGR's
terms -- `1` bold, `2` dim, a colour as `38;2;R;G;B`, `38;5;N` or `36` -- and never which
sequence drew it: another build may draw the same cell another way.

    from fixtures.aklooks import look, settled
    screen = settled(menu, "esc leave")
    assert look(screen, "›") == {"1", "38;2;137;180;250"}
"""

import re
import time

SGR = re.compile(r"\x1b\[([0-9;]*)m")
ATTRIBUTES = {"1", "2", "3", "4", "5", "7", "8", "9"}
OFF = {"22": {"1", "2"}, "23": {"3"}, "24": {"4"}, "25": {"5"}, "27": {"7"}, "28": {"8"},
       "29": {"9"}}


def looks(capture):
    """Each line of a capture as [(character, its look)], a look being the frozenset of the
    attributes and colours on that cell.  A look lasts until it changes, across lines too, as
    tmux writes it."""
    lines, attributes, colour = [], set(), {"38": None, "48": None}
    for text in capture.split("\n"):
        line, at = [], 0
        for code in [*SGR.finditer(text), None]:
            shown = frozenset(attributes | {own for own in colour.values() if own})
            line += [(char, shown) for char in text[at:code.start() if code else len(text)]]
            if code is None:
                break
            at = code.end()
            parts = (code.group(1) or "0").split(";")
            while parts:
                part = parts.pop(0) or "0"
                if part == "0":
                    attributes, colour = set(), {"38": None, "48": None}
                elif part in ATTRIBUTES:
                    attributes.add(part)
                elif part in OFF:
                    attributes -= OFF[part]
                elif part in ("38", "48"):
                    taken = 2 if parts[:1] == ["5"] else 4
                    colour[part], parts = ";".join([part, *parts[:taken]]), parts[taken:]
                elif part in ("39", "49"):
                    colour[part[0] + "8"] = None
                elif int(part) in (*range(30, 38), *range(90, 98)):
                    colour["38"] = part
                elif int(part) in (*range(40, 48), *range(100, 108)):
                    colour["48"] = part
        lines.append(line)
    return lines


def plain(line):
    """A line of `looks` as the text it shows."""
    return "".join(char for char, _ in line)


def look(lines, text, on=None):
    """The one look every cell of `text` has, on the first line that shows `on` as well (or
    only `text`); its cells drawn in several looks fail the test, naming them."""
    for line in lines:
        if text in plain(line) and (on is None or on in plain(line)):
            at = plain(line).index(text)
            found = {shown for _, shown in line[at:at + len(text)]}
            assert len(found) == 1, f"{text!r} is drawn in several looks: {found}"
            return set(found.pop())
    raise AssertionError(f"no line shows {text!r}" + (f" beside {on!r}" if on else ""))


def colours(lines):
    """Every colour drawn anywhere on the screen, text's and background's alike."""
    return {part for line in lines for _, shown in line for part in shown} - ATTRIBUTES


def settled(term, shown, still=1, bound=30):
    """The looks of a Terminal's screen once it shows `shown` (text, or a test of the text) and
    has not changed for `still` seconds: news on a screen glows and pulses before it rests in
    its colours.  A program that has ended fails at once."""
    ready = shown if callable(shown) else (lambda text: shown in text)
    deadline, last, since = time.monotonic() + bound, None, None
    while True:
        capture = term.screen(colours=True)
        if capture != last:
            last, since = capture, time.monotonic()
        elif ready(SGR.sub("", capture)) and time.monotonic() - since >= still:
            return looks(capture)
        if term.status.exists() or time.monotonic() > deadline:
            raise AssertionError(f"the terminal never rested on {shown!r}; it shows:\n"
                                 f"{SGR.sub('', capture)}")
        time.sleep(0.1)
