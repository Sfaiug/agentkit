"""A transfer of `ak standby ALIAS` that does nothing for `AK_STANDBY_TIMEOUT` seconds is sent
SIGTERM, then SIGKILL if it stays up, and fails the pass with `rsync did nothing for N seconds`,
whatever it exits with; the next pass with the real rsync ends well and stamps.  A transfer whose
child keeps a processor busy for longer than the timeout is not ended, and passes.  Black-box,
through tests/fixtures/twohomes.py.
"""

import os
from pathlib import Path
import shlex
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM, boxable
from fixtures.twohomes import Machines

REAL = shutil.which("rsync", path=os.pathsep.join(SYSTEM))    # past any fake of it
STATE = ".agentkit/state/watch.json"
STAMP = ".agentkit/tmp/standby/copied"
IDLE_TIMEOUT = 2
# Leaves room for a host at load where a busy child may wait seconds for a processor.
BUSY_TIMEOUT = 6
BUSY_SECONDS = BUSY_TIMEOUT + 3

EXIT_ZERO_ON_TERM = """
import os, pathlib, signal, sys, time
pathlib.Path(sys.argv[1]).write_text(f"{os.getpid()}\\n")
def on_term(*_):
    pathlib.Path(sys.argv[2]).write_text("term")
    sys.exit(0)
signal.signal(signal.SIGTERM, on_term)
time.sleep(600)
"""

IGNORE_TERM = """
import os, pathlib, signal, sys, time
pathlib.Path(sys.argv[1]).write_text(f"{os.getpid()}\\n")
signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(600)
"""

BUSY_CHILD = """
import os, pathlib, subprocess, sys
marker, real, seconds, *args = sys.argv[1:]
path = pathlib.Path(marker)
if not path.exists():
    path.touch()
    subprocess.run([sys.executable, "-c",
                    f"import time; end = time.monotonic() + {float(seconds)}\\n"
                    "while time.monotonic() < end: pass"], check=True)
os.execv(real, [real, *args])
"""


def _python_wrapper(script, *args):
    words = " ".join(shlex.quote(str(arg)) for arg in args)
    return (f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -I -c "
            f'{shlex.quote(script)} {words} "$@"\n')


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AStandbyEndsIdleTransfers(unittest.TestCase):
    def setUp(self):
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        self.home, self.here = home, here = machines
        here.client_of(home)
        home.write(STATE, "the home's state")

    def assertGone(self, pid_file):
        self.assertTrue(pid_file.exists(), "fake rsync did not start")
        pid = int(pid_file.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_a_sleeping_rsync_is_ended_and_the_next_pass_copies(self):
        home, here = self.home, self.here
        pid_file = here.root / "rsync.pid"
        fake = here.fake("rsync",
                         f"#!/bin/sh\nprintf '%s\\n' \"$$\" >{shlex.quote(str(here.at / pid_file.name))}\n"
                         "exec sleep 600\n")
        done = here.ak("standby", home.name, env={"AK_STANDBY_TIMEOUT": str(IDLE_TIMEOUT)})
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(f"the pass from {home.name} failed: rsync did nothing for {IDLE_TIMEOUT} seconds",
                      done.err)
        self.assertFalse((here.path / STAMP).exists())
        self.assertGone(pid_file)
        fake.unlink()
        passed = here.ak("standby", home.name)
        self.assertEqual(passed.code, 0, passed.out + passed.err)
        self.assertEqual((here.path / STAMP).read_text().splitlines()[1], home.name)
        self.assertEqual(here.tree()[STATE], b"the home's state")

    def test_a_sleeping_rsync_that_exits_zero_on_term_still_fails(self):
        home, here = self.home, self.here
        pid_file, got = here.root / "rsync.pid", here.root / "got"
        here.fake("rsync", _python_wrapper(EXIT_ZERO_ON_TERM,
                                           here.at / pid_file.name, here.at / got.name))
        done = here.ak("standby", home.name, env={"AK_STANDBY_TIMEOUT": str(IDLE_TIMEOUT)})
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(f"rsync did nothing for {IDLE_TIMEOUT} seconds", done.err)
        self.assertEqual(got.read_text(), "term")
        self.assertFalse((here.path / STAMP).exists())
        self.assertGone(pid_file)

    def test_a_sleeping_rsync_that_ignores_term_is_killed(self):
        home, here = self.home, self.here
        pid_file = here.root / "rsync.pid"
        here.fake("rsync", _python_wrapper(IGNORE_TERM, here.at / pid_file.name))
        done = here.ak("standby", home.name, env={"AK_STANDBY_TIMEOUT": str(IDLE_TIMEOUT)})
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(f"rsync did nothing for {IDLE_TIMEOUT} seconds", done.err)
        self.assertFalse((here.path / STAMP).exists())
        self.assertGone(pid_file)

    def test_a_transfer_whose_child_keeps_working_passes(self):
        home, here = self.home, self.here
        marker = here.root / "worked"
        here.fake("rsync", _python_wrapper(BUSY_CHILD,
                                           here.at / marker.name, REAL, BUSY_SECONDS))
        done = here.ak("standby", home.name, env={"AK_STANDBY_TIMEOUT": str(BUSY_TIMEOUT)})
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(marker.exists(), "fake rsync did not run")
        self.assertEqual((here.path / STAMP).read_text().splitlines()[1], home.name)
        self.assertEqual(here.tree()[STATE], b"the home's state")


if __name__ == "__main__":
    unittest.main(verbosity=2)
