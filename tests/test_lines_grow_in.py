"""As ak opens, every seat's progress line grows from empty to its length, row after row.

The owner's design (14 Oct 2026): 450 ms a line, each row 40 ms after the one above it, the
done part growing over the empty track and ending exactly as drawn; a draw after the first
grows nothing.  Offline: a temporary HOME, fake seats, the motion clock read, no terminal.
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
from test_news_motion import CELL, painted  # noqa: E402
from agentkit import config, menu, motion, terminal  # noqa: E402


class GrowIn(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=24))
        self.stack.enter_context(patch.object(terminal, "_POINTER", None))
        self.stack.enter_context(patch.object(menu, "seat_row_state", side_effect=lambda cfg, s, **_kw:
                                              {"word": "needs you", "reason": "", "since": None}))
        self.seats = [{"name": name, "repo": "", "path": "", "created": 9000}
                      for name in ("acme-api", "acme-docs")]
        for name, plan in (("acme-api", "- [x] a\n- [x] b\n- [ ] c\n- [ ] d\n"),
                           ("acme-docs", "- [x] a\n- [ ] b\n")):
            config.save_session(self.cfg, name, "opus", ["astra"])
            config.plan_path(name).write_text(plan)
        self.clock = motion.Clock()

    def draw(self, width=100):
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, menu.KEYS, 0, "acme-api", {}, look=False,
                      records=[], clock=self.clock)
        self.written = out.getvalue()
        return [line.replace("\033[K", "") for line in
                out.getvalue().split("\033[J")[0].split("\n")]

    def test_each_line_grows_from_empty_to_exactly_as_drawn_row_after_row(self):
        lines = self.draw()
        ends = {}
        for name in ("acme-api", "acme-docs"):
            row = next(n for n, line in enumerate(lines, 1) if f" {name} " in line)
            text = terminal.ANSI.sub("", lines[row - 1])
            first = terminal.cells(text[:text.index("━")]) + 1
            cells = sorted(column for at, column in self.clock.cells if at == row)
            self.assertEqual(cells[0], first)
            drawn = terminal.cell_texts(lines[row - 1])
            animation, until = self.clock.cells[row, first]
            began = until - motion.GROW
            # empty track at first, its own cells in the end
            self.assertEqual(terminal.plain(animation(began)), "─")
            for column in cells:
                self.assertEqual(self.clock.cells[row, column][0](until),
                                 drawn[column - 1], (name, column))
            ends[name] = until
        self.assertAlmostEqual(ends["acme-docs"] - ends["acme-api"], motion.STAGGER, places=3)
        # and the next draw grows nothing
        self.draw()
        self.assertEqual(self.clock.cells, {})

    def test_on_a_popup_each_line_grows_as_it_fades_in_and_never_shrinks(self):
        # Ctrl-b m's clock fades its first draw in from the background: the lines grow under
        # the fade, never shown at their length first
        lines = {n: terminal.ANSI.sub("", line) for n, line in enumerate(self.draw(), 1)}
        rows = [n for n, line in lines.items() if "━" in line and "acme" in line]
        self.clock, screen, filled = motion.Clock(fade=True), {}, []
        with patch.object(terminal, "_LIGHT", False):
            for n, now in enumerate((10, 10.05, 10.1, 10.15, 10.3, 10.5, 10.7)):
                with patch.object(motion.time, "monotonic", return_value=now):
                    written = self.clock.frame() if n else (self.draw(), self.written)[1]
                for row, column, text in CELL.findall(written):
                    for k, cell in enumerate(painted(text)):
                        screen[int(row), int(column) + k] = cell
                filled.append(sum(char in "━╸" and colour != (0, 0, 0)
                                  for (row, _), (char, colour) in screen.items() if row in rows))
        self.assertEqual(filled, sorted(filled))
        self.assertEqual((len(rows), filled[0]), (2, 0))
        self.assertEqual(filled[-1], sum(lines[n].count("━") + lines[n].count("╸") for n in rows))

    def test_line_glyphs_in_what_got_done_never_grow(self):
        done = {"word": "done", "reason": "Deployed - 1 of 2 services; ━╸─= 3 of 4", "since": None}
        for width in (100, 50):    # the line beside the row, or on the line under it
            with self.subTest(width=width), \
                    patch.object(menu, "seat_row_state", return_value=done):
                self.clock = motion.Clock()
                lines = [terminal.ANSI.sub("", line) for line in self.draw(width)]
                prose = {n for n, line in enumerate(lines, 1) if "Deployed" in line}
                grown = {row for row, _ in self.clock.cells}
                self.assertTrue(prose and grown and not grown & prose, (grown, lines))


if __name__ == "__main__":
    unittest.main()
