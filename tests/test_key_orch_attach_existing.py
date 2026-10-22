"""`ak orch NAME` for a seat that is running opens that seat; it never starts another.

A person opens a seat by its name, and a model told "open acme" runs the same command: the seat
already running is the one they mean, with its conversation and its scrollback, so ak attaches
to it -- or, with no terminal to hand over, says how to -- and starts nothing beside it.
`--dry-run` only says where it would attach.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py on a seat from tests/fixtures/akseat.py, and a person's
terminal is tests/fixtures/akterm.py.
"""

import json
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

AGE = r"\(\d+[smhd] old\)"    # how long tmux has held the session, which a test cannot set


def held(home):
    """Each session ak's tmux server holds, with its pane's id and process, and whether a
    client is on it."""
    return home.tmux("list-panes", "-a", "-F",
                     "#{session_name} #{pane_id} #{pane_pid} #{session_attached}").out


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WithoutATerminal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.seat = Seat(cls.home, "fix-api", cwd=cls.home.path / "code")
        cls.record = cls.home.path / ".agentkit/state/session-fix-api.json"

    def setUp(self):
        self.before = held(self.home)
        self.kept = self.record.read_text()

    def assert_seat_untouched(self, looked_only):
        self.assertEqual(held(self.home), self.before)    # no new session, no respawned pane
        self.assertEqual(self.seat.typed(), "")
        if looked_only:
            self.assertEqual(self.record.read_text(), self.kept)
        else:
            # opening it may note when it was seen; the conversation stays the seat's own
            self.assertEqual(json.loads(self.record.read_text())["conversation"], "conv-fix-api")

    def test_a_dry_run_says_where_it_would_attach_and_attaches_nothing(self):
        done = self.home.ak("orch", "fix-api", "--dry-run")
        self.assertEqual(done.code, 0, done.err)
        self.assertRegex(done.out, rf"\Aorch: attaching to fix-api in "
                                   rf"{re.escape(str(self.home.path / 'code'))} {AGE}\n\Z")
        self.assert_seat_untouched(looked_only=True)

    def test_with_no_terminal_to_hand_over_it_says_how_to_attach(self):
        done = self.home.ak("orch", "fix-api")
        self.assertEqual(done.code, 0, done.err)
        attaching, how = done.out.splitlines()
        self.assertRegex(attaching, rf"\Aorch: attaching to fix-api in "
                                    rf"{re.escape(str(self.home.path / 'code'))} {AGE}\Z")
        # the tmux it names may be a path to it
        self.assertRegex(how, r"\Asession fix-api is running; attach it with "
                              r"`(\S*/)?tmux -L agentkit-test attach -t fix-api`\Z")
        self.assert_seat_untouched(looked_only=False)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class FromATerminal(unittest.TestCase):
    def test_the_terminal_shows_the_running_seat_and_nothing_else_starts(self):
        with Home() as home:
            seat = Seat(home, "acme", screen="claude-prompt-pane.txt")
            before = held(home).replace(" 0\n", " 1\n")
            term = Terminal(home, "orch", "acme", size=(120, 40))
            # a line of the seat's own screen, which only the seat's pane draws
            term.wait("bypass permissions on (shift+tab to cycle)")
            self.assertEqual(home.tmux("list-clients", "-F", "#{client_session}").out,
                             "acme\n")
            self.assertEqual(held(home), before)
            self.assertEqual(seat.typed(), "")


if __name__ == "__main__":
    unittest.main()
