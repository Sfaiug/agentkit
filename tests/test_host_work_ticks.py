"""`host.work_ticks(pid)` reads the clock ticks `pid` and the processes whose parent it is have
used: a reading that grows while a child works and stays put while both sleep, or None where
`pid` or /proc is not there.

Offline: real processes of this test's own, read through this host's /proc.
"""

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import host

# Says it is waiting only once its child has said it runs, so neither has startup work left.
PARENT = """
import subprocess, sys
child = subprocess.Popen([sys.executable, "-c", sys.argv[1]], stdout=subprocess.PIPE)
child.stdout.readline()
print(flush=True)
child.wait()
"""
BUSY = "print(flush=True)\nwhile True: pass"
SLEEPING = "import time\nprint(flush=True)\ntime.sleep(600)"


class HostWorkTicks(unittest.TestCase):
    def family(self, child):
        """The pid of a parent waiting for its one child, running `child`."""
        parent = subprocess.Popen([sys.executable, "-c", PARENT, child], stdout=subprocess.PIPE,
                                  start_new_session=True)
        self.addCleanup(parent.wait)
        self.addCleanup(os.killpg, parent.pid, signal.SIGKILL)
        self.addCleanup(parent.stdout.close)
        parent.stdout.readline()
        return parent.pid

    def test_a_child_that_works_grows_its_parents_reading(self):
        pid = self.family(BUSY)
        before = host.work_ticks(pid)
        # A bound, not a duration: a host at load still gives a busy child a tick in it.
        deadline = time.monotonic() + 120
        while (after := host.work_ticks(pid)) == before and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIsNotNone(before)
        self.assertGreater(after, before)

    def test_a_sleeping_parent_and_child_read_the_same_twice(self):
        pid = self.family(SLEEPING)
        first = host.work_ticks(pid)
        time.sleep(0.2)
        self.assertIsNotNone(first)
        self.assertEqual(host.work_ticks(pid), first)

    def test_a_pid_or_a_proc_that_is_not_there_reads_none(self):
        beyond = int(Path("/proc/sys/kernel/pid_max").read_text()) + 1
        self.assertIsNone(host.work_ticks(beyond))
        with tempfile.TemporaryDirectory(prefix="proc-") as tmp:
            self.assertIsNone(host.work_ticks(os.getpid(), Path(tmp) / "absent"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
