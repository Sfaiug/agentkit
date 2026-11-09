"""A seat's line shows who builds, who reviews and each task in flight, never what it said.

The owner, 9 Nov 2026: "when the user wants to see what the session said, he can just press on
it, I think only models and the current runs should be shown."  So the line under a seat that
needs the owner is the line under any seat: each model building ⚒ and reviewing ◎ its work, then
each task in flight as three squares, build, review and land, filled as far as it has come --
never its question, which opening the seat shows.  From a pipe nothing is highlighted, so every
row opens its line.  Black-box: the program `AK_BIN` names runs from a pipe beside
tests/fixtures/akseat.py's seats, a question the seat sent and run records like those `ak run`
writes, and this test fails against `/bin/false`.
"""

import re
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

QUESTION = "Which branch should the parser land on, main or the release one?"
LIVE = Path("/proc/sys/kernel/random/boot_id")


def alive(pid):
    """A run record's say that its loop is process `pid`, as `ak run` fingerprints it."""
    ticks = int(Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[19])
    return {"pid": pid, "started_at": time.time(),
            "process_identity": {"boot": LIVE.read_text().strip(), "ticks": ticks}}


@unittest.skipUnless(REAL_TMUX and LIVE.exists(), "no tmux, or no /proc to fingerprint a run")
class ASeatThatNeedsYou(unittest.TestCase):
    def test_its_line_names_its_builder_its_reviewer_and_its_two_tasks_never_its_question(self):
        with Home() as home:
            akconfig.write(home, ["opus", "spark"])
            loop = subprocess.Popen(["sleep", "600"])
            self.addCleanup(loop.wait)
            self.addCleanup(loop.kill)
            Seat(home, "fix-api", record={"workers": ["spark"], "reviewers": ["opus"]})
            home.write(".agentkit/state/notify-fix-api.json",
                       {"session": "fix-api", "kind": "needs", "text": QUESTION,
                        "time": time.time()})
            for run, step in (("0900-aaaa", "executor"), ("0901-bbbb", "reviewer")):
                home.write(f".agentkit/runs/20261109-{run}/run.json",
                           {"state": "running", "step": step, "launched_session": "fix-api",
                            **alive(loop.pid)})
            done = home.ak(input="\n", env={"COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.err)
        lines = [line.rstrip() for line in done.out.splitlines()] + [""]
        at = next((n for n, line in enumerate(lines) if re.match(r"[› ] 1  fix-api ", line)), None)
        self.assertIsNotNone(at, done.out)
        self.assertIn("! needs you", lines[at])
        # under the name: the builder, the reviewer, then one building and one in review
        self.assertEqual(lines[at + 1], "     muse-spark-1.3-contributor xhigh ⚒   "
                                        "Opus 5.5 xhigh ◎   ■□□  ■■□")
        self.assertNotIn("Which branch", done.out)


if __name__ == "__main__":
    unittest.main()
