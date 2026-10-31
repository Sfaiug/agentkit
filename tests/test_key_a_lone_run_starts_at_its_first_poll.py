"""A run with nothing ahead of it starts at its first poll.

On 31 Oct 2026 fresh runs waited a median 25 to 37 s for a second healthy poll with nothing else
queued.  Readings lag what a run just let in will use, so only runs let in before it may hold a
run (tests/test_key_a_poll_lets_in_what_the_room_covers.py): a lone run goes in at once.
Black-box: the program `AK_BIN` names a run from outside through tests/fixtures/akbin.py, on a
project from gitrig.py with scripted harnesses from fakeadapter.py; the host readings and the
slot poll are ak's own knobs (AK_HOST_READINGS, AK_SLOT_POLL), the poll the shipped one, far
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
        done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", "--bg")
        assert done.code == 0, done.out + done.err
        run = taskfile.only_run(home)
        wait(lambda: cls.state(run).get("state") not in ("queued", "running"), "the run's end")
        cls.record = cls.state(run)

    @classmethod
    def state(cls, run):
        try:
            return json.loads((run / "run.json").read_text())
        except (OSError, ValueError):
            return {}

    def test_the_run_passes(self):
        self.assertEqual(self.record.get("verdict"), "PASS")

    def test_a_lone_run_starts_at_its_first_poll(self):
        self.assertLess(self.record["slot_started_at"] - self.record["queued_at"], POLL)


if __name__ == "__main__":
    unittest.main()
