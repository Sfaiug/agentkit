"""Swap is memory in use, and a minute of memory stalls holds a run as ten seconds of them do.

A slice at its cap swaps rather than frees, and `memory.current` leaves swap out: read alone, it
saw room while the host thrashed.  So the heavy suite turns `ak run status` derives, and a `--bg`
run's admission, count what the slice holds in swap beside its RAM, and say how much is in swap.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a
project from gitrig.py with scripted harnesses from fakeadapter.py.  It reads a fake cgroup tree
(AK_CGROUP_ROOT, AK_CGROUP_FILE) rather than AK_HOST_READINGS, so the slice's files are read by
the program itself; AK_MIN_FREE_MB=0 keeps this machine's own free memory out of it.
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
# Calm over the last ten seconds, stalled over the last minute.
STALLED = "some avg10=0.00 avg60=30.00 avg300=20.00 total=0\nfull avg10=0.00 avg60=9.00 avg300=6.00 total=0\n"


def wait(test, what, bound=90):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.1)


class Slice:
    """ak's slice in a fake cgroup tree: 4 GB high, 2 GB of RAM held, idle CPU at 8 cores."""

    def __init__(self, home):
        root = home.root / "cgroup"
        self.dir = root / SERVICE / "agentkit.slice" / "agentkit-test.slice"
        runs = self.dir / "agentkit-test-runs.slice"
        runs.mkdir(parents=True)
        membership = home.root / "membership"
        membership.write_text(f"0::/{SERVICE}/shell.scope\n")
        home.env.update(AK_CGROUP_ROOT=str(root), AK_CGROUP_FILE=str(membership))
        (runs / "cpu.max").write_text("800000 100000\n")
        for directory in (self.dir, runs):
            (directory / "cpu.pressure").write_text(CALM)
            (directory / "cpu.stat").write_text("usage_usec 0\n")
        (self.dir / "memory.high").write_text(str(4096 * MB))
        (self.dir / "memory.current").write_text(str(2048 * MB))
        (self.dir / "memory.stat").write_text("active_file 0\ninactive_file 0\n")
        self.holds(swap_mb=0)

    def holds(self, *, swap_mb, pressure=CALM):
        (self.dir / "memory.swap.current").write_text(str(swap_mb * MB))
        (self.dir / "memory.pressure").write_text(pressure)


class AdmissionCountsSwap(unittest.TestCase):
    def test_swap_in_the_slice_derives_fewer_heavy_turns_and_shows_on_the_host_line(self):
        with Home() as home:
            slice_ = Slice(home)
            lines = {}
            for swap in (0, 1536):
                slice_.holds(swap_mb=swap)
                done = home.ak("run", "status")
                self.assertEqual(done.code, 0, done.err)
                lines[swap] = done.out.splitlines()[:2]
            turns = {swap: int(heavy.split()[2]) for swap, (_, heavy) in lines.items()}
            self.assertLess(turns[1536], turns[0], lines)
            self.assertIn("1.5 G in swap", lines[1536][0])
            self.assertNotIn("in swap", lines[0][0])

    def test_a_run_waits_while_ram_and_swap_fill_the_slice_or_memory_stalls_for_a_minute(self):
        with Home() as home:
            del home.env["AK_MAX_RUNS"]
            home.env.update(AK_SLOT_POLL="0.5", AK_MIN_FREE_MB="0")
            slice_ = Slice(home)
            rig = Rig(home, "widgets")
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude="work", codex="pass")
            for title, holds, why in (
                    ("Add retry file", {"swap_mb": 1536}, "in swap"),
                    ("Bump alpha notes", {"swap_mb": 0, "pressure": STALLED}, "pressure 30%")):
                with self.subTest(title):
                    slice_.holds(**holds)
                    known = set(taskfile.runs(home))
                    task = taskfile.write(home, rig.path, title)
                    done = home.ak("run", str(task), "--no-merge", "--bg", "--anyway")
                    self.assertEqual(done.code, 0, done.out + done.err)
                    run = (set(taskfile.runs(home)) - known).pop()

                    def state():
                        try:
                            return json.loads((run / "run.json").read_text())
                        except (OSError, ValueError):
                            return {}
                    wait(lambda: state().get("slot_wait_kind") == "unit memory",
                         "the run queued on memory")
                    time.sleep(2)     # four polls: still held
                    held = state()
                    self.assertEqual(held.get("state"), "queued")
                    self.assertIn(why, held.get("slot_wait_reason", ""))
                    slice_.holds(swap_mb=0)
                    wait(lambda: state().get("state") not in ("queued", "running"),
                         "the run admitted once the slice has room, and its end")
                    self.assertEqual(state().get("verdict"), "PASS")


if __name__ == "__main__":
    unittest.main()
