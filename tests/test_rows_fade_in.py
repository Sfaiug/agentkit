"""What the highlight opens, and the page it turns to, come up out of the background.

The owner's design (14 Oct 2026): pointing at a row, or moving to it with ↑/↓, opens the line
under it, which fades in over 120 ms; turning a page fades its rows in over 150 ms.  Nothing
else moves for it, and the first draw draws them as they are.  Offline: a temporary HOME, fake
seats, the motion clock read, no terminal.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, motion, terminal  # noqa: E402

NAMES = [f"acme-{n:02}" for n in range(1, 13)]


class FadeIn(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=24))
        self.stack.enter_context(patch.object(terminal, "_POINTER", None))
        self.stack.enter_context(patch.object(menu, "seat_row_state", side_effect=lambda cfg, s, **_kw:
                                              {"word": "working", "reason": "", "since": None}))
        self.seats = [{"name": name, "repo": "", "path": "", "created": 9000} for name in NAMES]
        for name in NAMES:
            config.save_session(self.cfg, name, "opus", ["astra"])
        self.clock = motion.Clock()

    def draw(self, cursor, page=0, height=40):
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=height), \
                redirect_stdout(io.StringIO()) as out:
            drawn = {}
            menu.draw(self.cfg, self.seats, menu.KEYS, page, cursor, drawn, look=False,
                      records=[], clock=self.clock)
        lines = out.getvalue().split("\033[J")[0].replace("\033[K", "").split("\n")
        return [terminal.ANSI.sub("", line) for line in lines], drawn

    def test_the_line_under_a_row_the_highlight_comes_to_fades_in(self):
        self.draw("acme-01")
        self.assertFalse([cell for cell in self.clock.cells if cell[1] == 1])   # drawn as it is
        lines, _ = self.draw("acme-02")
        row = next(n for n, line in enumerate(lines, 1) if " acme-02 " in line) + 1
        self.assertIn("astra builds", lines[row - 1])
        # the line it opens, and no other, comes up out of the background
        self.assertEqual([cell for cell in self.clock.cells if cell[1] == 1], [(row, 1)])
        animation, until = self.clock.cells[row, 1]
        began = until - motion.OPEN
        first, last = animation(began), animation(until)
        self.assertNotEqual(first, last)
        self.assertEqual(terminal.plain(first), terminal.plain(last))
        self.assertEqual(terminal.ANSI.sub("", last).rstrip(), lines[row - 1].rstrip())

    def test_the_rows_of_a_page_turned_to_fade_in(self):
        _, drawn = self.draw("acme-01", height=14)
        self.assertGreater(len(drawn["turns"]), 1)
        lines, _ = self.draw(drawn["turns"][1], page=1, height=14)
        rows = sorted(row for row, column in self.clock.cells if column == 1)
        self.assertTrue(rows, lines)
        faded = []
        for row in rows:
            animation, until = self.clock.cells[row, 1]
            # it ends as drawn, and began TURN seconds before, faded into the background
            self.assertEqual(terminal.plain(animation(until)), terminal.plain(lines[row - 1]))
            faded.append(animation(until - motion.TURN) != animation(until))
        self.assertTrue(any(faded))
        self.assertTrue(any("acme" in lines[row - 1] for row in rows))

    def test_a_highlight_move_during_a_page_fade_gets_its_full_reveal(self):
        with patch.object(motion.time, "monotonic", return_value=10.0) as now:
            _, drawn = self.draw("acme-01", height=14)
            cursor = drawn["turns"][1]
            now.return_value = 11.0
            _, drawn = self.draw(cursor, page=1, height=14)
            # A page turn still brings up all its rows together, including the detail.
            for (_, column), (_, until) in self.clock.cells.items():
                if column == 1:
                    self.assertAlmostEqual(until, 11.15)
            cursor = drawn["order"][drawn["order"].index(cursor) + 1]
            now.return_value = 11.1
            lines, _ = self.draw(cursor, page=1, height=14)
            row = next(n for n, line in enumerate(lines, 1) if "astra builds" in line)
            animation, until = self.clock.cells[row, 1]
            self.assertAlmostEqual(until, 11.22)
            self.assertEqual(animation(11.1), terminal.fade(animation(until), 1))
            for (other, column), (_, end) in self.clock.cells.items():
                if column == 1 and other != row:
                    self.assertAlmostEqual(end, 11.15)
            now.return_value = 11.15
            self.clock.frame()
            self.assertEqual([cell for cell in self.clock.cells if cell[1] == 1], [(row, 1)])
            now.return_value = 11.22
            self.clock.frame()
            self.assertNotIn((row, 1), self.clock.cells)

    def test_news_during_a_page_fade_gets_its_full_glow(self):
        for word in ("needs you", "done"):
            with self.subTest(word=word), \
                    patch.object(motion.time, "monotonic", return_value=10.0) as now:
                self.clock = motion.Clock()
                _, drawn = self.draw("acme-01", height=14)
                cursor = drawn["turns"][1]
                now.return_value = 11.0
                self.draw(cursor, page=1, height=14)
                now.return_value = 11.1
                with patch.object(menu, "seat_row_state", return_value={
                        "word": word, "reason": "Status changed.", "since": None}):
                    lines, _ = self.draw(cursor, page=1, height=14)
                self.assertEqual(self.clock.seen[("page",)][1], 11.0)
                row = next(n for n, line in enumerate(lines, 1) if f" {cursor} " in line)
                animation, until = self.clock.cells[row, 1]
                self.assertAlmostEqual(until, 12.1)
                self.assertIn("48;2;", animation(11.1))
                now.return_value = 11.15
                self.clock.frame()
                self.assertIn((row, 1), self.clock.cells)
                now.return_value = 12.1
                self.clock.frame()
                self.assertNotIn((row, 1), self.clock.cells)


if __name__ == "__main__":
    unittest.main()
