"""A number on `c` whose step was refused nudges where its value is drawn, and lands back on it.

A row of config.POLICY draws its value beside its name or, on a narrow terminal, under it
(menu.number_rows).  What a frame writes stays until the next full draw, so a nudge anywhere but
on the value leaves a second one there.  Offline, in a temporary HOME: menu.config_body at each
layout with its frames written over the lines it drew, on the test's own clock.
"""

from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config, menu, motion, terminal

CELL = re.compile(r"\x1b\[(\d+);(\d+)H((?:(?!\x1b\[\d+;\d+H).)*)", re.S)
START = 100


class Nudge(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix="ak-number-nudge-")
        self.addCleanup(home.cleanup)
        self.now = START
        self.enterContext(patch.object(config, "HOME", Path(home.name)))
        self.enterContext(patch.object(terminal, "colour_depth", return_value=24))
        self.enterContext(patch.object(motion.time, "monotonic", side_effect=lambda: self.now))

    def screens(self, cfg, name):
        """`c` with `name` pointed at and its step just refused: its lines as drawn, and as each
        frame of the nudge leaves them, one for each cell it shifts to and one for its landing."""
        moves = []
        body, _ = menu.config_body(cfg, at=("row", name), moves=moves)
        drawn = [terminal.plain(line, spaced=True).rstrip() for line in body]
        clock = motion.Clock()
        clock.look({key: value for _, key, value, _ in moves})
        clock.touch(("number", name))
        frames = [clock.drawn(moves, lambda line: line + 1)[0]]
        for part in (3 / 8, 5 / 8, 1):
            self.now = START + motion.SHAKE * part
            frames.append(clock.frame())
        shown, screens = drawn.copy(), []
        for frame in frames:
            for row, column, text in CELL.findall(frame):
                at, first, text = int(row) - 1, int(column) - 1, terminal.plain(text, spaced=True)
                line = shown[at].ljust(first + len(text))
                shown[at] = (line[:first] + text + line[first + len(text):]).rstrip()
            screens.append(shown.copy())
        return drawn, screens

    def test_it_moves_the_value_alone_in_every_layout_and_leaves_the_draw(self):
        # the terminal's width, the settings, and where a value starts: lines under its name,
        # and the column counted from 1
        for width, settings, down, column in ((100, {}, 0, 17),     # all beside its name
                                              (40, {}, 0, 17),      # its boards fold under it
                                              (40, {"rounds": 10000}, 1, 5)):    # so does it
            for name in config.POLICY:
                self.now = START
                with self.subTest(width=width, settings=settings, name=name), \
                        patch.object(terminal, "width", return_value=width):
                    cfg = {**config.load(), **settings}
                    value = str(config.policy(cfg)[name])
                    drawn, screens = self.screens(cfg, name)
                    at = down + next(number for number, line in enumerate(drawn)
                                     if line[2:].split(" ")[0] == name)
                    line = drawn[at]
                    start, end = column - 1, column - 1 + len(value)
                    self.assertEqual(line[start:end], value)
                    self.assertEqual(screens, [
                        [*drawn[:at], (line[:start - 1] + moved + line[end + 1:]).rstrip(),
                         *drawn[at + 1:]]
                        for moved in (f"{value}  ", f"  {value}", f"{value}  ", f" {value} ")])
                    self.assertEqual(screens[-1], drawn)


if __name__ == "__main__":
    unittest.main()
