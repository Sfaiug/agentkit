"""The harness in a test seat's pane: it shows a screen and keeps what is typed into it.

    python3 akpane.py SCREEN TYPED [COMPOSER]

It draws the text of the file SCREEN, again whenever that file changes, and appends each byte it
reads to TYPED as it comes.  As a harness's own composer does, the last line starting with
COMPOSER (`❯` unless given) shows what has been typed since the last Enter, a paste included;
Enter empties it and adds the line to TYPED.lines as one JSON string.  It takes the terminal in
raw mode with bracketed paste on, as the harnesses do, and runs until its pane is killed.
"""

import codecs
import json
import os
from pathlib import Path
import re
import select
import sys
import tty

KEY = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|.)", re.S)   # arrows, paste brackets, Esc


def drawn(screen, draft, composer):
    lines = screen.split("\n")
    at = max((i for i, line in enumerate(lines) if line.lstrip().startswith(composer)),
             default=None)
    # Untouched until something is typed: a chooser's selected line starts with `❯` too.
    if at is not None and draft:
        lines[at] = lines[at][:lines[at].index(composer)] + f"{composer} {draft}"
    return "\x1b[H\x1b[2J" + "\r\n".join(lines).rstrip("\r\n")


def main(screen_path, typed_path, composer="❯"):
    screen_path, typed_path = Path(screen_path), Path(typed_path)
    lines_path = typed_path.with_name(typed_path.name + ".lines")
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    tty.setraw(0)
    os.write(1, b"\x1b[?2004h")
    stamp, draft = None, ""
    while True:
        now = screen_path.stat().st_mtime_ns
        got = os.read(0, 4096) if select.select([0], [], [], 0.05)[0] else None
        if got == b"":
            return
        if got:
            with typed_path.open("ab") as typed:
                typed.write(got)
        text = KEY.sub("", decoder.decode(got or b""))
        for char in text:
            if char in "\r\n":
                with lines_path.open("a") as lines:
                    lines.write(json.dumps(draft) + "\n")
                draft = ""
            elif char == "\x7f":
                draft = draft[:-1]
            elif char == "\x15":
                draft = ""
            elif char.isprintable():
                draft += char
        if now != stamp or text:
            stamp = now
            os.write(1, drawn(screen_path.read_text(), draft, composer).encode())


if __name__ == "__main__":
    main(*sys.argv[1:])
