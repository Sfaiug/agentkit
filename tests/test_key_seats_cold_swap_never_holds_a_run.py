"""Seats' swap never holds a run: only the runs slice's swap past a quarter of ak's slice's cap
takes a run's room, and the wait still names how much is in swap.

Sixty seats' cold pages, each within its own seat's cap, held 4.7 G of swap while three runs
went and about 65 waited on a calm host (27 Oct 2026); what ran away on 24 Oct 2026 was runs
and a lander paging their test pieces.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py with scripted harnesses from fakeadapter.py.  Admission reads a fake
cgroup tree (AK_CGROUP_ROOT, AK_CGROUP_FILE); AK_MIN_FREE_MB=0 keeps this machine's own free
memory out.
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


def wait(test, what, bound=90):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


def state(run):
    try:
        return json.loads((run / "run.json").read_text())
    except (OSError, ValueError):
        return {}


class Slice:
    """ak's slice in a fake cgroup tree: 4 GB high, 2 GB of RAM held, idle CPU at 8 cores."""

    def __init__(self, home):
        root = home.root / "cgroup"
        self.dir = root / SERVICE / "agentkit.slice" / "agentkit-test.slice"
        self.runs = self.dir / "agentkit-test-runs.slice"
        self.runs.mkdir(parents=True)
        membership = home.root / "membership"
        membership.write_text(f"0::/{SERVICE}/app.slice/acme.service\n")
        home.env.update(AK_CGROUP_ROOT=str(root), AK_CGROUP_FILE=str(membership))
        (self.runs / "cpu.max").write_text("800000 100000\n")
        for directory in (self.dir, self.runs):
            (directory / "cpu.pressure").write_text(CALM)
            (directory / "cpu.stat").write_text("usage_usec 0\n")
        (self.dir / "memory.pressure").write_text(CALM)
        (self.dir / "memory.high").write_text(str(4096 * MB))
        (self.dir / "memory.current").write_text(str(2048 * MB))
        (self.dir / "memory.stat").write_text("active_file 0\ninactive_file 0\n")

    def swaps(self, *, seats_mb, runs_mb):
        """The slice's swap counts its seats' and its runs'."""
        (self.dir / "memory.swap.current").write_text(str((seats_mb + runs_mb) * MB))
        (self.runs / "memory.swap.current").write_text(str(runs_mb * MB))


class SeatsColdSwapNeverHoldsARun(unittest.TestCase):
    def test_seats_swap_admits_a_run_and_the_runs_swap_past_the_allowance_holds_one(self):
        with Home() as home:
            del home.env["AK_MAX_RUNS"]
            home.env.update(AK_SLOT_POLL="0.5", AK_MIN_FREE_MB="0")
            slice_ = Slice(home)
            rig = Rig(home, "widgets")
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude="work", codex="pass")

            def launch(title):
                known = set(taskfile.runs(home))
                task = taskfile.write(home, rig.path, title)
                done = home.ak("run", str(task), "--no-merge", "--bg", "--anyway")
                self.assertEqual(done.code, 0, done.out + done.err)
                return (set(taskfile.runs(home)) - known).pop()
            # 2 of 4 G of RAM held: seats' 5 G of swap is past the slice's 1 G allowance.
            slice_.swaps(seats_mb=5120, runs_mb=0)
            run = launch("Add retry file")
            wait(lambda: state(run).get("state") not in ("queued", "running"),
                 "the run admitted beside the seats' swap, and its end")
            self.assertEqual(state(run).get("verdict"), "PASS")
            # The runs' 3 G is 2 G past the allowance: that fills the room the RAM left.
            slice_.swaps(seats_mb=0, runs_mb=3072)
            run = launch("Bump alpha notes")
            wait(lambda: state(run).get("slot_wait_kind") == "unit memory",
                 "the run queued on memory")
            time.sleep(2)     # four polls: still held
            held = state(run)
            self.assertEqual(held.get("state"), "queued")
            self.assertIn("waiting for the unit's memory", held.get("slot_wait_reason", ""))
            self.assertIn("3 G in swap", held.get("slot_wait_reason", ""))
            slice_.swaps(seats_mb=3072, runs_mb=1024)
            wait(lambda: state(run).get("state") not in ("queued", "running"),
                 "the run admitted once the runs' swap is back within the allowance")
            self.assertEqual(state(run).get("verdict"), "PASS")


if __name__ == "__main__":
    unittest.main()
