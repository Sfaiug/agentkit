"""← and → turn the ak screen's pages, and the key line says which page is up.

The owner's words (14 Oct 2026): "if there are so many sessions to scroll, then it should be
navigable in pages with the right and left arrow keys."  With the keyboard, while the seats run
to more than one page, the key line starts with where the owner is, `←  1 / 3  →`, wrapped with the
keys and never wider than the screen; ← and →, or a click on either arrow, take the highlight
to the nearest page that way with something it can rest on, passing a page with none, and the
place between the arrows opens nothing.  The loop runs as tests/test_menu_keys.py runs it, in a
child on a pty of its own; the draws in this process use a temporary HOME and fake seats.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from test_menu_keys import Menu  # noqa: E402
from agentkit import config, menu, terminal  # noqa: E402

RIGHT, LEFT = b"\x1b[C", b"\x1b[D"


def page_of(lines):
    """The page up as the key line's mark says it, `2 / 3`."""
    return next((m.group(1) for line in lines
                 for m in [re.search(r"←  (\d+ / \d+)  →", line)] if m), None)


class TurnInTheLoop(unittest.TestCase):
    def test_right_and_left_turn_the_page_and_a_click_on_an_arrow_does(self):
        child = Menu(self, [f"seat-{n:02d}" for n in range(1, 13)], rows=12, cols=60)
        lines = child.frame()
        self.assertIn("seat-01", child.highlighted(lines))
        self.assertRegex(page_of(lines), r"^1 / [2-9]$")
        child.send(RIGHT)
        lines = child.frame(lambda lines: page_of(lines).startswith("2 / "))
        first = child.highlighted(lines)
        self.assertNotIn("seat-01", first)
        # the first seat of the page turned to is the first row under its heading
        self.assertEqual(first, next(line for line in lines if re.match(r"[›> ] +\d+  ", line)))
        child.send(LEFT)
        lines = child.frame(lambda lines: page_of(lines).startswith("1 / "))
        self.assertIn("seat-01", child.highlighted(lines))
        row = next(number for number, line in enumerate(lines, 1) if page_of([line]))
        child.click(lines[row - 1].index("→") + 1, row)
        lines = child.frame(lambda lines: page_of(lines).startswith("2 / "))
        row = next(number for number, line in enumerate(lines, 1) if page_of([line]))
        child.click(lines[row - 1].index("2 / ") + 1, row)      # the place: no seat 2
        child.click(lines[row - 1].index("←") + 1, row)
        child.frame(lambda lines: page_of(lines).startswith("1 / "))
        child.leave()
        self.assertNotIn("<opened", child.text())


class KeyLine(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch("agentkit.watch.live_state", side_effect=lambda seat, *a, **kw:
                                      {"state": "at_prompt", "rule": "fixture", "since": 9100,
                                       "began": 9100, "evidence": ""}))
        directory = config.CODE / "acme"
        directory.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(directory)], check=True)
        self.seats = [{"name": f"acme-{n:02d}", "repo": str(directory), "path": str(directory),
                       "created": 9000 + n} for n in range(14)]
        for seat in self.seats:
            config.save_session(self.cfg, seat["name"], "fable", ["opus"],
                                {"repo": str(directory), "cwd": str(directory)})

    def screen(self, width, height, cursor=None):
        drawn = {}
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=height), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, self.seats, terminal.keys(menu.KEYS, enter="open"), 0, cursor,
                      drawn, look=False)
        return terminal.ANSI.sub("", out.getvalue().replace("\033[K", "")).split("\n")[:-1], drawn

    def test_the_page_mark_leads_the_keys_and_no_line_outgrows_the_screen(self):
        for width in (40, 60, 100):
            with self.subTest(width=width):
                lines, drawn = self.screen(width, 14)
                pages = len(drawn["turns"])
                self.assertGreater(pages, 1)
                self.assertTrue(all(terminal.cells(line) <= width for line in lines), lines)
                mark = next(line for line in lines if "←" in line)
                self.assertTrue(mark.startswith(f"  ←  1 / {pages}  →"), mark)
                self.assertFalse(any(re.search(r" \d+/\d+$", line) for line in lines), lines)
                lines, _ = self.screen(width, 14, cursor="acme-13")
                self.assertEqual(page_of(lines), f"{pages} / {pages}")
                self.assertTrue(all(terminal.cells(line) <= width for line in lines), lines)

    def test_a_page_with_nothing_to_rest_on_is_passed(self):
        self.assertEqual(menu.turned(["a", None, "c"], 0, "a", 1), "c")
        self.assertEqual(menu.turned(["a", None, "c"], 2, "c", -1), "a")
        self.assertEqual(menu.turned(["a", None], 0, "a", 1), "a")          # nowhere to go
        self.assertEqual(menu.turned(["a", "b"], 0, "a", -1), "a")

    def test_a_heading_over_each_of_its_projects_pages_turns_to_every_one(self):
        # a project naming its feature switches heads each of its pages with a row of its own,
        # which the highlight rests on only on the first
        groups = menu.v5o_groups(self.cfg, self.seats, look=False)
        groups[0][0]["switches"] = []
        with patch.object(menu, "v5o_groups", return_value=groups):
            lines, drawn = self.screen(60, 11, cursor=groups[0][0]["checkout"])
            pages = len(drawn["turns"])
            self.assertGreater(pages, 2)
            for step, number in [(1, n) for n in range(2, pages + 1)] + [
                    (-1, n) for n in range(pages - 1, 0, -1)]:
                cursor = menu.turned(drawn["turns"], number - 1 - step, drawn["cursor"], step)
                lines, drawn = self.screen(60, 11, cursor=cursor)
                self.assertEqual(page_of(lines), f"{number} / {pages}")


if __name__ == "__main__":
    unittest.main()
