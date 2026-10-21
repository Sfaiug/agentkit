"""The harness in a test seat's pane: it shows a screen and keeps what is typed into it.

    python3 akpane.py SCREEN TYPED [COMPOSER]

It draws the text of the file SCREEN, again whenever that file changes, and appends each byte it
reads to TYPED as it comes.  As a harness's own composer does, the last line starting with
COMPOSER (`❯` unless given) shows what has been typed since the last Enter, a paste included,
its line breaks too; Enter empties it and adds the line to TYPED.lines as one JSON string.  It
takes the terminal in raw mode with bracketed paste on, as the harnesses do, and runs until its
pane is killed.
"""

import codecs
import json
import os
from pathlib import Path
import re
import select
import sys
import tty

KEY = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*[@-~]|.)|.", re.S)   # an escape sequence or a character
# A sequence the input ends inside, finished by what comes next however late.  A lone Esc at
# the end is the Esc key: a terminal writes each key's sequence whole, and ak may type `[` next.
CUT = re.compile(r"\x1b\[[0-9;?]*[ -/]*\Z")


class Composer:
    """What a harness's composer makes of the keys typed into it: its draft, and each line
    entered with Enter.  Inside a bracketed paste a line break is part of the draft."""

    def __init__(self):
        self.draft, self.pasting, self.held = "", False, ""

    def read(self, text):
        """The lines `text` enters."""
        text, entered = self.held + text, []
        cut = CUT.search(text)
        text, self.held = (text[:cut.start()], text[cut.start():]) if cut else (text, "")
        for key in KEY.findall(text):
            if key in ("\x1b[200~", "\x1b[201~"):
                self.pasting = key == "\x1b[200~"
            elif key in ("\r", "\n") and self.pasting:
                self.draft += "\n"
            elif key in ("\r", "\n"):
                entered.append(self.draft)
                self.draft = ""
            elif key == "\x7f":
                self.draft = self.draft[:-1]
            elif key == "\x15":
                self.draft = ""
            elif key.isprintable():
                self.draft += key
        return entered


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
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    tty.setraw(0)
    os.write(1, b"\x1b[?2004h")
    stamp, composing = None, Composer()
    while True:
        now = screen_path.stat().st_mtime_ns
        got = os.read(0, 4096) if select.select([0], [], [], 0.05)[0] else None
        if got == b"":
            return
        if got:
            with typed_path.open("ab") as typed:
                typed.write(got)
        entered = composing.read(decoder.decode(got or b""))
        if entered:
            with lines_path.open("a") as lines:
                lines.writelines(json.dumps(line) + "\n" for line in entered)
        if now != stamp or got:
            stamp = now
            os.write(1, drawn(screen_path.read_text(), composing.draft, composer).encode())

if __name__ == "__main__":
    main(*sys.argv[1:])
