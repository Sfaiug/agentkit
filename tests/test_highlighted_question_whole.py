"""The highlighted seat's question is whole under its row, on whichever harness it runs.

A seat's row and its bar show a question from its start and cut the rest, and the seat's own
screen shows only what its harness and its model put there.  So the one place every seat's
question can be read whole is ak's own screen: the highlighted seat's sentence wraps onto as
many lines as it takes, there and in the popup over a seat.  Every other row keeps its two
lines.  Offline: the real renderer on invented rows.
"""

from contextlib import redirect_stdout
import io
import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import menu, terminal

QUESTION = ("Which schema should acme use? " + " ".join(
    f"Reason {n}: the parser reads both, and v2 drops the legacy fields the importer needs."
    for n in range(1, 9)) + " Recommend v2.")


def seat(number, name, word="needs you", sentence=QUESTION, **extra):
    return {"number": str(number), "name": name, "count": word, "orchestrator": "opus",
            "worker": "opus", "sentence": sentence, "bar": None, "running": 0, "word": word,
            "runs": (), **extra}


def said(block):
    """A seat's block as one sentence: its lines after the row's own columns, joined."""
    lines = [terminal.plain(line) for line in block]
    head, _, first = lines[0].partition("needs you")
    return " ".join(" ".join([first] + lines[1:]).split())


class HighlightedQuestionWhole(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                                                         "NO_COLOR": "1"}))

    def test_the_highlighted_seats_question_takes_the_lines_it_needs(self):
        for width in (100, 60, 40):
            with self.subTest(width=width):
                asks, other = menu.v5o_seat_blocks(
                    [seat(1, "fix-api"), seat(2, "acme-web")], width, whole="fix-api")
                self.assertEqual(said(asks), QUESTION)
                self.assertGreater(len(asks), 2)
                self.assertFalse(any("…" in line for line in asks))
                self.assertTrue(all(terminal.cells(terminal.plain(line)) <= width
                                    for line in asks))
                # every other row keeps its two lines, cut where it always was
                self.assertEqual(len(other), 2)
                self.assertTrue(terminal.plain(other[-1]).endswith("…"))

    def test_a_question_that_fits_its_row_and_a_tasks_bar_are_as_they_were(self):
        short = seat(1, "fix-api", sentence="Merge PR #7 by bob? yes/no")
        working = seat(2, "acme-web", word="working", sentence="", bar=(1, 3))
        rows = [short, working]
        self.assertEqual(menu.v5o_seat_blocks(rows, 100, whole="fix-api"),
                         menu.v5o_seat_blocks(rows, 100))
        self.assertEqual(menu.v5o_seat_blocks(rows, 100, whole="acme-web"),
                         menu.v5o_seat_blocks(rows, 100))

    def drawn(self, cursor, keyboard=True, width=100):
        rows = [seat(1, "fix-api"), seat(2, "acme-web")]
        groups = ([{"name": "acme", "checkout": None, "seats": rows}], rows, 2, 0)
        out = io.StringIO()
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=60), redirect_stdout(out):
            menu.draw(self.cfg, [], cursor=cursor, drawn={} if keyboard else None,
                      groups=groups, look=False)
        return " ".join(terminal.plain(terminal.ANSI.sub("", out.getvalue())).split())

    def test_the_menu_unfolds_it_under_the_highlight_and_folds_it_as_the_highlight_moves(self):
        for width in (100, 44):
            with self.subTest(width=width):
                for cursor in ("fix-api", "acme-web"):
                    screen = self.drawn(cursor, width=width)
                    # whole once, under the highlighted seat; the other one cut
                    self.assertEqual(screen.count(QUESTION), 1)
                    self.assertEqual(screen.count("…"), 1)

    def test_a_screen_with_no_highlight_cuts_every_row_as_before(self):
        screen = self.drawn("fix-api", keyboard=False)
        self.assertNotIn(QUESTION, screen)
        self.assertEqual(screen.count("…"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
