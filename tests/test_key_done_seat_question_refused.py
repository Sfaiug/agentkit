"""A seat whose plan is done is refused its question card until the owner writes to it again.

Before Claude draws an AskUserQuestion card it runs its PreToolUse hooks.  Where the seat's plan
is done, every line ticked, and the owner has written nothing in its conversation since the
plan's last write, the question would hold only the owner: the hook prints Claude's deny, its
reason telling the seat to say it in its last message instead.  A line still open, no plan, or a
word from the owner since, and the hook prints nothing: the card goes up.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, writing
and ticking the plan of a seat of tests/fixtures/akseat.py in a project of gitrig.py, whose hooks
fire as their harness fires them (tests/fixtures/hookdrive.py).
"""

import json
import os
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig
from fixtures import hookdrive

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

    def seat(self, name, planned=("parser.py",)):
        """A seat mid-turn on a job the owner's word began, in a project of its own.  Since,
        `ak plan add` wrote it a line for each file in `planned` that it is on main, and once
        the parser landed there `ak plan` ticked its line."""
        rig = Rig(self.home, name)
        seat = Seat(self.home, name, screen="claude-working-pane.txt", cwd=rig.path,
                    record={"repo": str(rig.path)})
        self.hooks.prompt("go", seat)
        for file in planned:
            self.ak(seat, "plan", "add", f"{file} is on main", "--check", f"test -f {file}")
        if planned:
            rig.commit({"parser.py": "parse = str.split\n"}, "the parser")
            self.ak(seat, "plan")
        return seat

    def ak(self, seat, *args):
        done = self.home.ak(*args, env={"AGENTKIT_SESSION": seat.name}, cwd=seat.cwd)
        self.assertEqual(done.code, 0, done.err)

    def asked(self, seat):
        """What the seat's PreToolUse hooks printed as its question card was about to go up."""
        fired = self.hooks.fire("PreToolUse", ASKED, seat=seat.name, pane=seat)
        self.assertEqual(fired.code, 0, fired.err)
        return fired.out

    def test_a_done_plan_with_nothing_from_the_owner_since_refuses_the_card(self):
        printed = json.loads(self.asked(self.seat("done")))
        reason = printed["hookSpecificOutput"].pop("permissionDecisionReason")
        self.assertEqual(printed, {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                          "permissionDecision": "deny"}})
        self.assertIn("last message", reason)

    def test_an_open_line_or_no_plan_lets_the_card_go_up(self):
        for name, planned in (("open-line", ("parser.py", "lexer.py")), ("no-plan", ())):
            with self.subTest(name):
                self.assertEqual(self.asked(self.seat(name, planned)), "")

    def test_the_owner_writing_since_the_plans_last_write_lets_the_card_go_up(self):
        seat = self.seat("owner-wrote")
        # its last line ticked ten minutes ago: Claude stamps the owner's word to the millisecond,
        # which a write a moment before may share
        ago = time.time() - 600
        os.utime(self.home.path / ".agentkit" / "state" / "plan-owner-wrote.md", (ago, ago))
        self.hooks.prompt("8080", seat)
        self.assertEqual(self.asked(seat), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
