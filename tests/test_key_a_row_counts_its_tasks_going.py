"""A seat's row says how many tasks it has going, after its plan's count.

The owner, 11 Nov 2026, on a row reading `0 of 1` for hours while six tasks built it: the count
stays the plan's outcomes, as a task mostly builds a plan line, and the row adds the tasks in
flight -- `3 of 8 · 2 tasks`, `3 of 8 · 1 task` -- and reads as before with none.  Black-box:
`AK_BIN` from a pipe beside akseat.py seats, their plans and `ak run`'s records; fails on
`/bin/false`.
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
class WorkingSeats(unittest.TestCase):
    def test_each_row_ends_in_its_plans_count_then_its_tasks_in_flight(self):
        made = int(time.time()) - 3600
        with Home() as home:
            loop = subprocess.Popen(["sleep", "600"])
            self.addCleanup(loop.wait)
            self.addCleanup(loop.kill)
            for at, (name, tasks) in enumerate((("fix-api", 2), ("fix-web", 1), ("fix-cli", 0))):
                Seat(home, name, screen="claude-working-pane.txt", record={"created": made + at})
                home.write(f".agentkit/state/plan-{name}.md", PLAN)
                for n in range(tasks):
                    home.write(f".agentkit/runs/20261111-090{n}-{name}/run.json",
                               {"state": "running", "step": "executor", "launched_session": name,
                                "started_at": time.time(), **owner(loop.pid)})
            # the list looks at each seat's screen, so the menu's first draw from a pipe reads
            # fix-cli working from its spinner, as a terminal's later draws would
            self.assertEqual(home.ak("orch", "list").code, 0)
            done = home.ak(input="\n", env={"COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.err)
        lines = [line.rstrip() for line in done.out.splitlines()]

        def row(name):
            """The seat's row in the last draw: the menu draws again once its probe lands."""
            found = [line for line in lines if re.match(rf"[› ] \d+  {name} ", line)]
            self.assertTrue(found, done.out)
            self.assertIn("● working", found[-1])
            return found[-1]
        self.assertRegex(row("fix-api"), r" [━╸]+─+ 3 of 8 · 2 tasks$")
        self.assertRegex(row("fix-web"), r" [━╸]+─+ 3 of 8 · 1 task$")
        self.assertRegex(row("fix-cli"), r" [━╸]+─+ 3 of 8$")


if __name__ == "__main__":
    unittest.main()
