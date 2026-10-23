"""`ak orch list` and `ak run status` print the rows their approved goldens hold.

tests/fixtures/v5z-orch-list.txt and v5z-status.txt are the two listings as the owner approved
them, rendered in-process from fixed state by tests/test_listings_share_design.py.  Here the
same state is made from outside, as records under HOME and the host's readings handed in, and
the program `AK_BIN` names must print the same headers and rows, word for word.  A listing is
what a person reads, so what each column says is the design; how many spaces stand between
columns is left to the layout tests.  Three lines read the host and are not compared: each
run's process and size line (its place under its run is), the slice line, and the heavy-suites
count.

Both seats are records tmux no longer holds, so each age is its record's: a seat tmux holds
reads its age from its session.  The working run is owned by a live process of this test's, as
`ak run` owns its run, or the listing would rightly call it interrupted.
"""

import json
from pathlib import Path
import re
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REPO, Home, owner
from fixtures.akseat import Seat

DAY = 86400
WORKING, UNFINISHED, DONE = ("20260101-0900-ship-the-tally", "20260101-0830-fix-the-parser",
                             "20260101-0700-write-release-notes")
READINGS = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000,
            "slice_cpu_pressure": 12}
PROCESSES = re.compile(r"^\s+\d+ process(es)? · \S+ [KMG]?B$")
HEAVY = re.compile(r"^heavy suites: \d+ at once \(derived\)$")


def golden(name):
    return (REPO / "tests" / "fixtures" / name).read_text().splitlines()


def collapsed(lines):
    """Each line's words, the run of spaces between them read as one; a process line read as its
    place alone."""
    return ["<processes>" if PROCESSES.match(line) else " ".join(line.split())
            for line in lines]


class GoldenListings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        keeper = subprocess.Popen(["sleep", "3600"], start_new_session=True)
        cls.addClassCleanup(lambda: (keeper.kill(), keeper.wait()))
        now = time.time()
        atoll = home.path / "code" / "atoll"
        Seat(home, "atoll", model="fable", cwd=atoll, alive=False,
             record={"workers": ["opus", "astra"], "repo": str(atoll),
                     "created": int(now - 5 * DAY)})
        Seat(home, "scribe", model="astra", alive=False,
             record={"workers": ["spark", "opus", "fable", "astra"], "repo": None,
                     "created": int(now - 3600)})
        workspace = home.path / ".agentkit" / "wt" / WORKING
        workspace.mkdir(parents=True)
        pair = {"executor": "opus", "reviewer": "astra"}
        cls.run_record(WORKING, launched_session="atoll", state="running", rounds=3,
                       title="Ship the tally so every seat row says what the run has done",
                       round_summaries=[{}], started_at=now - 420, finished_at=None,
                       worktree=str(workspace), **pair, **owner(keeper.pid))
        cls.run_record(UNFINISHED, launched_session=None, title="Fix the parser",
                       state="interrupted", rounds=2, round_summaries=[],
                       started_at=now - 3600, finished_at=None, interrupted_at=now - 1800,
                       interruption_reason="Run process exited.", recovery_pending=True,
                       recovery_notified="needs", **pair)
        cls.run_record(DONE, launched_session="atoll", title="Write release notes",
                       state="pass", verdict="PASS", merged=True, rounds=2,
                       round_summaries=[{}, {}], started_at=now - 7200, finished_at=now - 3600,
                       worktree=str(home.path / ".agentkit" / "wt" / "20260101-0700-gone"),
                       **pair)

    @classmethod
    def run_record(cls, run_id, **fields):
        cls.home.write(f".agentkit/runs/{run_id}/run.json", {"run_id": run_id, **fields})

    def listing(self, *args):
        done = self.home.ak(*args, env={"AK_HOST_READINGS": json.dumps(READINGS),
                                        "COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.err)
        return done.out.splitlines()

    def test_orch_list_names_each_seat_as_its_golden_does(self):
        shown, want = self.listing("orch", "list"), golden("v5z-orch-list.txt")
        # the last line is the slice the agents run in, which is the host's to say
        self.assertEqual(len(shown), len(want), "\n".join(shown))
        self.assertEqual(collapsed(shown[:-1]), collapsed(want[:-1]))

    def test_run_status_lists_each_run_as_its_golden_does(self):
        shown, want = self.listing("run", "status"), golden("v5z-status.txt")
        self.assertEqual(collapsed(shown[:1]), collapsed(want[:1]))
        self.assertRegex(shown[1], HEAVY)
        self.assertEqual(collapsed(shown[2:]), collapsed(want[2:]))


if __name__ == "__main__":
    unittest.main()
