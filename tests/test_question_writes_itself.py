"""A question shown the first time writes itself out under its row, a cell at a time, in a
third of a second; shown again, or as the screen opens, it comes up as any line does.

The owner's pick of 18 Oct 2026, "a question that writes itself, once".  Offline: a temporary
HOME, fake seats, the motion clock read at the times it is handed, no terminal.
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

QUESTION = "Ship the launch post on Tuesday, or hold it until the pricing page is live?"


def state(cfg, seat, **_kw):
    return ({"word": "needs you", "reason": QUESTION, "since": None} if seat["name"] == "acme-api"
            else {"word": "idle", "reason": "", "since": None})


class Writes(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=24))
        self.stack.enter_context(patch.object(terminal, "_POINTER", None))
        self.stack.enter_context(patch.object(menu, "seat_row_state", side_effect=state))
        self.seats = [{"name": name, "repo": "", "path": "", "created": 9000}
                      for name in ("acme-api", "acme-docs")]
        for name in ("acme-api", "acme-docs"):
            config.save_session(self.cfg, name, "opus", ["astra"])
        self.clock = motion.Clock()

    def draw(self, cursor, width=60):
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, menu.KEYS, 0, cursor, {}, look=False, records=[],
                      clock=self.clock)
        lines = [line.replace("\033[K", "") for line in
                 out.getvalue().split("\033[J")[0].split("\n")]
        rows = [n for n, line in enumerate(lines, 1)
                if any(word in terminal.ANSI.sub("", line) for word in ("Ship", "pricing"))]
        return lines, rows

    def shown(self, lines, rows, now):
        """The question's text as the clock writes it at `now`, over what was drawn."""
        out = []
        for row in rows:
            cells = terminal.cell_texts(lines[row - 1])
            moving = sorted(((column, animation(now)) for (at, column), (animation, _)
                             in self.clock.cells.items() if at == row),
                            key=lambda one: terminal.cells(one[1]) < 2)     # a whole line first
            for column, text in moving:
                for n, cell in enumerate(terminal.cell_texts(text)):
                    cells[column - 1 + n:column + n] = [cell]
            out.append(terminal.ANSI.sub("", "".join(cells)).strip())
        return " ".join(line for line in out if line)

    def test_the_first_time_the_highlight_comes_to_it_the_question_writes_itself_out(self):
        self.draw("acme-docs")
        lines, rows = self.draw("acme-api")
        self.assertGreater(len(rows), 1, lines)      # wrapped onto more than one line
        cells = [cell for cell in self.clock.cells if cell[0] in rows]
        began = min(until for cell, (_, until) in self.clock.cells.items()
                    if cell in cells) - motion.WRITE
        self.assertEqual(self.shown(lines, rows, began), "")
        half = self.shown(lines, rows, began + motion.WRITE / 2)
        self.assertTrue(QUESTION.startswith(half) and 0 < len(half) < len(QUESTION), half)
        self.assertEqual(self.shown(lines, rows, began + motion.WRITE), QUESTION)
        # away and back once it has: it comes up as any line does, written out already
        with patch.object(motion.time, "monotonic", return_value=began + motion.WRITE):
            self.draw("acme-docs")
            lines, rows = self.draw("acme-api")
        self.assertEqual(self.shown(lines, rows, began + motion.WRITE), QUESTION)

    def test_a_question_the_screen_opens_on_is_drawn_as_it_is(self):
        lines, rows = self.draw("acme-api")
        self.assertTrue(rows)
        self.assertEqual(self.shown(lines, rows, 0), QUESTION)
        self.draw("acme-docs")
        lines, rows = self.draw("acme-api")
        self.assertEqual(self.shown(lines, rows, 0), QUESTION)


if __name__ == "__main__":
    unittest.main()
