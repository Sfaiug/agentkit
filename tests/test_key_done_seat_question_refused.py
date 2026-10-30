"""A seat whose plan is done is refused its question card until the owner writes to it again.

Before Claude draws an AskUserQuestion card it runs its PreToolUse hooks.  Where the seat's plan
is done, every line ticked, and the owner has written nothing in its conversation since the
plan's last write, the question would hold only the owner: the hook prints Claude's deny, its
reason telling the seat to say it in its last message instead.  A line still open, no plan, or a
word from the owner since, and the hook prints nothing: the card goes up.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, before
seats of tests/fixtures/akseat.py whose hooks fire as their harness fires them
(tests/fixtures/hookdrive.py).
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import PLAN_LINE, Seat
from fixtures import hookdrive

DONE = ("- [x] The parser parses · check: `true` · acme · written 2026-10-23 09:00"
        " · done 0123456789ab\n")
# as Claude Code 2.1.305 hands its PreToolUse hooks a question card before drawing it
ASKED = {"tool_name": "AskUserQuestion", "tool_input": {"questions": [
    {"question": "The parser is live and checked. Can I mark this done?", "header": "Done",
     "multiSelect": False, "options": [{"label": "Yes", "description": "It is done"},
                                       {"label": "No", "description": "Not yet"}]}]}}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class DoneSeatQuestionRefused(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = hookdrive.Hooks(cls.home)

    def seat(self, name, plan=None):
        """A seat mid-turn on a job the owner's word began, its plan, when given, written since."""
        seat = Seat(self.home, name, screen="claude-working-pane.txt")
        self.hooks.prompt("go", seat)
        if plan is not None:
            # stamped from the clock the word's own stamp was read from: a file system's stamp
            # may lag that clock by a tick
            self.home.write(f".agentkit/state/plan-{name}.md", plan, ago=0)
        return seat

    def asked(self, seat):
        """What the seat's PreToolUse hooks printed as its question card was about to go up."""
        fired = self.hooks.fire("PreToolUse", ASKED, seat=seat.name, pane=seat)
        self.assertEqual(fired.code, 0, fired.err)
        return fired.out

    def test_a_done_plan_with_nothing_from_the_owner_since_refuses_the_card(self):
        printed = json.loads(self.asked(self.seat("done", DONE)))
        reason = printed["hookSpecificOutput"].pop("permissionDecisionReason")
        self.assertEqual(printed, {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                          "permissionDecision": "deny"}})
        self.assertIn("last message", reason)

    def test_an_open_line_or_no_plan_lets_the_card_go_up(self):
        for name, plan in (("open-line", DONE + PLAN_LINE + "\n"), ("no-plan", None)):
            with self.subTest(name):
                self.assertEqual(self.asked(self.seat(name, plan)), "")

    def test_the_owner_writing_since_the_plans_last_write_lets_the_card_go_up(self):
        seat = Seat(self.home, "owner-wrote", screen="claude-working-pane.txt")
        self.home.write(".agentkit/state/plan-owner-wrote.md", DONE, ago=600)
        self.hooks.prompt("8080", seat)
        self.assertEqual(self.asked(seat), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
