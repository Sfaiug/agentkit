"""A turn's end is looked at by a process already warm (`agentkit/looker.py`).

With the warm server up, the look `hooks/orchestrator-stop.sh` starts once it writes a seat's Stop
down (`watch.start_look`) is the looker's fork, on the runs it read: the word is published with no
run.json of a run at rest opened, nor the runs listed again.  With none up, or a looker silent for
`warm.WAIT`, the same Stop is looked at cold.  A looker older than the install takes no look: it
goes cold, or to the looker of the server the install's starts.

Black-box: Claude's hooks as ak's adapter registers them, fired as Claude fires them
(tests/fixtures/hookdrive.py), at a seat of tests/fixtures/akseat.py; the warm server is the
checkout's beside the program `AK_BIN` names, started as the first popup after an install starts
it.  Each Python of the hook's and of the server's writes down what it opens or lists, by an
audit hook, and the client waits on no clock for a live server (`warm.WAIT`).
"""

import contextlib
import os
from pathlib import Path
import shlex
import signal
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
    if not os.environ.get("LOOK_KEEP_WAIT"):
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
        # Begin a turn outside the pane so no prompt look runs before Stop is judged.
        begun = self.hooks.fire("UserPromptSubmit", {"prompt": "go", "session_id": f"conv-{NAME}"},
                                seat=NAME)
        self.assertEqual(begun.code, 0, begun.err)
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

    def stop(self, keep_wait=False):
        """The turn's Stop, handed to both hooks as Claude fires it, once the hooks have ended and
        the seat's title says `idle`."""
        env = {"LOOK_READS": str(self.reads), **({"LOOK_KEEP_WAIT": "1"} if keep_wait else {})}
        fired = self.hooks.fire("Stop", {"background_tasks": [], "last_assistant_message": "Done."},
                                seat=NAME, pane=self.seat, env=env, finished=True)
        self.assertEqual((fired.code, fired.said), (0, []), fired.err)
        deadline = time.monotonic() + BOUND
        while "idle" not in self.home.tmux("show-options", "-qv", "-t", f"={NAME}:",
                                           "set-titles-string").out:
            self.assertLess(time.monotonic(), deadline, "the word never came")
            time.sleep(0.05)

    def read(self):
        """(pid, its parent, event, what) for each written down."""
        lines = self.reads.read_text().splitlines() if self.reads.exists() else []
        return [(int(pid), int(parent), event, what) for pid, parent, event, what in (
            line.split("\t") for line in lines)]

    def cold(self):
        """What the hook's clients, and any Python they started, opened, once each has ended."""
        clients = {pid for pid, _, event, _ in self.read() if event == "client"}
        self.assertTrue(clients, "the stop hook asked for a look")
        deadline = time.monotonic() + BOUND
        while any(os.path.exists(f"/proc/{client}") for client in clients):
            self.assertLess(time.monotonic(), deadline, "a cold look never ended")
            time.sleep(0.05)
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
        self.stop()
        forks, forked = self.forks(looker)
        self.assertEqual({what for event, what in forked if event == "open"} & self.resting, set())
        # The first fork judged the Stop, on every run read again as a cold judgement reads them
        # (tests/test_key_a_turn_s_end_is_judged_warm.py), and only then started the look.
        judged = next(pid for pid, parent, *_ in self.read() if parent == looker)
        looks = forks - {judged}
        self.assertTrue(looks, "the looker's fork looked")
        self.assertNotIn(("os.scandir", str(self.runs)), {
            (event, what) for pid, _, event, what in self.read() if pid in looks},
            "the runs are listed once")
        self.assertEqual(self.cold(), set(), "nothing looked cold")

    def test_with_no_looker_up_the_turn_s_end_is_looked_at_cold(self):
        self.stop()
        self.assertLessEqual(self.resting, self.cold())

    def test_a_looker_of_an_older_install_is_not_asked(self):
        looker = self.warm()
        stamp = self.home.write(".agentkit/state/installed-at", str(time.time()))
        self.stop()
        self.assertLessEqual({what for _, what in self.forks(looker)[1]}, {str(stamp)})

    def test_a_looker_silent_for_wait_is_passed_by_for_a_cold_look(self):
        looker = self.warm()
        os.kill(looker, signal.SIGSTOP)

        def resume():
            with contextlib.suppress(ProcessLookupError):
                os.kill(looker, signal.SIGCONT)
        self.addCleanup(resume)
        self.stop(keep_wait=True)
        self.assertEqual(self.forks(looker)[0], set())
        self.assertTrue(self.cold(), "the client looked cold once WAIT elapsed")


if __name__ == "__main__":
    unittest.main()
