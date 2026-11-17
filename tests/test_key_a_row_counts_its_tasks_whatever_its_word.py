"""A seat's row counts its tasks in flight whatever its word.

The owner, 17 Nov 2026: "on the menu screen, we never show the task status but just have the
'x task' indicator", so the count is there whenever a task is, not only after a plan's progress:
after `back 19:20` where the seat is out of usage, `back 19:20 · 1 task`, and alone where its row
said nothing after its word, `2 tasks`.  A row with no task in flight reads as before.
Black-box: `AK_BIN` from a pipe beside akseat.py seats, their plans, waits and `ak run`'s
records; fails on `/bin/false`.
"""

import re
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, owner
from fixtures.akseat import Seat

PLAN = "- [x] done\n" * 3 + "- [ ] next\n" * 5       # 3 of its 8 lines done


@unittest.skipUnless(REAL_TMUX and Path("/proc/stat").exists(), "no tmux, or no /proc")
class EveryWord(unittest.TestCase):
    def test_each_row_with_a_task_in_flight_counts_them(self):
        now = int(time.time())
        with Home() as home:
            loop = subprocess.Popen(["sleep", "600"])
            self.addCleanup(loop.wait)
            self.addCleanup(loop.kill)
            seats = (("fix-api", "claude-permission-pane.txt", 2),     # needs you, no plan
                     ("fix-web", "claude-prompt-pane.txt", 1),         # out of usage
                     ("fix-cli", "claude-working-pane.txt", 1),        # working on its plan
                     ("fix-doc", "claude-permission-pane.txt", 0))     # needs you, nothing going
            for at, (name, screen, tasks) in enumerate(seats):
                Seat(home, name, screen=screen, record={"created": now - 3600 + at})
                for n in range(tasks):
                    home.write(f".agentkit/runs/20261117-090{n}-{name}/run.json",
                               {"state": "running", "step": "executor", "launched_session": name,
                                "started_at": now, **owner(loop.pid)})
            home.write(".agentkit/state/plan-fix-cli.md", PLAN)
            home.write(".agentkit/state/seat-fix-web.json", {"session": "fix-web", "usage_wait": {
                "reason": "anthropic out of usage", "since": now - 600, "until": now + 3600,
                "continue": True}})
            # the list looks at each seat's screen, so the menu's first draw from a pipe reads
            # each word from it, as a terminal's later draws would
            self.assertEqual(home.ak("orch", "list").code, 0)
            done = home.ak(input="\n", env={"COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.err)
        lines = [line.rstrip() for line in done.out.splitlines()]

        def row(name, word):
            """The seat's row in the last draw: the menu draws again once its probe lands."""
            found = [line for line in lines if re.match(rf"[› ] \d+  {name} ", line)]
            self.assertTrue(found, done.out)
            self.assertIn(word, found[-1])
            return found[-1]
        self.assertRegex(row("fix-api", "needs you"), r"needs you +2 tasks$")
        self.assertRegex(row("fix-web", "out of usage"),
                         r"out of usage +back (\w+ )?\d\d:\d\d · 1 task$")
        self.assertRegex(row("fix-cli", "working"), r" [━╸]+─+ 3 of 8 · 1 task$")
        self.assertRegex(row("fix-doc", "needs you"), r"needs you$")


if __name__ == "__main__":
    unittest.main()
