"""A run with nothing ahead of it starts at its first poll; of two started together, the second
waits one.

On 31 Oct 2026 fresh runs waited a median 25 to 37 s for a second healthy poll with nothing else
queued.  Readings lag what a run just let in will use, so only a run another went in before
within a poll waits for the next: a lone run goes in at once, and a burst still goes in one a
poll.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py,
on a project from gitrig.py with scripted harnesses from fakeadapter.py; the host readings and
the slot poll are ak's own knobs (AK_HOST_READINGS, AK_SLOT_POLL), the poll the shipped one, far
longer than a launch takes to reach its first.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

POLL = 30
READINGS = {"free_mb": 64000, "mem_total_mb": 128000, "cpus": 8, "load": 0.1,
            "slice_cpu_pressure": 0, "slice_memory_pressure": 0}


def wait(test, what, bound=4 * POLL):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


class LoneRunStartsAtItsFirstPoll(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        del home.env["AK_MAX_RUNS"]     # 0 turns admission off
        home.env.update(AK_SLOT_POLL=str(POLL), AK_HOST_READINGS=json.dumps(READINGS))
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex="pass")
        cls.runs = []
        for title in ("Add retry file", "Bump alpha notes"):
            known = set(taskfile.runs(home))
            # --anyway: the two check the same file, which reads as one change under way
            done = home.ak("run", str(taskfile.write(home, rig.path, title)), "--no-merge",
                           "--bg", "--anyway")
            assert done.code == 0, done.out + done.err
            cls.runs.append((set(taskfile.runs(home)) - known).pop())
        wait(lambda: all(cls.state(run).get("state") not in ("queued", "running")
                         for run in cls.runs), "both runs' end")
        cls.first, cls.second = (cls.state(run) for run in cls.runs)

    @classmethod
    def state(cls, run):
        try:
            return json.loads((run / "run.json").read_text())
        except (OSError, ValueError):
            return {}

    def test_both_runs_pass(self):
        self.assertEqual([self.first.get("verdict"), self.second.get("verdict")], ["PASS"] * 2)

    def test_a_lone_run_starts_at_its_first_poll(self):
        self.assertLess(self.first["slot_started_at"] - self.first["queued_at"], POLL)

    def test_of_two_started_together_the_second_waits_a_poll(self):
        self.assertGreaterEqual(self.second["slot_started_at"] - self.first["slot_started_at"],
                                POLL)


if __name__ == "__main__":
    unittest.main()
