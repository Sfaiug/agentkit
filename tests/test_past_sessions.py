"""A seat the owner stopped has no row under its project: it keeps its number on the past
screen, `p`, offered on the key line while there is one, where Enter reopens it where it stopped
and `x` removes it at once, the rest staying up; from a pipe a number reopens, `x` asks which to
remove by the numbers on the screen, and `x` on the main screen never offers a stopped seat and
asks by the main screen's numbers.

The keyboard tests run `menu.loop` in a child on a pty of its own, the way
tests/test_close_and_info.py does (its `Menu`), with the listing, each seat's word, the opening
and the stop faked; the line tests call `show_past` and `stop_session` in this process with the
line reader patched.  Nothing here starts a seat or a tmux server.
"""

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
from test_close_and_info import ENTER, Menu
from agentkit import menu, orch, terminal

CFG = {"fixture": True}            # handed through to the opening, and read by nothing here
NOW = time.time()
ALPHA = {"name": "alpha", "repo": "/home/x/code/atoll", "path": "/", "created": NOW - 86400,
         "closed": None}
OMEGA = {"name": "omega", "repo": "/home/x/code/atoll", "path": "/", "created": NOW - 86400,
         "closed": NOW - 7200, "resumable": True}
ZETA = {"name": "zeta", "repo": None, "path": "/", "created": NOW - 86400, "closed": NOW - 300,
        "resumable": False, "restart": "starts fresh"}


class Keys(unittest.TestCase):
    def test_a_stopped_seat_has_no_row_and_p_is_offered_while_there_is_one(self):
        shown = Menu(self, {"alpha": "working", "omega": "stopped"})
        lines = shown.frame()
        self.assertIn("alpha", shown.highlighted(lines))
        self.assertFalse(any("omega" in line for line in lines), lines)
        self.assertRegex(lines[-1], r"   x stop   p past   c config   ")
        shown.leave()
        alone = Menu(self, {"alpha": "working"})
        self.assertNotIn("p past", "\n".join(alone.frame()))
        alone.leave()

    def test_p_lists_it_with_its_number_and_enter_reopens_it(self):
        shown = Menu(self, {"alpha": "working", "omega": "stopped"})
        shown.frame()
        shown.send(b"p")
        lines = shown.frame(keys="esc back")
        self.assertIn("past sessions", lines[0])
        self.assertRegex(shown.highlighted(lines), r"^›\s+2  omega  -  stopped \d+[smhd] ago$")
        self.assertFalse(any("alpha" in line for line in lines), lines)
        self.assertRegex(lines[-1], r"⏎ reopen   x remove   esc back")
        mark = shown.mark()
        shown.send(ENTER)
        shown.saw("<opened omega>", after=mark)
        lines = shown.frame(after=mark)                          # the menu is back
        self.assertIn("alpha", shown.highlighted(lines))
        shown.leave()

    def test_x_on_the_past_screen_removes_the_highlighted_seat_and_the_rest_stay(self):
        shown = Menu(self, {"alpha": "working", "omega": "stopped", "zeta": "stopped"})
        shown.frame()
        shown.send(b"p")
        lines = shown.frame(keys="esc back")
        self.assertIn("omega", shown.highlighted(lines))
        shown.send(b"j")
        shown.frame(lambda lines: "zeta" in shown.highlighted(lines), keys="esc back")
        mark = shown.mark()
        shown.send(b"x")
        shown.saw("<stopped zeta>", after=mark)
        lines = shown.frame(keys="esc back", after=mark)
        self.assertIn("omega", shown.highlighted(lines))
        self.assertFalse(any("zeta" in line for line in lines), lines)
        mark = shown.mark()
        shown.send(b"x")
        shown.saw("<stopped omega>", after=mark)
        # none left: the menu is back, and once it has read the seats again, p is not offered
        lines = shown.frame(lambda lines: "p past" not in "\n".join(lines), after=mark)
        self.assertIn("alpha", shown.highlighted(lines))
        shown.leave()
        self.assertNotIn("everything it runs", shown.text())
        self.assertEqual(shown.text().count("<stopped"), 2)


