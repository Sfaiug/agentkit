"""A seat at its prompt reads its plan: `done` once every line is ticked, `needs you` while one
is open; a turn running reads `working` whatever the plan says.

The owner sees only what needs them or a finished job.  A seat whose plan has every line ticked
has finished its job, and its row says `done` with the work that got done, so the owner knows
where to look without opening it; a merged run of its own whose project declares no live check
keeps nothing owed.  A seat that stopped with a line still open owes the owner that line, and
its reason names it.  A turn moves without the owner: on the seat's screen, or begun by the
owner's own prompt in a done seat, it reads `working`, never `done`.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, before seats of
tests/fixtures/akseat.py whose prompt hook fires as Claude fires it (tests/fixtures/hookdrive.py);
this test fails against `/bin/false`.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks

PROMPT = "claude-prompt-pane.txt"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class PlanWords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.hooks = Hooks(cls.home)

    def seat(self, name, plan, screen=PROMPT):
        # a minute old: the plan was finished before anything happens in the seat
        self.home.write(f".agentkit/state/plan-{name}.md", plan, ago=60)
        return Seat(self.home, name, screen=screen)

    def why(self, name):
        """`ak orch why NAME`: its first line, and each `label: value` line under it."""
        done = self.home.ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.err)
        first, *rest = done.out.splitlines()
        return first, fields(rest)

    def row(self, name, *flags):
        """The seat's row of `ak orch list`, and the `label: value` lines under it."""
        done = self.home.ak("orch", "list", *flags)
        self.assertEqual(done.code, 0, done.err)
        lines = done.out.splitlines()
        at = next((i for i, line in enumerate(lines) if line.split()[:1] == [name]), None)
        self.assertIsNotNone(at, done.out)
        under = []
        for line in lines[at + 1:]:
            if not line.startswith(" "):
                break
            under.append(line)
        return lines[at], fields(under)

    def test_every_line_ticked_at_its_prompt_is_done_with_the_finished_work(self):
        self.seat("acme", "- [x] Ship the login fix\n")
        first, said = self.why("acme")
        self.assertEqual(first, "acme  done")
        self.assertEqual(said["reason"], "Ship the login fix")
        row, _ = self.row("acme")
        self.assertIn("✓ done", row)

    def test_an_open_line_at_its_prompt_needs_you_and_names_the_line(self):
        self.seat("beta", "- [x] Ship the login fix\n- [ ] Write the docs\n")
        first, said = self.why("beta")
        self.assertEqual(first, "beta  needs you")
        self.assertEqual(said["reason"], "stopped with work open: Write the docs")

    def test_a_turn_on_its_screen_is_working_though_its_plan_is_finished(self):
        self.seat("gamma", "- [x] Ship the login fix\n", screen="claude-working-pane.txt")
        first, _ = self.why("gamma")
        self.assertEqual(first, "gamma  working")
        row, _ = self.row("gamma")
        self.assertIn("working", row)
        self.assertNotIn("✓ done", row)

    def test_a_done_seat_with_its_run_merged_reads_working_once_the_owner_prompts_it(self):
        now = time.time()
        self.home.write(".agentkit/runs/run-dn/run.json",
                        {"state": "pass", "verdict": "PASS", "merged": True,
                         "launched_session": "dn", "started_at": now - 900,
                         "finished_at": now - 120})
        seat = self.seat("dn", "- [x] fix-api is live\n")
        row, said = self.row("dn", "--why")
        self.assertIn("✓ done", row)
        self.assertIn("1 merged", row)
        self.assertEqual(said["reason"], "fix-api is live")
        fired = self.hooks.fire("UserPromptSubmit", {"prompt": "one more thing"}, seat="dn",
                                pane=seat)
        self.assertEqual(fired.code, 0, fired.err)
        row, _ = self.row("dn", "--why")
        self.assertNotIn("✓ done", row)
        self.assertEqual(self.why("dn")[0], "dn  working")


def fields(lines):
    """`label: value` lines, indented under a row, as a mapping."""
    found = {}
    for line in lines:
        label, colon, value = line.strip().partition(":")
        if colon and label.isalpha():
            found.setdefault(label, value.strip())
    return found


if __name__ == "__main__":
    unittest.main()
