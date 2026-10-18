"""A task's squares move once when it moves on: its next square fills, and a failure nudges.

The owner's design (14 Oct 2026): on the line the highlighted row opens, each task in flight is
three squares (build, review, land).  One that reaches its next stage fills that square through
its half (`□ ▣ ■`) over 150 ms; one that fails turns red and nudges a cell left, right, left and
back over 240 ms.  A task first seen, or one that did not change, stands still.  Offline: a
temporary HOME, fake seats and runs, the motion clock read, no terminal.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import re
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, motion, terminal  # noqa: E402


def run(name, **state):
    return Path(name), {"run_id": name, "launched_session": "acme-api", "started_at": 9000,
                        "task_file": f"/t/{name}.md", **state}


class TasksMove(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=24))
        self.stack.enter_context(patch.object(terminal, "_POINTER", None))
        self.stack.enter_context(patch.object(menu, "seat_row_state", side_effect=lambda cfg, s, **_kw:
                                              {"word": "working", "reason": "", "since": None}))
        self.seats = [{"name": "acme-api", "repo": "", "path": "", "created": 9000}]
        config.save_session(self.cfg, "acme-api", "opus", ["astra"])
        self.clock = motion.Clock()
        self.clock.grows = {}

    def draw(self, records, width=100):
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=30), \
                patch.object(menu.time, "time", return_value=9600), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, menu.KEYS, 0, "acme-api", {}, look=False,
                      records=records, clock=self.clock)
        lines = out.getvalue().split("\033[J")[0].replace("\033[K", "").split("\n")
        return [terminal.ANSI.sub("", line) for line in lines]

    def groups(self, lines):
        """(row, first column) of each task's squares on the line the row opens."""
        row = next(n for n, line in enumerate(lines, 1) if "astra ⚒" in line)
        return [(row, terminal.cells(lines[row - 1][:group.start()]) + 1)
                for group in re.finditer("[■□]{3}", lines[row - 1])]

    def test_squares_in_a_draft_are_never_a_task(self):
        state = {"word": "working", "reason": "", "unsent": "unsent: explain ■□□ please",
                 "since": None}
        for width in (100, 40):    # the draft beside the row, or on a line of its own
            with self.subTest(width=width), \
                    patch.object(menu, "seat_row_state", return_value=state):
                self.clock = motion.Clock()
                self.clock.grows = {}
                self.draw([run("g1", state="running", step="executor")], width)
                moved = set(self.clock.cells)
                lines = self.draw([run("g1", state="running", step="reviewer")], width)
                (row, _), = self.groups(lines)
                self.assertTrue(any("explain ■□□" in line for line in lines), lines)
                new = {cell for cell in self.clock.cells if cell not in moved}
                self.assertTrue(new and {r for r, _ in new} == {row}, (new, lines))

    def test_the_next_square_fills_through_its_half_and_a_failure_nudges(self):
        before = [run("g1", state="running", step="executor"),
                  run("g2", state="running", step="reviewer")]
        self.groups(self.draw(before))
        moved = {(row, column) for row, column in self.clock.cells}
        after = [run("g1", state="running", step="reviewer"),
                 run("g2", state="fail", step="reviewer", finished_at=9500)]
        with patch.object(motion, "STEP", 60):     # long enough to read its half by the clock
            lines = self.draw(after)
            now = time.monotonic()
        (row, first), (_, second) = self.groups(lines)    # both at stage 1 now, g1 first
        new = {cell: self.clock.cells[cell] for cell in self.clock.cells if cell not in moved}
        # g1's second square fills: half first, then as drawn, breathing on as it moves
        animation, _ = new[row, first + 1]
        self.assertEqual(terminal.plain(animation(now)), "▣")
        self.assertEqual(terminal.plain(animation(now + 60)), "■")
        # g2 nudges, drawn from the cell before its squares: left, right, left and back
        animation, until = new[row, second - 1]
        began = until - motion.SHAKE
        shifts = [terminal.ANSI.sub("", animation(began + motion.SHAKE * k / 4 + 0.001))
                  for k in range(4)]
        self.assertEqual([len(text) - len(text.lstrip()) for text in shifts], [0, 2, 0, 1])
        self.assertEqual({text.strip() for text in shifts}, {"■■□"})

    def test_a_task_first_seen_or_unchanged_stands_still(self):
        records = [run("g1", state="running", step="executor")]
        self.draw(records)
        cells = set(self.clock.cells)
        self.draw(records)
        self.assertEqual(set(self.clock.cells), cells)       # the breathing square alone


if __name__ == "__main__":
    unittest.main()
