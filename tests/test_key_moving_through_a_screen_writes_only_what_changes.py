"""Moving through a screen writes only the rows that change, and no row goes blank on the way.

Black-box: a real ak on a pty over seats of tests/fixtures/akseat.py, its output fed a byte at a
time through a small terminal model: cursor address, erase and text, colours ignored.
"""

import os
import re
import select
import subprocess
import termios
import time
import unittest

from fixtures.akbin import AK, Home
from fixtures.akseat import Seat

ROWS, DOWN, WHEEL = 54, b"\x1b[B", b"\x1b[<65;20;12M"
WHOLE = re.compile(rb"\x1b(\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(\x07|\x1b\\)|[^\[\]])|[\x00-\x1a\x1c-\x7f]"
                   rb"|[\xc0-\xdf][\x80-\xbf]|[\xe0-\xef][\x80-\xbf]{2}|[\xf0-\xf7][\x80-\xbf]{3}")


class Screen:
    """What a terminal holds; `written`, the rows given text; `broken`, each cell a draw blanked
    that was text before and after it: a draw ends with its update, or at `settled`."""

    def __init__(self, cols):
        self.cols, self.row, self.col, self.held = cols, 0, 0, b""
        self.grid = [[b" "] * cols for _ in range(ROWS)]
        self.broken, self.written, self.blanked = set(), set(), set()
        self.settled()

    def settled(self):
        self.broken |= {(row, col) for row, col in self.blanked
                        if self.before[row][col] != b" " and self.grid[row][col] != b" "}
        self.before, self.blanked = [list(row) for row in self.grid], set()

    def blank(self, row, cols):
        self.blanked |= {(row, col) for col in cols if self.grid[row][col] != b" "}
        self.grid[row][cols.start:cols.stop] = [b" "] * len(cols)

    def byte(self, value):
        self.held += bytes([value])
        if not WHOLE.fullmatch(self.held):
            return
        token, self.held = self.held, b""
        numbers, final = re.findall(rb"\d+", token), token[-1:]
        if token in (b"\x1b[?2026h", b"\x1b[?2026l"):
            self.settled()
        elif token in b"\r\n":
            self.col, self.row = 0, self.row + (token == b"\n")
        elif token[:1] != b"\x1b":
            self.blank(self.row, range(self.col, self.col + (token == b" ")))
            self.grid[self.row][self.col] = token
            self.written.add(self.row)
            self.col += 1
        elif final == b"H":
            self.row, self.col = (int(n) - 1 for n in numbers) if numbers else (0, 0)
        elif token[1:2] == b"[" and final in b"KJ":
            # on a row's last cell, where its text left the cursor, a clear erases that cell
            self.blank(self.row, range(min(self.col, self.cols - 1), self.cols))
            for row in range(self.row + 1, ROWS) if final == b"J" else ():
                self.blank(row, range(self.cols))

    def lines(self):
        return [b"".join(row).decode().rstrip() for row in self.grid]


class Menu:
    """ak's main screen on a pty `cols` wide, read through a `Screen`."""

    def __init__(self, case, cols=116):
        self.screen, self.sent = Screen(cols), b""
        self.master, slave = os.openpty()
        termios.tcsetwinsize(slave, (ROWS, cols))
        proc = subprocess.Popen([AK], stdin=slave, stdout=slave, stderr=slave, cwd=case.home.path,
                                env=case.home._env({"NO_COLOR": None, "TERM": "xterm-256color"}),
                                start_new_session=True)
        os.close(slave)
        case.addCleanup(lambda: (proc.kill(), proc.wait(30), os.close(self.master)))
        self.settle(lambda lines: any("esc leave" in line for line in lines))

    def settle(self, shown=lambda lines: True):
        """Read until the screen is as `shown` asks and nothing has come for a while."""
        deadline = time.monotonic() + 60
        while (ready := select.select([self.master], [], [], 0.7)[0]) or not shown(self.screen.lines()):
            assert time.monotonic() < deadline, "\n".join(self.screen.lines())
            chunk = os.read(self.master, 65536) if ready else b""
            self.sent += chunk
            for value in chunk:
                self.screen.byte(value)

    def press(self, keys, shown=lambda lines: True):
        """`keys` on a still screen, their `written` and `broken`; the rows that differ after."""
        self.settle()
        screen, before = self.screen, [list(row) for row in self.screen.grid]
        screen.broken, screen.written = set(), set()
        os.write(self.master, keys)
        self.settle(shown)
        screen.settled()
        return {row for row, line in enumerate(screen.grid) if line != before[row]}


class Moving(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        for name in ("customer-journey", "mov-rework", "fix-api", "ship-docs", "acme-web"):
            Seat(cls.home, name)

    def test_moving_writes_only_what_changes_blanks_no_text_and_draws_only_in_updates(self):
        menu = Menu(self)
        # Every row is written every TICK anyway, which can fall on the key: asked again.
        for _ in range(3):
            changed = menu.press(DOWN)
            if menu.screen.written <= changed:
                break
        self.assertTrue(changed and menu.screen.written <= changed, menu.screen.lines())
        for keys in (DOWN, DOWN, b"\x1b[A", WHEEL, b"\x1b[<64;20;12M", b"\x1b[<35;20;12M",
                     b"\x1b[<35;20;14M", b"\x1b[<35;4;52M", b"\x1b[<35;60;30M"):
            menu.press(keys)
            self.assertEqual(menu.screen.broken, set(), (keys, menu.screen.lines()))
        self.assertEqual(re.sub(rb"\x1b\[\?2026h.*?\x1b\[\?2026l|\x1b\[\?[\d;]*[hl]|\x1b\]11;\?\x1b\\"
                                rb"|\x1b\[c", b"", menu.sent, flags=re.S), b"", "modes and asks aside")

    def test_back_from_c_the_screen_is_whole_and_a_row_filling_it_keeps_its_last_cell(self):
        menu = Menu(self, cols=80)
        before = menu.screen.lines()
        self.assertRegex(before[0], r"^.{75}\d\d:\d\d$", "the clock ends at the edge")
        menu.press(b"c", lambda lines: "config" in lines[0])
        self.assertEqual(len(menu.screen.lines()[0]), 80, "on `c` too")
        menu.press(b"\x1b", lambda lines: "config" not in lines[0])
        self.assertRegex(menu.screen.lines()[0], r"^.{75}\d\d:\d\d$", "drawn again whole")
        self.assertEqual(menu.screen.lines()[1:], before[1:], "\n".join(menu.screen.lines()))


if __name__ == "__main__":
    unittest.main()
