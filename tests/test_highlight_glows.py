"""Where the highlight left fades from the selection into the background in 0.2 s (the owner, 12
Nov 2026: "glowing effect ... when selection things"), on tests/test_news_motion.py's clock, in a
terminal of 24-bit colour that sets no background: the cells ak writes, read as written."""

import io
import os
import re
import sys
import types
import unittest
from unittest.mock import patch

from test_news_motion import CELL, Menu
from agentkit import menu, motion, terminal

ESC, DOWN = b"\x1b", b"\x1b[B"
SELECTION = ("8", "48", "93")       # the black theme's, over its black background
BACKS = re.compile(r"48;2;(\d+);(\d+);(\d+)")
POINT = "\x1b[<35;{};{}M"             # the pointer moved, as modes 1003 and 1006 report it
DRAW = re.compile(r"(\x1b\[H.*?\x1b\[J)", re.S)


def lines(screen):
    """A whole draw's lines, row 1 first, as written."""
    return DRAW.search(screen).group()[3:-3].split("\n")


def writes(waits, since):
    """Each cell written from wait `since` on, in order: (when, (row, column), text), a whole
    draw's lines each at its row's first column."""
    found = []
    for _, when, text in waits[since:]:
        for part in DRAW.split(text):
            found += ([(when, (row, 1), line) for row, line in enumerate(lines(part), 1)]
                      if DRAW.fullmatch(part) else
                      [(when, (int(row), int(column)), what)
                       for row, column, what in CELL.findall(part)])
    return found


