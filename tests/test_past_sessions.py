"""The past screen, `p`, from a pipe, `show_past` called with the line reader patched: a number
reopens, `x` asks which to remove by the numbers on the screen (the keys: test_key_past_*)."""

from contextlib import ExitStack, redirect_stdout
import io
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import menu, orch, terminal

CFG = {"fixture": True}            # handed through to the opening, and read by nothing here
NOW = time.time()
ALPHA = {"name": "alpha", "repo": "/home/x/code/atoll", "path": "/", "created": NOW - 86400,
         "closed": None}
OMEGA = {"name": "omega", "repo": "/home/x/code/atoll", "path": "/", "created": NOW - 86400,
         "closed": NOW - 7200, "resumable": True}
ZETA = {"name": "zeta", "repo": None, "path": "/", "created": NOW - 86400, "closed": NOW - 300,
        "resumable": False, "restart": "starts fresh"}


class Lines(unittest.TestCase):
    """The same screen read a line at a time: a pipe, a file, the smoke suite."""

    def setUp(self):
        self.out = io.StringIO()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(self.out))
        self.stack.enter_context(patch.object(terminal, "width", return_value=100))
        self.opened = self.stack.enter_context(patch.object(menu, "open_session"))
        self.closed = self.stack.enter_context(patch.object(menu, "remove_seat"))
        self.paused = self.stack.enter_context(patch.object(menu, "pause"))
        self.stack.enter_context(patch.object(orch, "listed", dict))
        self.stack.enter_context(patch.object(orch, "checkout_of",
                                              lambda repo, **_kw: repo and Path(repo)))
        self.stack.enter_context(patch.object(menu, "seat_progress", return_value=(0, 0)))
        self.stack.enter_context(patch.object(menu, "past_said", lambda session: (
            "", session.get("restart") or "")))

    def test_a_number_reopens_a_stopped_seat_and_x_asks_which_to_remove(self):
        with patch.object(menu, "read", side_effect=["x", "1", "1"]):
            menu.show_past(CFG, [ALPHA, OMEGA, ZETA])
        self.closed.assert_called_once_with("zeta", False)
        self.opened.assert_called_once_with(CFG, OMEGA, False)
        screens = self.out.getvalue().split("past sessions")[1:]
        self.assertEqual(len(screens), 2)
        self.assertRegex(screens[0], r"\n  1  zeta\s+no plan\s+\d\d:\d\d\n"
                                     r"(.*\n)*  2  omega  atoll  no plan\s+\d\d:\d\d\n")
        self.assertNotIn("alpha", screens[0])
        self.assertIn("x remove   esc back", screens[0])
        self.assertIn("1 zeta · 2 omega", screens[0])
        self.assertNotIn("zeta", screens[1])

    def test_a_number_that_is_no_past_seat_is_said_and_an_empty_line_goes_back(self):
        with patch.object(menu, "read", side_effect=["2", ""]):
            menu.show_past(CFG, [ALPHA, OMEGA])
        self.paused.assert_called_once_with("not a key: '2'", "x remove   esc back")
        self.opened.assert_not_called()
        self.closed.assert_not_called()

    def test_at_every_width_a_page_is_under_its_day_and_a_tall_opened_row_keeps_every_line(self):
        past = [(n, dict(OMEGA, name=f"fix-api-{n}", closed=NOW - n * 80000)) for n in range(1, 13)]
        said = {"fix-api-7": (" ".join(["The docs site ships"] * 20), "starts fresh")}
        for width in (20, 30, 60, 100):
            with self.subTest(width=width), patch.object(terminal, "width", return_value=width), \
                    patch.object(terminal, "away", return_value=False):
                lines = [terminal.plain(line, True)
                         for line in menu.past_body(past, "fix-api-7", 8, said)[0]]
                self.assertTrue(all(terminal.cells(line) <= width for line in lines), lines)
                self.assertIn(lines[0], ("today", "yesterday", "this week", "earlier"))
                self.assertRegex(lines[1], r"^›\s+7  fix-api-7(\s|$)")     # its name whole
                self.assertEqual(sum(line.startswith("›") for line in lines), 1)
                self.assertEqual(lines[-1].strip(), "starts fresh")

    def test_a_dry_run_draws_the_screen_once(self):
        with patch.object(menu, "read", side_effect=AssertionError("read")):
            menu.show_past(CFG, [ALPHA, OMEGA], dry_run=True)
        self.assertEqual(self.out.getvalue().count("past sessions"), 1)
        self.assertIn("1  omega", self.out.getvalue())


if __name__ == "__main__":
    unittest.main()
