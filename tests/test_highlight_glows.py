"""Where the highlight comes, by a key or the pointer, it starts 45% of the way from the theme's
selection to its accent and settles onto the selection in 0.25 s; where it left it fades from the
selection into the background in 0.2 s (the owner, 12 Nov 2026: "glowing effect ... when selection
things"), on tests/test_news_motion.py's clock, in a terminal of 24-bit colour that sets no
background: the cells ak writes, read as written."""

import io
import os
import re
import sys
import types
import unittest
from unittest.mock import patch

from test_news_motion import CELL, Keyboard, Menu
from agentkit import menu, motion, terminal

ESC, DOWN = b"\x1b", b"\x1b[B"
# the black theme's background, its selection, and where the highlight comes
BLACK, SELECTION, COMES = "000000", "08305d", "2764a6"
POINT = "\x1b[<35;{};{}M"             # the pointer moved, as modes 1003 and 1006 report it
DRAW = re.compile(r"(\x1b\[H.*?\x1b\[J)", re.S)


def lines(screen):
    """A whole draw's lines, row 1 first, as written."""
    return DRAW.search(screen).group()[3:-3].split("\n")


def backs(text):
    """The backgrounds `text`'s cells are on, as a terminal shows them, `rrggbb` each: a cell on
    none adds none."""
    return {bytes(map(int, ground.split(";")[2:])).hex()
            for ground in terminal._grounds(text) if ground}


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

    def moves(self, cells, at, start, took, end=None):
        """`cells`' writes at `at`, (row, column), each moment's last: the first on `start`, each
        after it nearer `end` -- the background where None -- and from `took` seconds on, on it,
        or on none of its own."""
        frames = {when: backs(text) for when, cell, text in cells if cell == at}
        self.assertTrue(frames, f"nothing written at {at}")
        first = min(frames)
        moving = [backs for when, backs in frames.items() if when < first + took]
        self.assertEqual(moving[0], {start})
        self.assertTrue(all(len(backs) == 1 for backs in moving), moving)
        steps = [sum(abs(a - b) for a, b in zip(bytes.fromhex(rgb), bytes.fromhex(end or BLACK)))
                 for (rgb,) in moving]
        self.assertGreaterEqual(len(steps), 4, steps)
        self.assertEqual(steps, sorted(set(steps), reverse=True), steps)
        rest = [backs for when, backs in frames.items() if when >= first + took]
        self.assertTrue(rest)
        self.assertEqual([backs for backs in rest if backs != ({end} if end else set())], [])

    def comes(self, cells, at):
        self.moves(cells, at, COMES, motion.LANDS, SELECTION)

    def leaves(self, cells, at):
        self.moves(cells, at, SELECTION, motion.LEAVES)

    def lit_alone(self, waits, at, name):
        """From the screen drawn whole at wait `at` on -- after the last frame of what the key
        read there ended -- `name`'s row on the selection and no other cell on a background."""
        _, when, text = waits[at]
        drawn = [(None, when, text[DRAW.search(text).start():]), *waits[at + 1:]]
        row = self.cell(drawn[0][2], "› ", name)[0]
        self.assertEqual({(number, back) for _, (number, _), text in writes(drawn, 0)
                          for back in backs(text)}, {(row, SELECTION)})

    def test_down_lights_the_next_row_from_toward_the_accent_and_fades_the_one_it_left(self):
        waits, (down, *_) = self.typed([None, DOWN])
        self.comes(writes(waits, down), (self.cell(waits[down][2], "› ", "web-portal")[0], 1))
        self.leaves(writes(waits, down), (self.row(waits, "fix-api"), 1))

    def test_on_a_white_terminal_the_highlight_comes_from_its_own_accent(self):
        with patch.object(terminal, "THEME", terminal.WHITE):
            waits, (down, *_) = self.typed([None, DOWN])
        self.moves(writes(waits, down), (self.cell(waits[down][2], "› ", "web-portal")[0], 1),
                   "79b0e5", motion.LANDS, "dcecff")

    def test_a_second_down_ends_the_first_fade_and_starts_its_own(self):
        self.words["acme"] = "idle"
        waits, (_, again, *_) = self.typed([None, DOWN, None, DOWN])
        self.cell(waits[again][2], "› ", "acme")
        cells, first = writes(waits, again), self.row(waits, "fix-api")
        self.assertEqual([text for _, (row, _), text in cells
                          if row == first and backs(text)], [])
        self.leaves(cells, (self.row(waits, "web-portal"), 1))

    def test_a_number_waits_for_its_second_digit_with_the_fade_ended(self):
        self.words.update({f"acme-{n}": "idle" for n in range(8)})    # ten: 1 waits for a 0
        with patch.object(menu, "open_session", return_value=None):
            waits, (_, digit, *_) = self.typed([None, DOWN, None, b"1"])
        self.assertEqual(waits[digit][0], 0.5)      # for a second digit, nothing drawn
        row = self.row(waits, "fix-api")
        ended = [text for at, _, text in CELL.findall(waits[digit][2]) if int(at) == row]
        self.assertTrue(ended)
        self.assertEqual(backs(ended[-1]), set())

    def test_a_number_typed_as_the_pointer_moves_ends_its_fades_and_comes_back_at_rest(self):
        self.words.update({f"acme-{n}": "idle" for n in range(8)})
        rows = [self.row(self.typed([])[0], name) for name in ("web-portal", "acme-0")]
        points = [POINT.format(12, row).encode() for row in rows]
        with patch.object(menu, "open_session", return_value=None):
            waits, (*_, opened, _) = self.typed([b"1", points[0], None, points[1], None, b"0"])
        self.lit_alone(waits, opened, "acme-7")         # seat 10, as the menu is back from it

    def test_the_pointer_moving_while_a_number_waits_fades_the_row_it_left(self):
        self.words.update({f"acme-{n}": "idle" for n in range(8)})
        screen = self.typed([])[0]
        to = POINT.format(12, self.row(screen, "web-portal")).encode()
        with patch.object(menu, "open_session", return_value=None):
            waits, (_, moved, *_) = self.typed([None, b"1", to, *[None] * 5, b"0"])
        self.leaves(writes(waits, moved), (self.row(screen, "fix-api"), 1))

    def test_a_number_on_past_sessions_waits_with_the_fade_ended(self):
        found = [{"name": f"acme-{n}", "repo": None, "path": "/", "created": 9000,
                  "closed": 9500 - n} for n in range(10)]
        with patch.object(menu, "open_session", return_value=None), \
                patch.object(terminal, "taken", return_value=True):
            waits, _ = self.run_menu([None, terminal.Key("down"), None, terminal.Key("char", "1")],
                                     screen=lambda: menu.show_past(self.cfg, found,
                                                                   keyboard=Keyboard()))
        digit = next(n for n, (timeout, _, _) in enumerate(waits) if timeout == 0.5)
        row = next(at for _, (at, _), text in writes(waits, 0) if "acme-0" in terminal.plain(text))
        written = [backs(text) for _, (at, _), text in writes(waits[:digit + 1], 0)
                   if at == row]
        self.assertIn({SELECTION}, written)         # lit till Down, then fading
        self.assertEqual(written[-1], set())

    def test_the_pointer_lights_a_meter_and_fades_it_as_it_goes(self):
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
        self.comes(writes(waits[:off], onto), (meter[0], lit[0]))
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
