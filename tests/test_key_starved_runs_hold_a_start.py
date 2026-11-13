"""A run waits for its slot while the runs building wait for a CPU longer than they run on one.

On 12 Nov 2026, 54 runs building on 18 cores stood still for want of a CPU three to five times
as long as they ran on one, and a line's check beside them took three hours for a pass of 17 to
48 minutes: more runs added only waiting.  So while the CPU time the runs building stood still
for sums to more than the time they ran, the first run in line waits, naming the runs' CPU, and
a run launched `--first` still goes; while they run longer than they wait, a run starts.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py with scripted harnesses from fakeadapter.py, the host readings and the
two sums, in cores, injected (AK_HOST_READINGS) with memory free.
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

FREE = {"free_mb": 64000, "mem_total_mb": 128000, "cpus": 8, "load": 0.1,
        "slice_cpu_pressure": 0, "slice_memory_pressure": 0}
WAITING = ("queued", "running")


def wait(test, what, bound=90):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


class StarvedRunsHoldAStart(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        del self.home.env["AK_MAX_RUNS"]
        self.home.env["AK_SLOT_POLL"] = "0.5"
        self.rig = Rig(self.home, "widgets")
        akconfig.write(self.home, ["opus", "astra"])
        fakeadapter.install(self.home, claude="work", codex="pass")

    def launch(self, title, *flags):
        """A `--bg` run's directory."""
        known = set(taskfile.runs(self.home))
        # --anyway: both check the same file, which reads as one change under way
        done = self.home.ak("run", str(taskfile.write(self.home, self.rig.path, title)),
                            "--no-merge", "--bg", "--anyway", *flags)
        self.assertEqual(done.code, 0, done.out + done.err)
        return (set(taskfile.runs(self.home)) - known).pop()

    def state(self, run):
        try:
            return json.loads((run / "run.json").read_text())
        except (OSError, ValueError):
            return {}

    def building(self, used, waited):
        self.home.env["AK_HOST_READINGS"] = json.dumps(
            {**FREE, "building_cpu_used": used, "building_cpu_waited": waited})

    def test_a_run_waits_while_the_runs_wait_longer_than_they_run_and_first_goes(self):
        self.building(used=2, waited=6)
        queued = self.launch("Add retry file")
        wait(lambda: self.state(queued).get("slot_wait_reason"), "the run queued")
        time.sleep(2)     # four polls: still held
        held = self.state(queued)
        self.assertEqual(held.get("state"), "queued")
        self.assertIn("the runs' CPU", held.get("slot_wait_reason", ""))
        first = self.launch("Write beta log", "--first")
        wait(lambda: self.state(first).get("state") not in WAITING, "the --first run's end")
        self.assertEqual(self.state(first).get("verdict"), "PASS")
        self.assertEqual(self.state(queued).get("state"), "queued")

    def test_a_run_starts_while_the_runs_run_longer_than_they_wait(self):
        self.building(used=6, waited=2)
        run = self.launch("Add retry file")
        wait(lambda: self.state(run).get("state") not in WAITING, "the run admitted, and its end")
        self.assertEqual(self.state(run).get("verdict"), "PASS")


if __name__ == "__main__":
    unittest.main()
