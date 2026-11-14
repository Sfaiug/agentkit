"""A seat's event is looked at by a process already warm (`agentkit/looker.py`).

With the warm server up, the hook's look is its looker's fork, on the runs it read: the word is
published with no run.json of a run at rest opened, nor the runs listed again.  With none up, the
same event is looked at cold, reading every run.  A looker older than the install takes no event:
it goes cold, or to the looker of the server the install's starts.

Black-box: Claude's hooks as ak's adapter registers them, fired as Claude fires them
(tests/fixtures/hookdrive.py), at a seat of tests/fixtures/akseat.py; the warm server is the
checkout's beside the program `AK_BIN` names, started as the first popup after an install starts
it.  Each Python of the hook's and of the server's writes down what it opens or lists, by an
audit hook, and the hook's waits on no clock for the server (`warm.WAIT`).
"""

import os
from pathlib import Path
import shlex
import socket
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.hookdrive import ROOT, Hooks

NAME = "acme"
BOUND = 120       # seconds a look may take on a loaded host
# `python3 script args`, with `pid<TAB>ppid<TAB>event<TAB>what` to $LOOK_READS for each open or
# listing under HOME and each socket bound, and for the hook's client as it starts
AUDIT = r"""
import os, runpy, sys
def _read(event, args, home=os.environ["HOME"] + "/",
          log=os.open(os.environ["LOOK_READS"], os.O_WRONLY | os.O_APPEND | os.O_CREAT)):
    what = (event in ("open", "os.scandir") and args[0] or event == "socket.bind" and args[1]
            or event == "client" and "-")
    if isinstance(what, (str, os.PathLike)) and (
            event in ("socket.bind", "client") or os.fspath(what).startswith(home)):
        os.write(log, f"{os.getpid()}\t{os.getppid()}\t{event}\t{os.fspath(what)}\n".encode())
sys.addaudithook(_read)
del sys.argv[0]
sys.path.insert(0, os.path.dirname(sys.argv[0]))
if sys.argv[0].endswith("looker.py"):
    sys.audit("client")
    __import__("warm").WAIT = None
runpy.run_path(sys.argv[0], run_name="__main__")
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Warm(unittest.TestCase):
    def setUp(self):
        self.home = home = Home(tmux_log=False)
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        self.hooks = Hooks(home)
        self.seat = Seat(home, NAME)
        self.reads = home.root / "reads"
        home.fake("python3", f"#!/bin/sh\ncase $1 in */agentkit/looker.py|*/agentkit/warm.py) "
                             f"exec {shlex.quote(sys.executable)} -c {shlex.quote(AUDIT)} \"$@\";; "
                             f"esac\nexec {shlex.quote(sys.executable)} \"$@\"\n")
        self.state, self.runs = home.path / ".agentkit/state", home.path / ".agentkit/runs"
        ended, written = time.time() - 7200, []
        for number in range(40):            # many runs of another seat, ended hours ago
            run_id = f"20261113-{number:04d}-fix-api"
            written.append(home.write(f".agentkit/runs/{run_id}/run.json", {
                "run_id": run_id, "launched_session": "docs-site", "state": "pass",
                "verdict": "PASS", "finished_at": ended, "handed_back": ended}, ago=7200))
        self.resting = set(map(str, written))
        # A read trusts what it parsed of a file only once its stat is a second old: a
        # filesystem's clock can give two writes in one tick the same times.  As a run long over.
        while time.time_ns() - max(run.stat().st_ctime_ns for run in written) <= 1e9:
            time.sleep(0.05)

    def warm(self):
        """The warm server up in this Home, its looker listening: the looker's pid."""
        done = self.home.run("sh", "-c", 'python3 "$0" serve </dev/null >/dev/null 2>&1 &',
                             str(ROOT / "agentkit" / "warm.py"), env={"LOOK_READS": str(self.reads)})
        self.assertEqual(done.code, 0, done.err)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.state)                # a socket by its name: a Home's path may be past 108 bytes
        deadline = time.monotonic() + BOUND
        while True:
            bound = [(pid, what) for pid, _, event, what in self.read()
                     if event == "socket.bind" and what.endswith(".look")]
            with socket.socket(socket.AF_UNIX) as probe:    # refused until it listens
                if bound and probe.connect_ex(bound[0][1]) == 0:
                    return bound[0][0]
            self.assertLess(time.monotonic(), deadline, "no looker came up")
            time.sleep(0.05)

    def prompt(self):
        """The owner's prompt, as the seat's harness tells its hook, once the hook and all it
        started have ended and the seat's title says `working`."""
        fired = self.hooks.fire("UserPromptSubmit", {"prompt": "go", "session_id": f"conv-{NAME}"},
                                seat=NAME, pane=self.seat, env={"LOOK_READS": str(self.reads)},
                                finished=True)
        self.assertEqual(fired.code, 0, fired.err)
        deadline = time.monotonic() + BOUND
        while "working" not in self.home.tmux("show-options", "-qv", "-t", f"={NAME}:",
                                              "set-titles-string").out:
            self.assertLess(time.monotonic(), deadline, "the word never came")
            time.sleep(0.05)

    def read(self):
        """(pid, its parent, event, what) for each written down."""
        lines = self.reads.read_text().splitlines() if self.reads.exists() else []
        return [(int(pid), int(parent), event, what) for pid, parent, event, what in (
            line.split("\t") for line in lines)]

    def cold(self):
        """What the hook's clients, and any Python they started, opened."""
        clients = {pid for pid, _, event, _ in self.read() if event == "client"}
        self.assertTrue(clients, "the hook asked for a look")
        return {what for pid, parent, event, what in self.read()
                if event == "open" and {pid, parent} & clients}

    def forks(self, looker):
        """What each fork of the looker opened or listed, once each has ended."""
        forks = {pid for pid, parent, *_ in self.read() if parent == looker}
        deadline = time.monotonic() + BOUND
        while any(os.path.exists(f"/proc/{fork}") for fork in forks):
            self.assertLess(time.monotonic(), deadline, "a look never ended")
            time.sleep(0.05)
        return forks, {(event, what) for pid, _, event, what in self.read() if pid in forks}

    def test_a_looker_up_looks_on_the_runs_it_read(self):
        looker = self.warm()
        self.prompt()
        forks, forked = self.forks(looker)
        self.assertTrue(forks, "the looker's fork looked")
        self.assertEqual({what for event, what in forked if event == "open"} & self.resting, set())
        self.assertNotIn(("os.scandir", str(self.runs)), forked, "the runs are listed once")
        self.assertEqual(self.cold(), set(), "nothing looked cold")

    def test_with_no_looker_up_the_event_is_looked_at_cold(self):
        self.prompt()
        self.assertLessEqual(self.resting, self.cold())

    def test_a_looker_of_an_older_install_is_not_asked(self):
        looker = self.warm()
        stamp = self.home.write(".agentkit/state/installed-at", str(time.time()))
        self.prompt()
        self.assertLessEqual({what for _, what in self.forks(looker)[1]}, {str(stamp)})


if __name__ == "__main__":
    unittest.main()
