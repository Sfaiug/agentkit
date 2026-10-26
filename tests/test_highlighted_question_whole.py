"""A seat's question is whole under its row, on whichever harness it runs.

A seat's bar shows a question from its start and cuts the rest, and the seat's own screen shows
only what its harness and its model put there.  So the one place every seat's question can be
read whole is ak's own screen: its sentence wraps onto as many lines as it takes, there and in
the popup over a seat, and only a block taller than its page is cut to it, ending in `…`.  The
highlight changes no block, so no row moves and no page turns as it moves.  Offline: the real
renderer on invented rows.
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


ROWS = [seat(1, "fix-api"), seat(2, "acme-web", sentence="Merge PR #7 by bob? yes/no")] + [
    seat(n, f"acme-{n}", word="done", sentence=f"Shipped part {n}.") for n in range(3, 13)]


def blocks(infos, width, most=None):
    """The seats' blocks as a pipe draws them: what each seat asking or done says opens under
    its row (`menu.detail`)."""
    widths = menu.v5o_column_widths(infos, width)
    room = widths["room"] - (2 + widths["num"] + 2)
    details = {info["name"]: menu.detail(None, info, room) for info in infos
               if info["word"] in ("needs you", "done")}
    return menu.v5o_seat_blocks(infos, width, widths, most, details)


def said(block):
    """A seat's block as one sentence: its lines after the row's own columns, joined."""
    lines = [terminal.plain(line) for line in block]
    head, _, first = lines[0].partition("needs you")
    return " ".join(" ".join([first] + lines[1:]).split())


class SeatQuestionWhole(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                                                         "NO_COLOR": "1"}))

    def test_a_seats_question_takes_the_lines_it_needs(self):
        for width in (100, 60, 40):
            with self.subTest(width=width):
                for block in blocks([seat(1, "fix-api"), seat(2, "acme-web")], width):
                    self.assertEqual(said(block), QUESTION)
                    self.assertGreater(len(block), 2)
                    self.assertTrue(all(terminal.cells(terminal.plain(line)) <= width
                                        for line in block))

    def test_a_block_taller_than_most_is_cut_to_it_and_ends_in_its_mark(self):
        for width in (100, 60, 40):
            with self.subTest(width=width):
                [block] = blocks([seat(1, "fix-api")], width, most=4)
                self.assertEqual(len(block), 4)
                self.assertTrue(block[-1].endswith("…"))
                # the cut line stays under its row, as the lines before it
                self.assertEqual(*[len(line) - len(line.lstrip()) for line in block[-2:]])
                self.assertTrue(QUESTION.startswith(said(block)[:-1].rstrip()))
        # a block that fits is as it is, a tasks bar among them
        rows = [seat(1, "fix-api", sentence="Merge PR #7 by bob? yes/no"),
                seat(2, "acme-web", word="working", sentence="", bar=(1, 3))]
        self.assertEqual(blocks(rows, 100, most=2), blocks(rows, 100))

    def draw(self, cursor, width, height, keyboard=True):
        """The screen as plain text, the page count and the seat on each screen row."""
        groups = ([{"name": "acme", "checkout": None, "seats": ROWS}], ROWS, 2, 0)
        out, drawn = io.StringIO(), {} if keyboard else None
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=height), redirect_stdout(out):
            page, pages = menu.draw(self.cfg, [], cursor=cursor, drawn=drawn, groups=groups,
                                    look=False)
        rows = {row: what for row, (what, _) in (drawn or {}).get("spots", {}).items()}
        return (" ".join(terminal.plain(terminal.ANSI.sub("", out.getvalue())).split()),
                (page, pages), rows)

    def test_the_menu_shows_it_whole_with_the_keyboard_or_without(self):
        for width in (100, 44):
            for keyboard in (True, False):
                with self.subTest(width=width, keyboard=keyboard):
                    # with the keyboard it opens under its row once that row is highlighted
                    screen, _, _ = self.draw("fix-api", width, 60, keyboard)
                    self.assertIn(QUESTION, screen)
                    screen, _, _ = self.draw("acme-web", width, 60, keyboard)
                    self.assertEqual(QUESTION in screen, not keyboard)

    def test_in_the_popup_over_a_seat_a_question_past_its_page_is_cut_to_it(self):
        # the popup over an 80x27 terminal: 80% by 70%, less its border
        screen, _, _ = self.draw("fix-api", 62, 19)
        self.assertNotIn(QUESTION, screen)
        # its lines under the row are half the screen at most, the last ending in `…`,
        # and the rows after it stay on the page
        self.assertIn("Reason 6: the parser reads both, and v2 drops the legac… 2 acme-web", screen)
        self.assertIn("2 acme-web opus ! needs you", screen)
        self.assertTrue(screen.endswith("← 1 / 3 → n new x stop c config esc leave"), screen)

    def test_what_opens_takes_only_the_lines_the_screen_has_left(self):
        groups = ([{"name": "acme", "checkout": None, "seats": ROWS}], ROWS, 2, 0)
        for width in (38, 62):
            for height in range(7, 14):
                with self.subTest(width=width, height=height):
                    out = io.StringIO()
                    with patch.object(terminal, "width", return_value=width), \
                            patch.object(terminal, "height", return_value=height), \
                            redirect_stdout(out):
                        menu.draw(self.cfg, [], cursor="fix-api", drawn={}, groups=groups,
                                  keys=terminal.keys(menu.KEYS), look=False)
                    lines = [terminal.ANSI.sub("", line) for line in
                             out.getvalue().split("\033[J")[0].split("\n")[:-1]]
                    # the usage and the keys stay, over the two lines every draw keeps
                    self.assertLessEqual(len(lines), height - 2, "\n".join(lines))
                    self.assertTrue(lines[0].startswith("  Claude"), lines)
                    self.assertIn("esc leave", lines[-1])

    def test_no_page_turns_as_the_highlight_moves(self):
        for width in (44, 62, 100):
            for height in (*range(8, 24), 50):
                with self.subTest(width=width, height=height):
                    # the rows under the highlighted one move down for its lines, but every seat
                    # keeps its page: a page holds the most lines any seat on it opens
                    drawn = {}
                    for row in ROWS:
                        _, (page, pages), rows = self.draw(row["name"], width, height)
                        seats = {what for what in rows.values() if what}
                        self.assertEqual(drawn.setdefault(page, (pages, seats)), (pages, seats))


if __name__ == "__main__":
    unittest.main(verbosity=2)
