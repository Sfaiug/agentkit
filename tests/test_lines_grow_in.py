"""As ak opens, every seat's progress line grows from empty to its length, row after row.

The owner's design (14 Oct 2026): 450 ms a line, each row 40 ms after the one above it, the
done part growing over the empty track and ending exactly as drawn, through the draw the read
landing as ak opens makes, each from its own start till news moves it; a draw once they have
grown grows nothing.  Offline: a temporary HOME, fake seats, the motion clock read, no terminal.
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
        # a draw again at once -- the read landing as ak opens -- grows them on from where they
        # were, and one once they have grown grows nothing
        growing = {cell: until for cell, (_, until) in self.clock.cells.items()}
        self.draw()
        self.assertEqual({cell: until for cell, (_, until) in self.clock.cells.items()}, growing)
        with patch.object(motion.time, "monotonic", return_value=max(ends.values()) + 0.01):
            self.draw()
        self.assertEqual({cell for cell, (_, until) in self.clock.cells.items() if until}, set())

    def test_progress_effects_keep_their_cells_after_an_accented_model_name(self):
        name = "cafe\u0301"
        self.cfg["models"][name] = dict(self.cfg["models"]["opus"])
        state = {"word": "needs you", "reason": "", "since": None}
        with patch.object(config, "load", return_value=self.cfg), \
                patch.object(menu, "seat_row_state", return_value=state):
            for seat in self.seats:
                config.save_session(self.cfg, seat["name"], name, ["astra"])
            for width in (100, 50):
                self.clock = motion.Clock()
                for now, done, word in ((10, 1, "needs you"), (11, 3, "needs you"), (12, 4, "done")):
                    with self.subTest(width=width, done=done), \
                            patch.object(motion.time, "monotonic", return_value=now):
                        state["word"] = word
                        for seat in self.seats:
                            config.plan_path(seat["name"]).write_text(
                                "- [x] step\n" * done + "- [ ] step\n" * (4 - done))
                        lines = self.draw(width)
                        moving = {(row, column): terminal.ANSI.sub("", animation(until))
                                  for (row, column), (animation, until) in self.clock.cells.items()
                                  if until is not None and terminal.cells(animation(until)) == 1}
                        self.assertTrue(moving)
                        for (row, column), text in moving.items():
                            expected, at = {}, 1
                            for char in terminal.ANSI.sub("", lines[row - 1]):
                                size = terminal.cells(char)
                                if size:
                                    expected[at], at = char, at + size
                                else:
                                    expected[max(expected)] += char
                            self.assertEqual(text, expected.get(column), (row, column))

    def test_each_line_keeps_its_own_start_till_news_moves_it(self):
        # the read landing as ak opens may give a row above a line its own, or turn the line's
        # seat done: the line keeps the start it had, one drawn only since grows nothing, and one
        # done grows no more once the light that crossed it has
        words = {"acme-api": "idle", "acme-docs": "needs you"}

        def growing(now):     # each seat's line -> until when its cells move
            with patch.object(menu, "seat_row_state", side_effect=lambda cfg, s, **_kw:
                              {"word": words[s["name"]], "reason": "", "since": None}), \
                    patch.object(motion.time, "monotonic", return_value=now):
                lines = [terminal.ANSI.sub("", line) for line in self.draw()]
            rows = {name: next(n for n, line in enumerate(lines, 1) if f" {name} " in line)
                    for name in words}
            return {name: {until for (at, column), (_, until) in self.clock.cells.items()
                           if at == row and column > terminal.cells(
                               lines[row - 1][:lines[row - 1].find("━")])}
                    for name, row in rows.items()}

        growing(10)
        words["acme-api"] = "needs you"
        self.assertEqual(growing(10.02), {"acme-api": set(), "acme-docs": {10 + motion.GROW}})
        words["acme-docs"] = "done"
        growing(10.03)
        self.assertEqual(growing(10.03 + motion.SWEEP + 0.01)["acme-docs"], set())

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
