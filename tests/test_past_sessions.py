"""The past screen, `p`, from a pipe, `show_past` called with the line reader patched: a number
reopens, `x` asks which to remove by the numbers on the screen; then with the keys read patched."""

from contextlib import ExitStack, redirect_stdout
import io
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from agentkit import menu, orch, terminal

CFG = {"fixture": True}            # handed through to the opening, and read by nothing here
DAYS = ("today", "yesterday", "this week", "earlier")
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
        past = [(n, dict(OMEGA, name=f"fix-api-{n}", closed=NOW - n * 80000,
                         repo="/x/acme-data-migration-and-integration-platform"))
                for n in range(1, 13)]
        said = {"fix-api-7": (" ".join(["The docs site ships"] * 20), "starts fresh")}
        for width in (20, 30, 60, 100):
            with self.subTest(width=width), patch.object(terminal, "width", return_value=width), \
                    patch.object(terminal, "away", return_value=False):
                lines = [terminal.plain(line, True)
                         for line in menu.past_body(past, "fix-api-7", 8, said)[0]]
                self.assertTrue(all(terminal.cells(line) <= width for line in lines), lines)
                self.assertIn(lines[0], DAYS)
                self.assertRegex(lines[1], r"^›\s+7  fix-api-7(\s|$)")     # its name whole
                self.assertEqual(sum(line.startswith("›") for line in lines), 1)
                self.assertEqual(lines[-1].strip(), "starts fresh")

    def test_a_dry_run_draws_the_screen_once(self):
        with patch.object(menu, "read", side_effect=AssertionError("read")):
            menu.show_past(CFG, [ALPHA, OMEGA], dry_run=True)
        self.assertEqual(self.out.getvalue().count("past sessions"), 1)
        self.assertIn("1  omega", self.out.getvalue())


class Keys(unittest.TestCase):
    """The screen with the keys: each frame drawn, as plain lines, and what was reopened."""

    def drive(self, seats, keys, width=100, height=24):
        drawn = []
        with ExitStack() as stack:
            for obj, name, value in ((terminal, "width", width), (terminal, "height", height),
                                     (terminal, "taken", True), (terminal, "away", False),
                                     (terminal, "utf8", True), (orch, "listed", {}),
                                     (menu, "seat_progress", (0, 0))):
                stack.enter_context(patch.object(obj, name, return_value=value))
            stack.enter_context(patch.object(orch, "checkout_of", lambda repo, **_kw: Path(repo)))
            stack.enter_context(patch.object(menu, "past_said", lambda seat: (
                (seat["name"] + " started this job. ") * 20, "starts fresh")))
            stack.enter_context(patch.object(terminal, "frame", lambda title, body, *_a, **_kw:
                                             drawn.append([terminal.plain(line, True).rstrip()
                                                           for line in body]) or {}))
            stack.enter_context(patch.object(terminal, "read_key", side_effect=[
                terminal.Key(*key) for key in keys]))
            opened = stack.enter_context(patch.object(menu, "open_session"))
            menu.show_past(CFG, seats, keyboard=Mock())
        return drawn, [call.args[1]["name"] for call in opened.call_args_list]

    def test_more_than_a_page_keeps_each_row_under_its_days_heading(self):
        seats = [dict(name=f"fix-api-{n}", repo="/x/acme", closed=NOW - n * 40000)
                 for n in range(1, 21)]
        drawn, _ = self.drive(seats, [("down",)] * 19 + [("esc",)])
        for number, lines in enumerate(drawn, 1):
            self.assertIn(lines[0], DAYS)
            self.assertEqual([line for line in lines if line.startswith("›")],
                             [next(line for line in lines if f"  fix-api-{number} " in line)])
        self.assertEqual(len(drawn), 20)

    def test_the_next_row_opens_from_its_start_not_where_the_last_was_turned_to(self):
        seats = [dict(name=name, repo="/x/acme", closed=NOW - 100) for name in ("alpha", "beta")]
        drawn, _ = self.drive(seats, [("down",)] * 3 + [("esc",)], 40, 14)
        self.assertEqual(drawn[2][-1], "     starts fresh")       # alpha turned to its end
        self.assertIn(drawn[3][0], DAYS)
        self.assertRegex(drawn[3][1], r"^› 2  beta ")
        self.assertEqual(drawn[3][2], "     beta started this job. beta started")

    def test_1_then_2_reopens_row_12(self):
        seats = [dict(name=f"fix-api-{n}", repo="/x/acme", closed=NOW - n) for n in range(1, 13)]
        self.assertEqual(self.drive(seats, [("char", "1"), ("char", "2")])[1], ["fix-api-12"])


if __name__ == "__main__":
    unittest.main()
