"""The harness in a test seat's pane: it shows a screen and keeps what is typed into it.

    python3 akpane.py SCREEN TYPED [COMPOSER]

It draws the text of the file SCREEN, again whenever that file changes or a key comes, and
appends each byte it reads to TYPED as it comes.  As a harness's own composer does, the last
line starting with COMPOSER (`❯` unless given) shows what has been typed since the last Enter,
a paste and its line breaks included; each line entered goes to TYPED.lines as one JSON string.
Each frame ends by setting the pane's title to the `stamp` of what it drew: tmux reads a pane's
output in order, so once the title reads it the frame is on the screen, however tmux laid it
out.  It takes the terminal in raw mode with bracketed paste on, as the harnesses do, and runs
until its pane is killed.
"""

import json
import os
from pathlib import Path
import re
import select
import sys
import tty
import zlib

# A key a terminal writes as one sequence: a paste mark, an arrow, a function key.  Any other
# Esc is the Esc key, whatever follows it: ak may type its own `[audit]` right after one.
KEY = re.compile(r"\x1b\[[0-9;]*[A-Z~]|.", re.S)


def compose(typed):
    """What a harness's composer makes of every key typed so far: its draft, and each line
    entered with Enter.  Read whole each time, a sequence split across reads is never seen
    half; inside a bracketed paste every key is part of the draft, a line break or tab too."""
    draft, pasting, entered = "", False, []
    for key in KEY.findall(typed):
        if key in ("\x1b[200~", "\x1b[201~"):
            pasting = key == "\x1b[200~"
        elif pasting:
            draft += "\n" if key == "\r" else key
        elif key in ("\r", "\n"):
            entered.append(draft)
            draft = ""
        elif key == "\x7f":
            draft = draft[:-1]
        elif key == "\x15":
            draft = ""
        elif key.isprintable():
            draft += key
    return draft, entered


def stamp(screen, typed):
    """The title a frame of `screen` (bytes) sets once it is drawn behind `typed` bytes."""
    return f"akpane {zlib.crc32(screen):08x} {typed}"


def drawn(screen, draft, composer):
    lines = screen.split("\n")
    at = max((i for i, line in enumerate(lines) if line.lstrip().startswith(composer)),
             default=None)
    # Untouched until something is typed: a chooser's selected line starts with `❯` too.
    if at is not None and draft:
        indent = lines[at][:lines[at].index(composer)]
        lines[at:at + 1] = f"{indent}{composer} {draft}".split("\n")
    return "\x1b[H\x1b[2J" + "\r\n".join(lines).rstrip("\r\n")


def main(screen_path, typed_path, composer="❯"):
    screen_path, typed_path = Path(screen_path), Path(typed_path)
    lines_path = typed_path.with_name(typed_path.name + ".lines")
    tty.setraw(0)
    os.write(1, b"\x1b[?2004h")
    stamp_seen, typed, written = None, b"", 0
    while True:
        now = screen_path.stat().st_mtime_ns
        got = os.read(0, 4096) if select.select([0], [], [], 0.05)[0] else None
        if got == b"":
            return
        if got:
            typed += got
            with typed_path.open("ab") as keep:
                keep.write(got)
        draft, entered = compose(typed.decode("utf-8", errors="replace"))
        if len(entered) > written:
            with lines_path.open("a", encoding="utf-8") as lines:
                lines.writelines(json.dumps(line) + "\n" for line in entered[written:])
            written = len(entered)
        if now != stamp_seen or got:
            stamp_seen = now
            screen = screen_path.read_bytes()
            frame = drawn(screen.decode("utf-8"), draft, composer)
            os.write(1, f"{frame}\x1b]2;{stamp(screen, len(typed))}\x1b\\".encode())


if __name__ == "__main__":
    main(*sys.argv[1:])