class Lines(unittest.TestCase):
    """The same screen read a line at a time: a pipe, a file, the smoke suite."""

    def setUp(self):
        self.out = io.StringIO()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(self.out))
        self.stack.enter_context(patch.object(terminal, "width", return_value=100))
        self.opened = self.stack.enter_context(patch.object(menu, "open_session"))
        self.closed = self.stack.enter_context(patch.object(menu, "close_seat"))
        self.paused = self.stack.enter_context(patch.object(menu, "pause"))
        self.stopped = self.stack.enter_context(patch.object(orch, "cmd_stop"))
        self.stack.enter_context(patch.object(orch, "listed", dict))
        self.stack.enter_context(patch.object(orch, "checkout_of",
                                              lambda repo, **_kw: repo and Path(repo)))
        self.stack.enter_context(patch.object(menu, "selection_of", lambda cfg, name: {
            "orchestrator": "opus"} if name == "omega" else None))

    def test_a_number_reopens_a_stopped_seat_and_x_asks_which_to_remove(self):
        # `x` asks by the numbers on the screen: 3 is zeta here, as it is on the main screen
        with patch.object(menu, "read", side_effect=["x", "3", "2"]):
            menu.show_past(CFG, [ALPHA, OMEGA, ZETA])
        self.closed.assert_called_once_with("zeta", False)
        self.opened.assert_called_once_with(CFG, OMEGA, False)
        screens = self.out.getvalue().split("past sessions")[1:]
        self.assertEqual(len(screens), 2)
        # under their projects' headings, as on the main screen, with their orchestrators
        self.assertRegex(screens[0], r"\natoll\n  2  omega  opus  stopped 2h ago\n\n"
                                     r"no project\n  3  zeta   -     stopped 5m ago  starts fresh\n")
        self.assertNotIn("alpha", screens[0])
        self.assertIn("x remove   esc back", screens[0])
        self.assertIn("2 omega · 3 zeta", screens[0])
        self.assertNotIn("zeta", screens[1])

    def test_a_number_that_is_no_past_seat_is_said_and_an_empty_line_goes_back(self):
        with patch.object(menu, "read", side_effect=["1", ""]):
            menu.show_past(CFG, [ALPHA, OMEGA])
        self.paused.assert_called_once_with("no past session 1", "x remove   esc back")
        self.opened.assert_not_called()
        self.closed.assert_not_called()

    def test_x_on_the_main_screen_never_offers_a_stopped_seat_and_keeps_its_numbers(self):
        # omega, stopped, has no row on the main screen, and alpha is 2 there as it is here
        with patch.object(menu, "read", side_effect=["2", "n"]) as read:
            menu.stop_session([OMEGA, ALPHA], False)
        self.assertIn("2 alpha", self.out.getvalue())
        self.assertNotIn("omega", self.out.getvalue())
        self.assertEqual(read.call_args_list[-1].args[0], menu.stop_question("alpha"))
        with patch.object(menu, "read", side_effect=["1", "y"]):
            menu.stop_session([OMEGA], False)
        self.paused.assert_called_once_with("no session to stop")
        self.stopped.assert_not_called()
        self.assertNotIn("stop omega", self.out.getvalue())

    def test_more_than_a_page_keeps_each_row_under_its_projects_heading(self):
        # with the keys, on a 100x24 screen: 18 lines between the frame and the keys for 20 seats
        seats = [dict(OMEGA, name=f"fix-api-{n}") for n in range(20)]
        drawn = []
        with patch.object(terminal, "taken", return_value=True), \
                patch.object(terminal, "height", return_value=24), \
                patch.object(terminal, "frame", lambda title, body, *_a, **_kw:
                             drawn.append([terminal.plain(line) for line in body]) or {}), \
                patch.object(terminal, "read_key",
                             side_effect=[terminal.Key("down")] * 19 + [terminal.Key("esc")]):
            menu.show_past(CFG, seats, keyboard=None)
        self.assertEqual([lines[0] for lines in drawn], ["atoll"] * 20)
        self.assertRegex(drawn[-1][-1], r"^›\s+20\s+fix-api-19\s+-\s+stopped 2h ago$")

    def test_on_a_narrow_screen_how_long_ago_goes_whole_under_its_row(self):
        seat = {"name": "fix-api", "repo": None, "closed": 1}
        rows = {}
        for width in (26, 100):
            with patch.object(terminal, "width", return_value=width), \
                    patch.object(orch, "age", return_value="120d"):
                lines, places = menu.past_body([(12, seat)], "fix-api")
            rows[width] = [terminal.plain(lines[n]) for n in places]
        self.assertEqual(rows, {26: ["› 12 fix-api -", "stopped 120d ago"],
                                100: ["› 12 fix-api - stopped 120d ago"]})

    def test_a_dry_run_draws_the_screen_once(self):
        with patch.object(menu, "read", side_effect=AssertionError("read")):
            menu.show_past(CFG, [ALPHA, OMEGA], dry_run=True)
        self.assertEqual(self.out.getvalue().count("past sessions"), 1)
        self.assertIn("2  omega", self.out.getvalue())


if __name__ == "__main__":
    unittest.main()
