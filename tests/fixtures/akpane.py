"""The harness in a test seat's pane: it shows a screen and keeps what is typed into it.

    python3 akpane.py [--editor] SCREEN TYPED [COMPOSER [ASKS]]

It draws the text of the file SCREEN, again whenever that file changes, a key comes or its
terminal is resized, and appends each byte it reads to TYPED as it comes.  As a harness's own
composer does, the last line starting with COMPOSER (`❯` unless given) shows, after its mark,
what has been typed since the last Enter, a paste and its line breaks included -- a
COMPOSER running on to a placeholder picks that row of a box (`┃  Ask anything…`); each line
entered goes to TYPED.lines as one JSON string.  ASKS, a JSON object, maps a line's start to
the screen of a card the harness asks before it takes such a line, as Claude Code's `/model`
does: entered, the line draws that card in SCREEN's place, every key going to it until a `1`,
its yes, puts it away.  With --editor, Ctrl-G hands the composer to $VISUAL in a file, and what
that leaves there is the composer then, as Claude Code's and Codex's Ctrl-G do.
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
import subprocess
import sys
import tempfile
import tty
import zlib

# A key a terminal writes as one sequence: a paste mark, an arrow, a function key.  Any other
# Esc is the Esc key, whatever follows it: ak may type its own `[audit]` right after one.
KEY = re.compile(r"\x1b\[[0-9;]*[A-Z~]|.", re.S)


def compose(typed, asks=None, edits=None):
    """What a harness's composer makes of every key typed so far: its draft, each line
    entered with Enter, the card one of `asks` raised that stands, else None, and the draft a
    Ctrl-G its editor has yet to hand back opens it on, else None.  Read whole each time, a
    sequence split across reads is never seen half; inside a bracketed paste every key is part
    of the draft, a line break or tab too.  Given `edits`, what the editor left at each Ctrl-G
    so far, each is the draft from there, and the keys past one it has yet to leave wait."""
    draft, pasting, entered, card = "", False, [], None
    edits = None if edits is None else iter(edits)
    for key in KEY.findall(typed):
        if card is not None:
            card = None if key == "1" else card
        elif key in ("\x1b[200~", "\x1b[201~"):
            pasting = key == "\x1b[200~"
        elif pasting:
            draft += "\n" if key == "\r" else key
        elif key == "\x07" and edits is not None:
            edit = next(edits, None)
            if edit is None:
                return draft, entered, card, draft
            draft = edit
        elif key in ("\r", "\n"):
            entered.append(draft)
            card = next((shown for start, shown in (asks or {}).items()
                         if draft.startswith(start)), None)
            draft = ""
        elif key == "\x7f":
            draft = draft[:-1]
        elif key == "\x15":
            draft = ""
        elif key.isprintable():
            draft += key
    return draft, entered, card, None


def edited(draft):
    """What $VISUAL leaves in the file it is handed `draft` in, as a harness's Ctrl-G hands it."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "composer.md"
        path.write_text(draft, encoding="utf-8")
        subprocess.run([os.environ["VISUAL"], str(path)], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return path.read_text(encoding="utf-8")


def stamp(screen, typed):
    """The title a frame of `screen` (bytes) sets once it is drawn behind `typed` bytes."""
    return f"akpane {zlib.crc32(screen):08x} {typed}"


def drawn(screen, draft, composer, height):
    """A frame of `screen` in a terminal `height` rows tall, its composer showing `draft` and
    holding the cursor, as a harness's own composer does: OpenCode is typed into only while the
    cursor sits in its box.  Rows past the terminal's scroll its top away."""
    lines = screen.split("\n")
    at = max((i for i, line in enumerate(lines) if line.lstrip().startswith(composer)),
             default=None)
    # Untouched until something is typed: a chooser's selected line starts with `❯` too.
    if at is not None and draft:
        indent = lines[at][:lines[at].index(composer)]
        # its mark: COMPOSER up to a placeholder two spaces on, a box's edge too (`│ ❯`)
        rows = f"{indent}{composer.split('  ')[0]} {draft}".split("\n")
        lines[at:at + 1] = rows
        at += len(rows) - 1
    frame = "\r\n".join(lines).rstrip("\r\n")
    row = None if at is None else at - max(0, frame.count("\n") + 1 - height)
    return ("\x1b[H\x1b[2J" + frame
            + (f"\x1b[{row + 1};{len(lines[at]) + 1}H" if row is not None and row >= 0 else ""))


def main(screen_path, typed_path, composer="❯", asks=None, editor=False):
    screen_path, typed_path = Path(screen_path), Path(typed_path)
    asks = json.loads(Path(asks).read_text()) if asks else None
    lines_path = typed_path.with_name(typed_path.name + ".lines")
    tty.setraw(0)
    os.write(1, b"\x1b[?2004h")
    stamp_seen, typed, written, size, edits = None, b"", 0, None, [] if editor else None
    while True:
        now = screen_path.stat().st_mtime_ns
        got = os.read(0, 4096) if select.select([0], [], [], 0.05)[0] else None
        if got == b"":
            return
        if got:
            typed += got
            with typed_path.open("ab") as keep:
                keep.write(got)
        draft, entered, card, opening = compose(typed.decode("utf-8", errors="replace"), asks,
                                                edits)
        while opening is not None:
            edits.append(edited(opening))
            draft, entered, card, opening = compose(typed.decode("utf-8", errors="replace"),
                                                    asks, edits)
        if len(entered) > written:
            with lines_path.open("a", encoding="utf-8") as lines:
                lines.writelines(json.dumps(line) + "\n" for line in entered[written:])
            written = len(entered)
        # a resize redraws, as a harness does: tmux drops the rows under a cursor when a pane
        # shrinks, and this cursor sits on the composer's
        shape = os.get_terminal_size(0)
        if now != stamp_seen or got or shape != size:
            stamp_seen, size = now, shape
            screen = screen_path.read_bytes() if card is None else card.encode()
            frame = drawn(screen.decode("utf-8"), draft, composer, size.lines)
            os.write(1, f"{frame}\x1b]2;{stamp(screen, len(typed))}\x1b\\".encode())


if __name__ == "__main__":
    main(*(arg for arg in sys.argv[1:] if arg != "--editor"), editor="--editor" in sys.argv)
