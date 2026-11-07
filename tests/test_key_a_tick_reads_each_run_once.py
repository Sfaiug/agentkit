"""A tick opens a run nobody's merge involves no more often for each merged run or ending it weighs.

A tick asks about each merged run's seat: whether the run's ending waits on the seat's other going
runs, or the ending and its live notice ride on one.  Reading every run again for each was 5167
files read 200 times a tick, a quarter of its 8 minutes (30 Oct 2026).  Two Homes, one holding one
merged run of seat `fix-api` and one holding three, are set side by side by how often a tick opens
`bystander`'s run.json, by the kernel's count (inotify), from the tick's start until it and every
process it started have ended.  Black-box: the program `AK_BIN` names ticks from outside through
tests/fixtures/akbin.py, beside tests/fixtures/akseat.py's seat.  The file runs whole in one box
(`rerun_boxed`), where the tick sees the process this test holds for the seat's waiting run: a
tick's own box (`home.tick()`) would hide it, and a tick finding it gone acts on the run.
"""

import ctypes
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import BOXED, REAL_TMUX, Home, owner, rerun_boxed
from fixtures.akseat import Seat

SEAT = "fix-api"
SERVED = "The work is done · written 2026-10-23 09:00"     # akseat's PLAN_LINE, as a run names it
# A close between each two opens, or the kernel counts them as one.
IN_OPEN, IN_CLOSE = 0x20, 0x18
EVENT = struct.Struct("iIII")
BOUND = 120     # seconds what a tick started may outlive it


def run(home, name, **record):
    return home.write(f".agentkit/runs/{name}/run.json", {
        "run_id": name, "title": f"Finished {name}", "launched_session": SEAT, **record})


def processes():
    return {entry for entry in os.listdir("/proc") if entry.isdigit()}


@unittest.skipUnless(REAL_TMUX and BOXED, "no tmux, or no bwrap able to box the test here")
class ATickReadsEachRunOnce(unittest.TestCase):
    def opens(self, merged, ticks=1, **each):
        """How often the last of `ticks` ticks opens `bystander`'s run.json, in a Home whose seat
        has `merged` merged runs, each with `each` on its record."""
        home = Home(tmux_log=False)
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        now = time.time()
        # swept by a tick once it ended (`tree_stopped`), as a run long over is: no tick writes it
        bystander = run(home, "bystander", launched_session="docs-site", state="pass",
                        verdict="PASS", finished_at=now - 86400, handed_back=now - 86400,
                        reported=True, tree_stopped=[None, None])
        Seat(home, SEAT, planned=True, screen="claude-working-pane.txt")
        held = subprocess.Popen(["sleep", "3600"])
        self.addCleanup(held.wait)
        self.addCleanup(held.kill)
        # alive, and serving the seat's one open line: each merged run's ending and live notice
        # ride on the seat's next prompt, and nothing is typed
        run(home, "waits", state="queued", slot_waiting=True, plan_line=SERVED, **owner(held.pid))
        for n in range(merged):
            run(home, f"merged-{n}", state="pass", verdict="PASS", merged=True,
                pr=f"https://github.com/acme/widget/pull/{n + 7}", merge_sha=f"{n + 1:x}" * 40,
                finished_at=now - 600, **each)
        # A build trusts what it parsed of a file whose stat is unchanged only once that stat is a
        # second old: a filesystem's clock can give two writes in one tick the same times.  A tick
        # hands what it trusts to the next (Python's census, `menu.run_records`), so whether the
        # last tick opens the bystander would hang on how soon the first read it.  Older before
        # any tick, as a run's long over is, its count races no such second.
        while time.time_ns() - bystander.stat().st_ctime_ns <= 1e9:
            time.sleep(0.05)
        for _ in range(ticks - 1):
            self.tick(home)
        libc = ctypes.CDLL(None, use_errno=True)
        queue = libc.inotify_init1(os.O_CLOEXEC | os.O_NONBLOCK)
        self.assertGreaterEqual(queue, 0, os.strerror(ctypes.get_errno()))
        self.addCleanup(os.close, queue)
        self.assertGreaterEqual(libc.inotify_add_watch(queue, os.fsencode(bystander.parent),
                                                       IN_OPEN | IN_CLOSE), 0,
                                os.strerror(ctypes.get_errno()))
        self.tick(home)
        events = b""
        while True:
            try:
                events += os.read(queue, 1 << 20)
            except BlockingIOError:
                break
        count, at = 0, 0
        while at < len(events):
            _, mask, _, size = EVENT.unpack_from(events, at)
            name = events[at + EVENT.size:at + EVENT.size + size].rstrip(b"\0")
            count += bool(mask & IN_OPEN and name == b"run.json")
            at += EVENT.size + size
        return count

    def tick(self, home):
        """One tick, waited out with every process it started."""
        before = processes()
        done = home.ak("watch")
        self.assertEqual(done.code, 0, done.out + done.err)
        deadline = time.monotonic() + BOUND
        while left := processes() - before:
            self.assertLess(time.monotonic(), deadline, f"the tick left {sorted(left)} running")
            time.sleep(0.1)

    def test_a_tick_opens_a_run_of_nobodys_no_more_for_each_merge_gone_live(self):
        def opens(merged):
            now = time.time()
            return self.opens(merged, live_at=now - 5, handed_back=now - 300, reported=True)

        alone = opens(1)
        self.assertLessEqual(opens(3), alone)

    def test_a_tick_opens_a_run_of_nobodys_no_more_for_each_ending_owed(self):
        alone = self.opens(1, ticks=2)      # the first marks each ending (`handback.reap`)
        self.assertLessEqual(self.opens(3, ticks=2), alone)


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
