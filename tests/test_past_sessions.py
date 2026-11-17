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
from test_close_and_info import ENTER, Menu
from test_hover import played, texts
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


def click(answer):
    """A click on the row the screen up, as a person sees it, draws `answer` on."""
    return lambda screen: terminal.Key("click", col=3, row=next(
        row for row, line in enumerate(screen, 1) if answer in line))


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

    def x(self, size, *steps):
        """`x` on the first of three past sessions in a terminal of `size`, then each of `steps`,
        a function of the screen up, as a person sees it, to the key read next, or the size the
        terminal is resized to, then Esc: each read's screen and the rows its spots are on, and
        the sessions removed."""
        seats = [dict(name=f"fix-api-{n}", repo="/x/acme", closed=NOW - n) for n in range(1, 4)]
        size, out, reads, since = list(size), io.StringIO(), [], [0]
        steps = iter([lambda screen: terminal.Key("char", "x"), *steps,
                      *[lambda screen: terminal.Key("esc")] * 2])

        def read_key(timeout=None, wake=None):
            screen = texts(played(out.getvalue()[since[0]:], size[1]))
            reads.append((screen, {row: what for row, (what, *_) in terminal._SPOTS.items()}))
            step = next(steps)
            if isinstance(step, tuple):         # resized: what is drawn next is drawn whole
                size[:], since[0] = step, len(out.getvalue())
                terminal._ASKED, terminal._UP = True, terminal._UP and []
                return None
            return step(screen)
        with ExitStack() as stack:
            for obj, name, value in ((terminal, "colour_depth", 0), (terminal, "utf8", True),
                                     (orch, "listed", {}), (menu, "seat_progress", (0, 0)),
                                     (menu, "past_said", ("", ""))):
                stack.enter_context(patch.object(obj, name, return_value=value))
            for name, at in (("width", 0), ("height", 1)):
                stack.enter_context(patch.object(terminal, name, lambda *_a, at=at: size[at]))
            stack.enter_context(patch.object(orch, "checkout_of", lambda repo, **_kw: Path(repo)))
            stack.enter_context(patch.object(terminal, "read_key", read_key))
            stack.enter_context(patch.multiple(terminal, _UP=None, _SPOTS={}, _ASKED=False,
                                               _TAKEN=Mock(again=(None, None))))
            removed = stack.enter_context(patch.object(menu, "remove_seat"))
            stack.enter_context(redirect_stdout(out))
            menu.show_past(CFG, seats, keyboard=Mock())
        return reads, [call.args[0] for call in removed.call_args_list]

    def test_x_asks_on_a_card_whose_answers_are_clicked_where_they_show(self):
        for size in ((100, 10), (40, 11), (30, 12), (30, 10)):
            for answer, removed in (("✓ Keep", []), ("× Remove", ["fix-api-1"])):
                with self.subTest(size=size, answer=answer):
                    reads, gone = self.x(size, click(answer))
                    screen = reads[1][0]        # read on the card: it waits for its answer
                    # nothing scrolled off: the heading on the first row, the card's keys last
                    self.assertIn("past sessions", screen[0])
                    self.assertIn("esc back", [line for line in screen if line][-1])
                    self.assertTrue(all(any(word in line for line in screen)
                                        for word in ("✓ Keep", "× Remove")), screen)
                    self.assertEqual(gone, removed)
                    self.assertNotIn("✓ Keep", "\n".join(reads[2][0]))     # answered

    def test_a_card_shrunk_to_ten_rows_has_its_answers_on_the_rows_they_are_clicked(self):
        for answer, removed in (("✓ Keep", []), ("× Remove", ["fix-api-1"])):
            with self.subTest(answer=answer):
                reads, gone = self.x((100, 24), (100, 10), click(answer))
                screen, spots = reads[2]        # the frame after the resize
                self.assertIn("past sessions", screen[0])
                self.assertEqual(
                    {what: row for row, what in spots.items() if what is not None},
                    {number: next(row for row, line in enumerate(screen, 1) if word in line)
                     for number, word in enumerate(("✓ Keep", "× Remove"))})
                self.assertEqual(gone, removed)

    def test_x_with_no_room_for_both_answers_asks_nothing_and_removes_nothing(self):
        reads, gone = self.x((30, 5))
        self.assertEqual(len(reads), 2)         # the page, and the page again after `x`
        self.assertFalse(any("Keep" in "\n".join(screen) for screen, _ in reads))
        self.assertEqual(gone, [])

    def test_p_lists_it_with_its_number_and_enter_reopens_it(self):
        shown = Menu(self, {"alpha": "working", "omega": "stopped"})       # a child on a pty
        shown.frame()
        shown.send(b"p")
        lines = shown.frame(keys="esc back")
        self.assertIn("past sessions", lines[0])
        self.assertRegex(shown.highlighted(lines), r"^›\s+1  omega  ")
        self.assertEqual(lines[-1], "  ↑↓←→ move   ⏎ reopen   x remove   esc back")
        mark = shown.mark()
        shown.send(ENTER)
        shown.saw("<opened omega>", after=mark)
        shown.leave()

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
