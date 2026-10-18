"""A seat's count counts with its progress line: from nothing as ak opens, from where it was as
its plan moves, each digit that changes in the line's colour for a moment.

The owner's pick of 18 Oct 2026, "numbers that roll".  Offline: a temporary HOME, fake seats,
the motion clock read at the times it is handed, no terminal.
"""

from contextlib import redirect_stdout
import io
import os
import re
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, motion, terminal  # noqa: E402


def painted(text):
    """Each cell's colour, `#rrggbb`, or None where it is plain."""
    colour, out = None, []
    for code, char in re.findall(r"((?:\033\[[\d;]*m)*)([^\033])", text):
        for found in re.findall(r"\033\[([\d;]*)m", code):
            rgb = re.search(r"38;2;(\d+);(\d+);(\d+)", found)
            colour = ("#" + "".join(f"{int(c):02x}" for c in rgb.groups()) if rgb else
                      None if found.startswith("0") or found == "" else colour)
        out.append(colour)
    return out


def near(one, other):
    return sum(abs(int(one[n:n + 2], 16) - int(other[n:n + 2], 16)) for n in (1, 3, 5))


class Rolls(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=24))
        self.stack.enter_context(patch.object(terminal, "_POINTER", None))
        self.stack.enter_context(patch.object(menu, "seat_row_state", side_effect=lambda cfg, s, **_kw:
                                              {"word": "working", "reason": "", "since": None}))
        self.seats = [{"name": "acme-api", "repo": "", "path": "", "created": 9000}]
        config.save_session(self.cfg, "acme-api", "opus", ["astra"])
        self.plan("- [x] a\n- [ ] b\n- [ ] c\n- [ ] d\n- [ ] e\n- [ ] f\n- [ ] g\n- [ ] h\n- [ ] i\n"
                  "- [ ] j\n- [ ] k\n- [ ] l\n")
        self.clock = motion.Clock()

    def plan(self, text):
        config.plan_path("acme-api").write_text(text)

    def counts(self, whole=False):
        """The count the clock shows at each of its moments, from what was drawn; `whole`: its
        line and the count."""
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, menu.KEYS, 0, "nobody", {}, look=False, records=[],
                      clock=self.clock)
        line = next(line for line in out.getvalue().split("\033[J")[0].split("\n")
                    if "acme-api" in line)
        text = terminal.ANSI.sub("", line.replace("\033[K", ""))
        row = out.getvalue().split("\033[J")[0].split("\n").index(line) + 1
        first = terminal.cells(text[:re.search(r"[━╸─]", text).start() if whole else
                                    text.rindex(" of ")].rstrip("0123456789")) + 1
        columns = range(first, terminal.cells(text.rstrip()) + 1)
        moving = [self.clock.cells[row, column] for column in columns
                  if (row, column) in self.clock.cells]
        until = max((until for _, until in moving if until), default=None)
        self.written = "".join(terminal.cell_texts(line.replace("\033[K", ""))[first - 1:columns.stop - 1])
        return text[first - 1:].rstrip(), moving, until

    @staticmethod
    def at(moving, now):
        return "".join(animation(now) for animation, _ in moving)

    def test_as_ak_opens_the_count_counts_up_from_nothing_with_its_line(self):
        drawn, moving, until = self.counts()
        self.assertEqual(drawn, "1 of 12")
        self.assertEqual(len(moving), len(drawn))
        began = until - motion.GROW
        self.assertEqual(terminal.plain(self.at(moving, began)), "0 of 12")
        self.assertEqual(self.at(moving, until), self.written)

    def later(self):
        """The draws after this as the clock reads once ak's lines have grown in."""
        now = time.monotonic() + motion.GROW + motion.STAGGER
        return patch.object(motion.time, "monotonic", lambda: now)

    def test_a_count_whose_plan_moves_rolls_there_its_new_digits_coloured_a_moment(self):
        self.counts()
        self.plan("- [x] a\n" * 11 + "- [ ] l\n")
        with self.later():
            drawn, moving, until = self.counts()
        self.assertEqual(drawn, "11 of 12")
        began = until - motion.GLIDE - motion.ROLL
        shown = [terminal.plain(self.at(moving, began + n * motion.FRAME))
                 for n in range(round((until - began) / motion.FRAME) + 1)]
        numbers = [int(text.split(" of ")[0]) for text in shown]
        self.assertEqual(numbers[0], 1)
        self.assertEqual(numbers, sorted(numbers))       # it only counts on, never back
        self.assertGreater(len(set(numbers)), 3, numbers)
        self.assertEqual(self.at(moving, until), self.written)
        flips = [began + n * motion.FRAME for n in range(1, len(numbers))
                 if numbers[n] != numbers[n - 1]]
        line = terminal.faded("working", 0)
        for flip in flips:      # the digit just changed in the line's colour, easing out of it
            lit = [colour for colour in painted(self.at(moving, flip + motion.FRAME / 2)) if colour]
            self.assertTrue(lit and all(near(colour, line) < near(colour, "#ffffff")
                                        for colour in lit), (flip, lit))
        self.assertEqual(painted(self.at(moving, until - motion.FRAME / 2)),
                         painted(self.written))

    def glided(self, plan):
        """The line and its count as drawn, and at each frame as its plan moves to `plan`."""
        self.counts()
        self.plan(plan)
        with self.later():
            drawn, moving, until = self.counts(whole=True)
        began = until - motion.GLIDE - motion.ROLL
        return drawn, [terminal.plain(self.at(moving, began + n * motion.FRAME))
                       for n in range(round(motion.GLIDE / motion.FRAME) + 1)]

    def test_as_its_total_moves_the_line_shows_what_its_count_says(self):
        self.plan("- [x] a\n- [ ] b\n")
        drawn, frames = self.glided("- [x] a\n" + "- [ ] b\n" * 9)
        size = drawn.index(" ")
        self.assertTrue(any(frame.endswith(" 1 of 6") for frame in frames), frames)
        for frame in frames:
            line, done, total = re.fullmatch(r"([━╸─]+) +(\d+) of (\d+)", frame).groups()
            filled, done, total = line.count("━") + line.count("╸") / 2, int(done), int(total)
            # the share of a count its rounding could have said, give or take the line's cell
            self.assertLessEqual(size * (done - 0.5) / (total + 0.5) - 1, filled, frame)
            self.assertLessEqual(filled, size * (done + 0.5) / (total - 0.5) + 1, frame)

    def test_a_count_drawn_narrower_counts_down_from_where_it_was(self):
        self.plan("- [x] a\n" * 11 + "- [ ] l\n")
        drawn, frames = self.glided("- [x] a\n" + "- [ ] b\n" * 11)
        self.assertEqual(frames[-1], drawn)
        for frame in frames:        # over the line's end while it is wider than drawn
            self.assertRegex(frame, r"^[━╸─]+ +\d+ of 12$")
            self.assertEqual(len(frame), len(drawn))
        numbers = [int(frame.split()[-3]) for frame in frames]
        self.assertEqual((numbers[0], numbers[-1]), (11, 1))
        self.assertEqual(numbers, sorted(numbers, reverse=True))

    def test_a_count_that_stands_still_does_not_move(self):
        self.counts()
        with self.later():
            self.assertEqual(self.counts()[1], [])


if __name__ == "__main__":
    unittest.main()
