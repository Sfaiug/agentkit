"""A working seat with no plan draws a plan's line with nothing done and `no plan yet`.

The line is a plan's own, as wide as one, all a dim `─`; on the menu a soft light goes round it,
its place the clock's alone, and a frame rewrites nothing but that line and the breathing `●`.
A seat's own tmux bar draws it still.  Every other word, and a seat with a plan, draws as before.
Offline, in a throwaway HOME, on a true-colour terminal that is a stand-in.
"""

from contextlib import redirect_stdout
import io
import math
import os
import re
import time
from unittest.mock import patch
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config, menu, motion, orch, statusbar, terminal

WORDS = {"fix-api": "working", "add-tab": "working", "web-app": "needs you"}
PLANS = {"add-tab": (3, 8)}
WRITE = re.compile(r"\x1b\[(\d+);(\d+)H")


class NoPlanBar(Sandbox):
    def setUp(self):
        super().setUp()
        os.environ.pop("NO_COLOR")
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "xterm-256color",
            "COLORTERM": "truecolor"}))
        repo = config.CODE / "acme"
        (repo / ".git").mkdir(parents=True)

        def row_state(cfg, session, look=True, **facts):
            return {"word": WORDS[session["name"]], "reason": "", "since": None}

        for target, name, fake in (
                (orch, "listing", lambda: [{"name": name, "repo": str(repo), "path": str(repo),
                                            "created": 0} for name in WORDS]),
                (menu, "run_records", lambda **_kw: []),
                (menu, "seat_row_state", row_state),
                (menu, "seat_progress", lambda name: PLANS.get(name, (0, 0))),
                (orch, "job_notices", lambda: []),
                (terminal, "width", lambda *args: 100),
                (terminal, "height", lambda *args: 30)):
            self.stack.enter_context(patch.object(target, name, fake))

    def draw(self):
        """The menu as it has the keyboard, plain line by line, and its clock."""
        clock = motion.Clock()
        with redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, orch.listing(), drawn={}, clock=clock)
        screen = out.getvalue().partition("\033[H")[2].rpartition("\033[J")[0]
        return [terminal.plain(line.replace("\033[K", "")) for line in screen.split("\n")], clock

    def test_a_its_row_ends_in_a_dim_line_and_no_plan_yet_as_wide_as_a_plans(self):
        lines, _ = self.draw()
        row = next(line for line in lines if " fix-api " in line).rstrip()
        planned = next(line for line in lines if " add-tab " in line).rstrip()
        self.assertRegex(row, r"● working  ─+ no plan yet$")
        self.assertRegex(planned, r"● working  ━+╸?─+ 3 of 8$")
        self.assertEqual(terminal.cells(row), terminal.cells(planned))
        # the line itself, cell for cell, as a plan's would be with nothing done
        self.assertEqual(terminal.plain(menu.last_column("working", 0, 0, 30)), "─" * 18 + " no plan yet")
        self.assertEqual(terminal.cells(menu.last_column("working", 0, 0, 30)),
                         terminal.cells(menu.last_column("working", 3, 8, 30)))
        with patch.dict(os.environ, {"LANG": "C", "LC_ALL": "", "COLORTERM": "", "TERM": "dumb"}):
            self.assertEqual(terminal.plain(menu.last_column("working", 0, 0, 30)), "-" * 18 + " no plan yet")
        # a room too narrow for both: the words alone
        self.assertEqual(terminal.plain(menu.last_column("working", 0, 0, 11, narrow=True)),
                         "no plan yet")

    def test_b_a_light_goes_round_it_on_the_menu_and_the_seats_bar_stays_still(self):
        lines, clock = self.draw()
        number = next(n for n, line in enumerate(lines, 1) if " fix-api " in line)
        line = lines[number - 1]
        first = line.index("─") + 1
        span = range(first, line.index(" no plan yet") + 1)
        dot = (number, line.index("●") + 1)
        base = math.ceil((time.monotonic() + 60) / motion.ROUND) * motion.ROUND

        def frame(at):
            with patch.object(motion.time, "monotonic", return_value=at):
                return clock.frame()

        def lit(at):
            """The cells of fix-api's line lit at `at`, and every cell any other row shows."""
            shown = {cell: terminal.plain(animation(at))
                     for cell, (animation, _) in clock.cells.items()}
            return ({column for (row, column), text in shown.items()
                     if row == number and text == "━"},
                    {cell: text for cell, text in shown.items() if cell[0] != number})

        early, others = lit(base + 0.4)
        later, still = lit(base + 1.2)
        self.assertEqual(len(early), 3)
        self.assertEqual(len(later), 3)
        self.assertLess(max(early), min(later))         # left to right
        self.assertTrue(early | later <= set(span))
        self.assertEqual(others, still)                 # the planned row draws as drawn
        planned = next(n for n, line in enumerate(lines, 1) if " add-tab " in line)
        self.assertEqual("".join(text for (row, _), text in sorted(others.items())
                                 if row == planned and text in "━╸─"),
                         re.search(r"[━╸─]+(?= 3 of 8)", lines[planned - 1]).group())
        # a frame after another rewrites that line's cells and the breathing dot, nothing else
        frame(base + 0.4)
        written = {(int(row), int(column)) for row, column in WRITE.findall(frame(base + 1.2))}
        self.assertTrue(written)
        self.assertTrue(all(cell == dot or cell[0] == number and cell[1] in span
                            for cell in written if cell[0] == number), written)
        self.assertTrue(all(row != number or (row, column) == dot or column in span
                            for row, column in written))
        self.assertTrue({cell for cell in written if cell[0] == number} - {dot})
        # the seat's own bar, at the same two readings, draws the line still
        bars = []
        for at in (base + 0.4, base + 1.2):
            with patch.object(motion.time, "monotonic", return_value=at), \
                    patch.object(orch, "on_own_server", return_value=True), \
                    patch.object(statusbar, "_write",
                                 lambda name, model, word, lasts, *_a, **_kw: bars.append(lasts)):
                statusbar.redress({"name": "fix-api"}, {"word": "working", "reason": ""},
                                  self.cfg)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0], bars[1])
        for cells, last in zip(statusbar.BARS, bars[0]):
            shown = re.sub(r"#\[[^\]]*\]", "", last)
            self.assertEqual(shown, "─" * (cells - 12) + " no plan yet")

    def test_c_every_other_word_and_a_plan_draw_as_before(self):
        for word in ("idle", "done", "needs you", None):
            with self.subTest(word=word):
                self.assertEqual(menu.last_column(word, 0, 0, 30), "")
                self.assertEqual(menu.last_column(word, 0, 0, 24, narrow=True, tmux=True), "")
        self.assertEqual(terminal.plain(menu.last_column("working", 3, 8, 30)),
                         "━" * 8 + "╸" + "─" * 14 + " 3 of 8")
        lines, _ = self.draw()
        asking = next(line for line in lines if " web-app " in line).rstrip()
        self.assertTrue(asking.endswith("! needs you"), asking)


if __name__ == "__main__":
    unittest.main(verbosity=2)
