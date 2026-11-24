"""A dead loop whose worktree goes while the tick waits for its record's lock is not resumed.

The tick reads a dead loop's record, then takes the record's lock to order its resume; cleanup
may take the worktree in between, and a resume ordered then continues into a directory already
gone.  Here the test holds that lock, waits for the tick to queue behind it, removes the
worktree and lets go.  Black-box: a record written by hand where ak keeps it, its loop a process
the test started and reaped, and the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py.
"""

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home, boxable, owner

RUN = "20261124-1200-acme-api"


def waited_on(lock):
    """Whether a process waits for the flock this test holds on `lock`: /proc/locks names a
    file by its device, major and minor in hex, and its inode, as an inode alone is one of
    every filesystem."""
    info = lock.stat()
    held = f" {os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}:{info.st_ino} "
    return any("->" in line and held in line
               for line in Path("/proc/locks").read_text().splitlines())


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class AWorktreeGoneBeforeTheLockIsNotResumed(unittest.TestCase):
    def test_the_tick_orders_no_resume(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        loop = subprocess.Popen(["true"])
        ended = owner(loop.pid)
        loop.wait()
        worktree = home.path / ".agentkit/wt" / RUN
        worktree.mkdir(parents=True)
        receipt = home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "title": "acme api", "state": "running", **ended,
            "started_at": time.time() - 600, "step": "executor", "rounds": 3,
            "worktree": str(worktree)})
        ticks = []
        tick = threading.Thread(target=lambda: ticks.append(home.tick()))
        with receipt.with_name("recovery.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            tick.start()
            deadline = time.monotonic() + 120
            while not waited_on(Path(lock.name)):
                self.assertLess(time.monotonic(), deadline, "the tick never waited for the lock")
                time.sleep(.05)
            worktree.rmdir()
        tick.join()
        done, = ticks
        self.assertEqual(done.code, 0, done.out + done.err)
        deaths = json.loads(receipt.read_text()).get("deaths") or []
        self.assertEqual([death for death in deaths if "resumed_at" in death], [])


if __name__ == "__main__":
    unittest.main()
