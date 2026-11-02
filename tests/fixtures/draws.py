"""What a screen on a test's pty shows after each draw: only changed rows are written of it."""

import re


def draws(text, after=0):
    """The screen after each whole update in `text` from `after` on, newest first, as the whole
    draw it comes to: its rows, each ended by a newline, then `\\x1b[J`.  A clock's cell is no row."""
    rows, found = [], []
    for update in re.finditer(r"\x1b\[\?2026h(.*?)\x1b\[\?2026l", text, re.S):
        parts = re.split(r"\x1b\[H|\x1b\[(\d+);(\d+)H", update[1].replace("\x1b8", ""))
        for row, column, written in zip(parts[1::3], parts[2::3], parts[3::3]):
            if row is None:
                rows = written.partition("\x1b[J")[0].split("\n")[:-1]
            elif "\x1b[J" in written:
                del rows[int(row) - 1:]
            elif column == "1" and (written.endswith("\x1b[K") or len(
                    re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", written)) > 1):
                rows += [""] * (int(row) - len(rows))
                rows[int(row) - 1] = written
        if update.start() >= after:
            found.append("".join(line + "\n" for line in rows) + "\x1b[J")
    return found[::-1]
