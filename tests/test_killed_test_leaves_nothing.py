"""A test killed before its cleanup leaves nothing running.

`Home.close()` ends the tmux servers a test started in its Home and removes it.  A test killed
before then, by a timeout's SIGKILL or a memory cap, leaves that to the Home's reaper, which
wakes as the test's end of their pipe closes; a runner reading the test's output to its end
still reaches it.
"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
from fixtures.akbin import REAL_TMUX, Home, _clear

# A test's process: it makes a Home with a server and a pane, says so and waits to be killed.
MAKER = """import json, sys
sys.path.insert(0, sys.argv[1])
from test_killed_test_leaves_nothing import started
home, pids = started()
print(json.dumps([str(home.root), str(home.tmux_dir), *pids]), flush=True)
sys.stdin.read()
"""


def started():
    """A Home with a tmux server and a pane in it, and the pids of both."""
    home = Home()
    home.tmux("new-session", "-d", "-s", "acme", "sleep 600")
    pids = home.tmux("display-message", "-p", "#{pid} #{pane_pid}").out.split()
    return home, [*map(int, pids)]


def running(*paths):
    """Processes whose command line or environment names one of `paths`: what a Home there
    started, and its reaper."""
    marks = [str(path).encode() for path in paths]
    found = set()
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            said = (entry / "cmdline").read_bytes() + (entry / "environ").read_bytes()
        except OSError:      # gone meanwhile, or not ours to read
            continue
        if any(mark in said for mark in marks):
            found.add(int(entry.name))
    return found


def holding(pids, *pipes):
    """Those of `pids` holding one of `pipes` open."""
    names = {f"pipe:[{os.fstat(pipe.fileno()).st_ino}]" for pipe in pipes}
    found = set()
    for pid in pids:
        try:
            if names & {os.readlink(fd) for fd in Path(f"/proc/{pid}/fd").iterdir()}:
                found.add(pid)
        except OSError:      # gone meanwhile
            continue
    return found


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(Path("/proc/self/environ").exists(), "no /proc to read processes from")
class KilledTest(unittest.TestCase):
    def test_a_test_killed_leaves_no_server_pane_or_home(self):
        maker = subprocess.Popen([sys.executable, "-c", MAKER, str(TESTS)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        line = maker.stdout.readline()
        if not line:
            self.fail(maker.communicate(timeout=60)[1])
        root, tmux_dir, *pids = json.loads(line)
        self.addCleanup(_clear, root, tmux_dir)     # what a failing reaper left
        self.assertLessEqual({*pids}, running(root, tmux_dir))
        # a runner reads a test's output to its end
        self.assertEqual(holding(running(root, tmux_dir), maker.stdout, maker.stderr), set())
        os.kill(maker.pid, signal.SIGKILL)
        maker.communicate(timeout=60)
        deadline = time.monotonic() + 60
        while (running(root, tmux_dir) or Path(root).exists() or Path(tmux_dir).exists()) \
                and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(running(root, tmux_dir), set())
        self.assertFalse(Path(root).exists())
        self.assertFalse(Path(tmux_dir).exists())

    def test_a_home_closed_ends_what_it_started_as_it_returns(self):
        home, pids = started()
        self.addCleanup(home.close)
        self.assertLessEqual({*pids}, running(home.root, home.tmux_dir))
        home.close()
        self.assertEqual(running(home.root, home.tmux_dir), set())
        self.assertFalse(home.root.exists())
        self.assertFalse(home.tmux_dir.exists())


if __name__ == "__main__":
    unittest.main()
