"""CPU pressure never holds a run from starting; memory still does.

A suite is cut to fill the cores, so the runs slice reads high CPU pressure whenever one runs, and
on 27 Oct 2026 every queue head waited on it while 6 G was free.  A build waits on its model most
of the time, and CPU is shared: a check given less of it only runs slower.  So a run starts
whatever the runs' CPU pressure, and waits, naming memory, while memory has no room.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py with scripted harnesses from fakeadapter.py.  It reads a fake cgroup tree
(AK_CGROUP_ROOT, AK_CGROUP_FILE) rather than AK_HOST_READINGS; AK_MIN_FREE_MB=0 keeps this
machine's own free memory out of it.
"""

import json
import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

MB = 1024 ** 2
SERVICE = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"
CALM = "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
BUSY = "some avg10=90.00 avg60=90.00 avg300=90.00 total=0\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"


def wait(test, what, bound=90):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


class CpuNeverHoldsARun(unittest.TestCase):
    def launch(self, used_mb):
        """A `--bg` run beside a runs slice and a run scope at 90% CPU pressure, ak's slice holding
        `used_mb` of its 4 G."""
        home = Home()
        self.addCleanup(home.close)
        del home.env["AK_MAX_RUNS"]
        home.env.update(AK_SLOT_POLL="0.5", AK_MIN_FREE_MB="0")
        root = home.root / "cgroup"
        slice_ = root / SERVICE / "agentkit.slice" / "agentkit-test.slice"
        runs = slice_ / "agentkit-test-runs.slice"
        scope = runs / "ak-review-1723.scope"
        scope.mkdir(parents=True)
        membership = home.root / "membership"
        membership.write_text(f"0::/{SERVICE}/app.slice/acme.service\n")
        home.env.update(AK_CGROUP_ROOT=str(root), AK_CGROUP_FILE=str(membership))
        (runs / "cpu.max").write_text("800000 100000\n")
        for directory, pressure in ((slice_, BUSY), (runs, BUSY), (scope, BUSY)):
            (directory / "cpu.pressure").write_text(pressure)
            (directory / "cpu.stat").write_text("usage_usec 0\n")
        (slice_ / "memory.pressure").write_text(CALM)
        (slice_ / "memory.high").write_text(str(4096 * MB))
        (slice_ / "memory.current").write_text(str(used_mb * MB))
        (slice_ / "memory.swap.current").write_text("0")
        (slice_ / "memory.stat").write_text("active_file 0\ninactive_file 0\n")
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex="pass")
        done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", "--bg")
        self.assertEqual(done.code, 0, done.out + done.err)
        return taskfile.only_run(home)

    def state(self, run):
        try:
            return json.loads((run / "run.json").read_text())
        except (OSError, ValueError):
            return {}

    def test_a_run_starts_while_the_runs_read_high_cpu_pressure(self):
        run = self.launch(used_mb=1024)
        wait(lambda: self.state(run).get("state") not in ("queued", "running"),
             "the run admitted beside 90% CPU pressure, and its end")
        self.assertEqual(self.state(run).get("verdict"), "PASS")

    def test_a_run_waits_on_memory_whatever_the_cpu_reads(self):
        run = self.launch(used_mb=3584)
        wait(lambda: self.state(run).get("slot_wait_reason"), "the run queued")
        time.sleep(2)     # four polls: still held
        held = self.state(run)
        self.assertEqual(held.get("state"), "queued")
        self.assertIn("memory", held.get("slot_wait_reason", ""))


if __name__ == "__main__":
    unittest.main()
