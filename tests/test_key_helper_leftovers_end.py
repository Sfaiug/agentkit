"""What a gone `ak` or helper left running in its session, one tick ends; what a live one left,
or one left in another session, it leaves running.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, beside a
user manager the Home fakes: its control socket listens.  The test plants the leftovers itself,
each a `sleep 600` in a session of its own with the Home's HOME, carrying the mark an `ak` gives
what it starts (tests/test_key_a_command_marks_what_it_starts.py), `AK_OWNER`: `<pid namespace>
<pid> <start> <session> <name>`.  Which real helper is gone by which tick depends on the program's
speed; planted ones are judged by the rule alone.  The whole file runs in one box (`rerun_boxed`):
the tick must see them.
"""

import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import BOXED, Home, rerun_boxed

# `$$` is the sleep's own session: `exec` keeps the pid that `setsid` made its session's.
SLEEP = 'AK_OWNER="$1 $2 $3 ${4:-$$} helper" && export AK_OWNER && exec sleep 600'


@unittest.skipUnless(BOXED, "no bwrap able to box the test here")
class GoneHelperLeftovers(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        # as on a Linux home with systemd, so the tick goes the way it goes there
        manager = socket.socket(socket.AF_UNIX)
        self.addCleanup(manager.close)
        (self.home.root / "run" / "systemd").mkdir()
        manager.bind(str(self.home.root / "run" / "systemd" / "private"))  # XDG_RUNTIME_DIR's
        manager.listen(64)

    def leave(self, start, session=None):
        """A `sleep 600` in a session of its own with the Home's HOME, marked as left in
        `session`, its own unless named, by this process as started at `start`."""
        sleep = subprocess.Popen(
            ["sh", "-c", SLEEP, "sh", str(os.stat("/proc/self/ns/pid").st_ino), str(os.getpid()),
             str(start), str(session or "")], env=self.home.env, start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # reaped before the Home's close, which waits for a killed stray until it is no zombie
        self.addCleanup(sleep.wait)
        self.addCleanup(sleep.kill)
        # marked only once it runs `sleep`: a tick looking earlier sees the shell's environment
        while (sleep.poll() is None
               and Path(f"/proc/{sleep.pid}/cmdline").read_bytes() != b"sleep\x00600\x00"):
            time.sleep(0.01)
        return sleep

    def test_one_tick_ends_only_what_a_gone_helper_left(self):
        # this process's pid with an earlier start: a gone helper's, which this process was given
        start =int(Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19])
        gone, live = self.leave(start - 1), self.leave(start)
        elsewhere = self.leave(start - 1, live.pid)
        done = self.home.ak("watch", timeout=300)
        self.assertEqual(done.code, 0, done.err)
        deadline = time.monotonic() + 60
        while gone.poll() is None:
            self.assertLess(time.monotonic(), deadline, "the tick left a gone helper's leftover")
            time.sleep(0.05)
        self.assertIsNone(live.poll(), "the tick ended what a live helper left")
        self.assertIsNone(elsewhere.poll(), "the tick ended what was left in another session")


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
