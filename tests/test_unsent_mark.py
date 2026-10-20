"""Unsent text is a mark on the row, its words under the pointer.

The owner's choice of 20 Oct 2026: a seat holding text it never sent keeps its row as it would
be without it -- a working seat's progress line and `N of M` -- and the row ends in `✎ unsent`
in the needs-you colour; the row the pointer is on opens the text under itself, `✎` first,
before what it opens today, and past half the screen cuts it with `…` as it does a question, so
the usage and the keys stay on screen (the owner's rule of 14 Oct).  The reason never carries
the text.  Offline: the menu's own drawing functions on a seat info built here.
"""

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import menu, terminal

TEXT = ("Fix the login redirect for acme, then check that the session cookie survives the "
        "round trip through the proxy and tell me what broke")
AMBER = "\033[1;38;2;249;226;175m"      # needs you, on a dark true-colour terminal


def seat(word, bar=None, sentence=""):
    return {"number": "1", "name": "fix-api", "count": word, "word": word, "orchestrator": "opus",
            "sentence": sentence, "unsent": TEXT, "bar": bar, "crew": (("opus",), ("astra",)),
            "tasks": []}


def bare(line):
    """A drawn line as it reads, its spacing kept."""
    return terminal.ANSI.sub("", line)


def block(info, width=100, pointed=False):
    """The seat's lines as the menu draws them, the pointer on it where `pointed`."""
    widths = menu.v5o_column_widths([info], width)
    room = widths["room"] - (2 + widths["num"] + 2)
    details = {info["name"]: menu.detail(None, info, room)} if pointed else None
    return menu.v5o_seat_blocks([info], width, widths, details=details)[0]


class UnsentMark(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(terminal, "colour_depth", return_value=24))

    def test_a_working_seat_keeps_its_line_and_count_and_ends_in_the_mark(self):
        lines = block(seat("working", bar=(3, 7)))
        self.assertEqual(len(lines), 1, lines)
        row = bare(lines[0])
        self.assertRegex(row, r"● working +[━╸]+─* 3 of 7  ✎ unsent$")
        self.assertTrue(lines[0].endswith(f"{AMBER}✎ unsent\033[0m"), repr(lines[0]))

    def test_the_pointed_row_opens_the_whole_text_first(self):
        info = seat("working", bar=(3, 7))
        for width in (100, 60, 40):
            with self.subTest(width=width):
                lines = [bare(line).strip() for line in block(info, width, pointed=True)]
                head = next(n for n, line in enumerate(lines) if "✎ unsent" in line)
                under = lines[head + 1:]
                self.assertTrue(under[0].startswith("✎ Fix the login"), under)
                said = " ".join(under).partition("✎ ")[2]
                self.assertIn(TEXT, said)            # whole, wrapped at words, never cut
                self.assertEqual(under[-1], "opus ⚒   astra ◎")     # what it opened before
        opened = block(info, pointed=True)[1]
        self.assertIn(f"{AMBER}✎ Fix", opened)

    def test_an_idle_seat_shows_the_mark_and_never_the_old_sentence(self):
        info = seat("idle", sentence="nothing running")
        for pointed in (False, True):
            with self.subTest(pointed=pointed):
                lines = [bare(line) for line in block(info, pointed=pointed)]
                self.assertTrue(lines[0].endswith("○ idle  ✎ unsent"), lines)
                self.assertNotIn(" · unsent:", "\n".join(lines))
        self.assertEqual(menu.last_column("idle", 0, 0, unsent=TEXT),
                         f"{AMBER}✎ unsent\033[0m")

    def test_text_past_half_the_screen_is_cut_as_a_question_is(self):
        long = seat("working", bar=(3, 7))
        long["unsent"] = "word " * 330 + "LAST"
        question = dict(seat("needs you"), name="acme-web", number="2", unsent="",
                        sentence="question " * 180 + "LAST")

        def drawn(infos, cursor):
            out = io.StringIO()
            with patch.object(terminal, "width", return_value=80), \
                    patch.object(terminal, "height", return_value=40), \
                    patch.object(terminal, "_POINTER", None), redirect_stdout(out):
                menu.draw(self.cfg, [], cursor=cursor, drawn={}, look=False,
                          groups=([{"name": "acme", "checkout": None, "seats": infos}], infos, 0, 0))
            lines = [bare(line) for line in out.getvalue().splitlines()]
            self.assertIn("esc leave", "\n".join(lines[-3:]))
            self.assertNotIn("LAST", "\n".join(lines))
            return lines

        def opened(lines, first):
            at = next(n for n, line in enumerate(lines) if line.strip().startswith(first))
            return lines[at:next(n for n, line in enumerate(lines) if line.endswith("…")) + 1]

        self.assertEqual(len(opened(drawn([long], "fix-api"), "✎ word")), 40 // 2)
        # another seat's text lifts no question's limit
        self.assertEqual(opened(drawn([long, question], "acme-web"), "question"),
                         opened(drawn([question], "acme-web"), "question"))

    def test_without_utf8_the_mark_is_an_asterisk(self):
        with patch.dict(os.environ, {"LANG": "C", "LC_ALL": ""}):
            self.assertTrue(bare(block(seat("working", bar=(3, 7)))[0])
                            .endswith("3 of 7  * unsent"))


if __name__ == "__main__":
    unittest.main()