class Fades(Menu):
    def setUp(self):
        super().setUp()
        self.words = {"fix-api": "idle", "web-portal": "idle"}      # nothing breathes
        # the keyboard's own clock is the menu's, so a move is answered as the frames go
        self.stack.enter_context(patch.object(terminal, "time", menu.time))

    def typed(self, script, after=1.0):
        """`menu.loop`'s waits, and after which each step but None was taken: the bytes of a key
        typed, or a function run as a frame's time passes, as None is that time alone; then the
        frames on until nothing moves or `after`, and Esc."""
        read, write = os.pipe()
        out, waits, read_at, steps = io.StringIO(), [], [], list(script)
        out.isatty = lambda: True
        real, began = terminal.read_key, self.now

        def read_key(timeout=None, wake=None):
            waits.append((timeout, self.now, re.sub(r"\x1b\[\?2026[hl]", "", out.getvalue())))
            out.seek(0)
            out.truncate()
            if steps:
                step = steps.pop(0)
                if step is None or callable(step):
                    self.sleep(motion.FRAME if timeout is None else min(timeout, motion.FRAME))
                    if step:
                        step()
                        read_at.append(len(waits))
                    return None
            elif timeout is not None and timeout <= motion.FRAME and self.now - began < after:
                self.sleep(timeout)
                return None
            else:
                step = ESC
            read_at.append(len(waits))      # its draw is written before the next wait
            os.write(write, step)
            return real(0)

        with open(read, "rb", buffering=0) as stdin, patch.object(sys, "stdin", stdin), \
                patch("sys.stdout", out), patch.object(terminal, "read_key", read_key), \
                patch.multiple(terminal, _TAKEN=types.SimpleNamespace(again=(None, None)),
                               _KEYED=b"", _PRESSED=False, _POINTER=None, _SPOTS={},
                               _POINTED=terminal.Spot(), _MOVED=0.0, _NEXT=None, _HELD=None,
                               _AWAY=False, _ASKED=False, _UP=None):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        os.close(write)
        return waits, read_at

    def row(self, waits, name):
        return self.cell(waits[0][2], name, name)[0]

    def leaves(self, cells, at):
        """`cells`' writes at `at`, (row, column), each moment's last: the first on the
        selection, each after it nearer the background, and from LEAVES seconds on, on none."""
        frames = {when: set(BACKS.findall(text)) for when, cell, text in cells if cell == at}
        self.assertTrue(frames, f"nothing written at {at}")
        first = min(frames)
        fading = [backs for when, backs in frames.items() if when < first + motion.LEAVES]
        self.assertEqual(fading[0], {SELECTION})
        self.assertTrue(all(len(backs) == 1 for backs in fading), fading)
        steps = [sum(map(int, back)) for (back,) in fading]
        self.assertGreaterEqual(len(steps), 4, steps)
        self.assertEqual(steps, sorted(set(steps), reverse=True), steps)
        rest = [backs for when, backs in frames.items() if when >= first + motion.LEAVES]
        self.assertTrue(rest)
        self.assertEqual([backs for backs in rest if backs], [])

    def lit_alone(self, waits, at, name):
        """The screen drawn at wait `at` and every cell written after it: `name`'s row on the
        selection and no other cell on a background."""
        screen = DRAW.search(waits[at][2]).group()
        row = self.cell(screen, "› ", name)[0]
        self.assertEqual({(number, back) for number, line in enumerate(lines(screen), 1)
                          for back in BACKS.findall(line)}, {(row, SELECTION)})
        after = waits[at][2].partition(screen)[2]
        self.assertLessEqual({(at, back) for _, (at, _), text in writes(
            [(None, None, after), *waits[at + 1:]], 0) for back in BACKS.findall(text)},
            {(row, SELECTION)})

    def test_down_fades_the_row_it_left(self):
        waits, (down, *_) = self.typed([None, DOWN])
        self.cell(waits[down][2], "› ", "web-portal")
        self.leaves(writes(waits, down), (self.row(waits, "fix-api"), 1))

    def test_a_second_down_ends_the_first_fade_and_starts_its_own(self):
        self.words["acme"] = "idle"
        waits, (_, again, *_) = self.typed([None, DOWN, None, DOWN])
        ended, _, _ = DRAW.split(waits[again][2], maxsplit=1)
        first = self.row(waits, "fix-api")
        self.assertEqual([BACKS.findall(text) for _, (row, _), text in writes(
            [(None, None, ended)], 0) if row == first][-1:], [[]])
        self.cell(waits[again][2], "› ", "acme")
        cells = writes(waits, again)
        self.assertEqual([text for _, (row, _), text in cells
                          if row == first and BACKS.search(text)], [])
        self.leaves(cells, (self.row(waits, "web-portal"), 1))

    def test_a_number_waits_for_its_second_digit_with_the_fade_ended(self):
        self.words.update({f"acme-{n}": "idle" for n in range(8)})    # ten: 1 waits for a 0
        with patch.object(menu, "open_session", return_value=None):
            waits, (_, digit, *_) = self.typed([None, DOWN, None, b"1"])
        self.assertEqual(waits[digit][0], 0.5)      # for a second digit, nothing drawn
        row = self.row(waits, "fix-api")
        ended = [text for at, _, text in CELL.findall(waits[digit][2]) if int(at) == row]
        self.assertTrue(ended)
        self.assertEqual(BACKS.findall(ended[-1]), [])

    def test_the_pointer_going_off_a_meter_fades_its_cell(self):
        screen = self.typed([])[0][0][2]
        meter = self.cell(screen, "Claude", "Claude")
        blank = next(row for row, line in enumerate(lines(screen), 1)
                     if row > meter[0] and not terminal.ANSI.sub("", line).strip())
        to = [POINT.format(meter[1] + 2, row).encode() for row in (meter[0], blank)]
        waits, (onto, off, *_) = self.typed([None, to[0], *[None] * 8, to[1]])
        on = lines(waits[onto][2])[meter[0] - 1]
        lit = [n for n, back in enumerate(terminal._grounds(on), 1) if back == "48;2;8;48;93"]
        self.assertIn(meter[1], lit)
        self.assertEqual(lit, list(range(lit[0], lit[-1] + 1)))     # its cell, whole
        self.leaves(writes(waits, off), (meter[0], lit[0]))

    def test_the_ak_screen_is_first_drawn_with_its_highlight_alone_at_rest(self):
        waits, _ = self.typed([None] * 6)
        self.lit_alone(waits, 0, "fix-api")

    def test_a_resize_in_the_middle_of_a_fade_draws_the_highlight_alone_at_rest(self):
        size = [100]

        def resized():
            size[0], terminal._ASKED = 90, True
        with patch.object(terminal, "width", lambda *args: size[0]):
            waits, (_, at, _) = self.typed([None, DOWN, None, resized])
        self.lit_alone(waits, at, "web-portal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
