"""While a model works, the tip of its seat's line and its moving tasks' squares breathe.

The owner's design (14 Oct 2026): motion means a model is working right now.  The `●` of a
working seat breathes, and in the same phase so does the tip of its row's progress line and,
on the line the highlighted row opens, the square of the stage each moving task is at; a task
that waits, and a seat that needs you or is done, stand still.  Offline: a temporary HOME,
fake seats and runs, the motion clock read, no terminal.
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

WORDS = {"acme-api": "working", "acme-docs": "needs you"}


def run(name, seat, **state):
    return Path(name), {"run_id": name, "launched_session": seat, "started_at": 9000,
                        "task_file": f"/t/{name}.md", **state}


class Breathes(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=24))
        self.stack.enter_context(patch.object(terminal, "_POINTER", None))
        self.stack.enter_context(patch.object(menu, "seat_row_state", side_effect=lambda cfg, s, **_kw:
                                              {"word": WORDS[s["name"]], "reason": "", "since": None}))
        self.seats = [{"name": name, "repo": "", "path": "", "created": 9000} for name in WORDS]
        for name in WORDS:
            config.save_session(self.cfg, name, "opus", ["astra"])
            config.plan_path(name).write_text("- [x] a\n- [x] b\n- [ ] c\n- [ ] d\n")
        self.records = [run("g1", "acme-api", state="running", step="reviewer"),
                        run("g2", "acme-api", state="queued"),
                        run("g3", "acme-docs", state="running", step="executor")]

    def drawn(self, cursor, width=100):
        clock = motion.Clock()
        clock.began = 0             # opened long ago: no line grows in
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, menu.KEYS, 0, cursor, {}, look=False,
                      records=self.records, clock=clock)
        lines = terminal.ANSI.sub("", out.getvalue().split("\033[J")[0]).split("\n")
        return [line.replace("\033[K", "") for line in lines], clock

    def cell(self, lines, row_of, char, last=True):
        row = next(n for n, line in enumerate(lines, 1) if row_of(line))
        line = lines[row - 1]
        return row, terminal.cells(line[:line.rfind(char) if last else line.find(char)]) + 1

    def test_the_tip_and_the_moving_square_breathe_and_nothing_else_of_theirs(self):
        lines, clock = self.drawn("acme-api")
        tip = self.cell(lines, lambda line: " acme-api " in line, "━")
        self.assertIn(tip, clock.cells)
        # the line acme-api opens: the queued task's lone square still, then the reviewing
        # task's second square breathing, its first filled and still
        under = tip[0] + 1
        self.assertRegex(lines[under - 1], r"   ■□□  ■■□$")
        square = self.cell(lines, lambda line: line == lines[under - 1], "■■□")
        self.assertIn((under, square[1] + 1), clock.cells)
        self.assertNotIn((under, square[1]), clock.cells)
        queued = self.cell(lines, lambda line: line == lines[under - 1], "■□□")
        self.assertNotIn(queued, clock.cells)
        # a seat that needs you holds its line still
        still = self.cell(lines, lambda line: " acme-docs " in line, "━")
        self.assertNotIn(still, clock.cells)

    def test_a_tip_on_the_line_under_a_narrow_row_breathes(self):
        for width, tip in ((59, "━"), (40, "╸")):
            lines, clock = self.drawn("acme-api", width)
            row = self.cell(lines, lambda line: " acme-api " in line, "●")[0] + 1
            line = lines[row - 1]
            self.assertRegex(line, f"^ +━*{tip}─+ 2 of 4$")
            self.assertIn((row, terminal.cells(line[:line.rfind(tip)]) + 1), clock.cells)

    def test_draft_glyphs_stay_still_while_the_real_task_square_breathes(self):
        self.seats = self.seats[:1]
        self.records = self.records[:1]
        for width in (100, 59, 40):
            for draft in ("unsent: explain ━ please", "unsent: explain ■□□ please",
                          "unsent: " + "example " * 8 + "╸ ■□□ ■■□ ■■■"):
                with self.subTest(width=width, draft=draft), patch.object(
                        menu, "seat_row_state", return_value={"word": "working", "reason": "",
                                                             "unsent": draft, "since": None}):
                    lines, clock = self.drawn("acme-api", width)
                    dot = self.cell(lines, lambda line: " acme-api " in line, "●")
                    square = self.cell(lines, lambda line: line.rstrip().endswith("■■□"), "■■□")
                    self.assertEqual(set(clock.cells), {dot, (square[0], square[1] + 1)})

    def test_only_the_last_bar_cell_breathes_in_each_palette(self):
        for depth, light in ((24, False), (24, True), (256, False), (256, True)):
            for width in (100, 59, 40):
                with self.subTest(depth=depth, light=light, width=width), \
                        patch.object(terminal, "colour_depth", return_value=depth), \
                        patch.object(terminal, "_LIGHT", light):
                    lines, clock = self.drawn("acme-docs", width)
                    dot = self.cell(lines, lambda line: " acme-api " in line, "●")
                    row = dot[0] + (width < 60)
                    line = lines[row - 1]
                    tip = max(line.rfind("━"), line.rfind("╸"))
                    self.assertEqual(set(clock.cells),
                                     {dot, (row, terminal.cells(line[:tip]) + 1)})

    def test_each_breathes_in_the_dots_phase(self):
        lines, clock = self.drawn("acme-api")
        dot = self.cell(lines, lambda line: " acme-api " in line, "●", last=False)
        tip = self.cell(lines, lambda line: " acme-api " in line, "━")
        for now in (0.0, 0.5, 1.0):
            dim = motion.breath(now)
            self.assertEqual(terminal.plain(clock.cells[tip][0](now)), "━")
            self.assertIn(terminal.faded("working", motion.DIMMER * dim)[1:].lower(),
                          "".join(f"{int(part):02x}" for part in clock.cells[tip][0](now)
                                  .split("38;2;")[1].split("m")[0].split(";")))
            self.assertIn(dot, clock.cells)


if __name__ == "__main__":
    unittest.main()
