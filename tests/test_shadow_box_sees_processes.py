"""tests/shadow.py's box shares the host's process table: a process outside it reads alive there,
by kill(pid, 0) and its /proc/<pid>/stat, and one that has exited reads gone; yet a signal from
inside, or a write to its /proc, leaves it be, while a box's process still ends its own child.
What a run detached is waited out and what it wrote is the run's, and a run its cap cuts off
leaves no process behind.

The file runs whole in the box tests/test_shadow.py runs the shadow in, `OUTER`, whose /var/tmp
of its own holds each run's overlay, and the process outside the shadow's box is the test's."""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import BOXED, Home, _strays, owner, rerun_boxed
import shadow
from test_shadow import OUTER

# Each pid a box's process is handed, as ak reads it there: alive unless kill(pid, 0) finds no
# such process, as host.alive and Go's host.Alive ask, and its start in clock ticks by its
# /proc/<pid>/stat, if it has one.
LOOK = """import os, sys
for pid in map(int, sys.argv[1:]):
    alive, start = True, None
    try:
        os.kill(pid, 0)
    except PermissionError:     # alive, though not this one's to signal
        pass
    except ProcessLookupError:
        alive = False
    try:
        with open(f"/proc/{pid}/stat") as stat:
            start = int(stat.read().rsplit(")", 1)[1].split()[19])
    except FileNotFoundError:
        pass
    print(pid, alive, start)
"""
# A SIGTERM, then a SIGKILL, to the pid a box's process is handed, each sent or the error refusing
# it, then a SIGTERM to a child of its own, by how that child ended.
SIGNAL = """import errno, os, signal, subprocess, sys
for each in (signal.SIGTERM, signal.SIGKILL):
    try:
        os.kill(int(sys.argv[1]), each)
        print(each.name, "sent")
    except OSError as error:
        print(each.name, errno.errorcode[error.errno])
child = subprocess.Popen(["sleep", "600"])
child.send_signal(signal.SIGTERM)
print("child", child.wait())
"""
# A write to the oom_score_adj of the pid a box's process is handed: written, or the error
# refusing it.
SCORE = """import errno, sys
try:
    with open(f"/proc/{sys.argv[1]}/oom_score_adj", "w") as score:
        score.write("1000")
    print("written")
except OSError as error:
    print(errno.errorcode[error.errno])
"""


@unittest.skipUnless(BOXED, "no bwrap able to build a box here")
class ABoxSeesTheHostsProcesses(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.outside = subprocess.Popen(["sleep", "600"], stdin=subprocess.DEVNULL)
        self.addCleanup(self.outside.wait)
        self.addCleanup(self.outside.kill)
        # the shadow's scratch, OUTER's /var/tmp, holds the moment each box's /proc shows, as the
        # shadow's own does
        for name in shadow.MOMENT:
            Path("/var/tmp", name).write_bytes(Path("/proc", name).read_bytes())

    def boxed(self, *argv):
        """What a run of `argv` in the shadow's box did."""
        return shadow.run("boxed", argv[0], argv[1:], self.home.path, Path("/var/tmp"))

    def python(self, script, *pids):
        """What `script` did, run in the box by Python handed the outside process's pid, then
        `pids`."""
        return self.boxed(sys.executable, "-I", "-c", script, *map(str, (self.outside.pid, *pids)))

    def test_a_process_outside_reads_alive_and_one_that_exited_gone(self):
        exited = subprocess.Popen(["true"])
        exited.wait()
        done = self.python(LOOK, exited.pid)
        start = owner(self.outside.pid)["process_identity"]["ticks"]
        self.assertEqual(done["line"], {f"stdout: {self.outside.pid} True {start}",
                                        f"stdout: {exited.pid} False None"}, done)

    def test_signals_to_it_are_refused_and_a_box_ends_its_own_child(self):
        done = self.python(SIGNAL)
        self.assertEqual(done["line"], {"stdout: SIGTERM EPERM", "stdout: SIGKILL EPERM",
                                        "stdout: child -15"}, done)
        self.assertIsNone(self.outside.poll())

    def test_a_write_to_its_proc_is_refused(self):
        score = Path(f"/proc/{self.outside.pid}/oom_score_adj")
        before = score.read_text()
        done = self.python(SCORE)
        self.assertIn(done["line"], ({"stdout: EACCES"}, {"stdout: EROFS"}), done)
        self.assertEqual(score.read_text(), before)

    def test_a_detached_child_is_waited_out_and_what_it_wrote_named(self):
        done = self.boxed("sh", "-c", 'sleep 1 && echo late >"$HOME/late" &')
        self.assertIn("wrote late", done["home"], done)

    def test_a_run_its_cap_cuts_off_leaves_no_process(self):
        with mock.patch.object(shadow, "CAP", 3):
            done = self.boxed("sh", "-c", "sleep 600 &")
        self.assertTrue(done["cut"], done)
        self.assertEqual(_strays(self.home.path), [])


if __name__ == "__main__":
    rerun_boxed(OUTER)
    unittest.main(verbosity=2)
