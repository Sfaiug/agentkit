"""A seat's line shows who builds and who reviews, never what it said nor its tasks' squares.

The owner, 9 Nov 2026: "when the user wants to see what the session said, he can just press on
it"; 17 Nov 2026: "on the menu screen, we never show the task status but just have the 'x task'
indicator".  So a seat that needs the owner opens each model building and reviewing its work,
never its tasks in flight nor its question.  Black-box: `AK_BIN` from a pipe, where every row
opens, beside an akseat.py seat, its question and `ak run`'s records; fails on `/bin/false`.
"""

import re
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, owner
from fixtures.akseat import Seat


@unittest.skipUnless(REAL_TMUX and Path("/proc/stat").exists(), "no tmux, or no /proc")
class ASeatThatNeedsYou(unittest.TestCase):
    def test_its_line_names_its_builder_and_its_reviewer_never_its_tasks_or_its_question(self):
        with Home() as home:
            akconfig.write(home, ["opus", "spark"])
            loop = subprocess.Popen(["sleep", "600"])
            self.addCleanup(loop.wait)
            self.addCleanup(loop.kill)
            Seat(home, "fix-api", record={"workers": ["spark"], "reviewers": ["opus"]})
            home.write(".agentkit/state/notify-fix-api.json",
                       {"session": "fix-api", "kind": "needs", "time": time.time(),
                        "text": "Which branch should the parser land on, main or the release one?"})
            for run, step in (("0900-aaaa", "executor"), ("0901-bbbb", "reviewer")):
                home.write(f".agentkit/runs/20261109-{run}/run.json",
                           {"state": "running", "step": step, "launched_session": "fix-api",
                            "started_at": time.time(), **owner(loop.pid)})
            done = home.ak(input="\n", env={"COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.err)
        lines = [line.rstrip() for line in done.out.splitlines()] + [""]
        at = next((n for n, line in enumerate(lines) if re.match(r"[› ] 1  fix-api ", line)), None)
        self.assertIsNotNone(at, done.out)
        self.assertIn("! needs you", lines[at])
        # under the name: the builder and the orchestrator reviewing, and no task's squares
        self.assertEqual(lines[at + 1], "     build: Spark 1.3 Contributor xhigh   "
                                        "review: Opus 5.5 xhigh")
        self.assertNotIn("Which branch", done.out)


if __name__ == "__main__":
    unittest.main()
