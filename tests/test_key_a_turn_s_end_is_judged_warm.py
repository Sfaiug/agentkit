"""A turn's end is judged by a process already warm (`agentkit/looker.py`).

With the warm server up, hooks/orchestrator-stop.sh hands a seat's Stop to its looker, whose fork
judges it and answers what the hook prints: a Stop with an open plan line and nothing recorded
goes back with the same words as cold, one waiting on a run of the seat's stands, and a run of the
seat's that parked after the looker last read holds the turn.  The hook's Python imports no
agentkit and opens nothing under HOME, and the fork opens no run unchanged since the looker read
it.  With none up, the same answers, cold.

Black-box: Claude's hooks as ak's adapter registers them, fired as Claude fires them
(tests/fixtures/hookdrive.py), at seats of tests/fixtures/akseat.py that tmux lost, so only their
records and plans are there; the warm server is the checkout's beside the program `AK_BIN` names,
started as the first popup after an install starts it.  Each Python of the hook's and of the
server's writes down what it opens or imports, by an audit hook, and the hook's waits on no clock
for the server (`warm.WAIT`).
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

OWES, WAITS, PARKS = "acme", "beta", "gamma"    # an open plan line, a run going, a run parking
GOING, PARKED = "20261113-0100-fix-parser", "20261113-0200-fix-schema"
SPENT = "three rounds spent: split or re-scope the task"
BOUND = 120       # seconds a judgement may take on a loaded host
# `python3 script args`, with `pid<TAB>ppid<TAB>event<TAB>what` to $LOOK_READS for each open
# under HOME, each agentkit module imported and each socket bound, and for the hook's client as
# it starts
AUDIT = r"""
import os, runpy, sys
def _read(event, args, home=os.environ["HOME"] + "/",
          log=os.open(os.environ["LOOK_READS"], os.O_WRONLY | os.O_APPEND | os.O_CREAT)):
    what = (event == "open" and args[0] or event == "socket.bind" and args[1]
            or event == "client" and "-" or event == "import" and str(args[0]))
    if isinstance(what, (str, os.PathLike)) and (
            event in ("socket.bind", "client") or os.fspath(what).startswith(home)
            or event == "import" and what.partition(".")[0] == "agentkit"):
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
class JudgedWarm(unittest.TestCase):
    def setUp(self):
        self.home = home = Home(tmux_log=False)
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        self.hooks = Hooks(home)
        for name in (OWES, WAITS, PARKS):
            Seat(home, name, alive=False, planned=name != PARKS)
            begun = self.hooks.fire("UserPromptSubmit", {"prompt": "go",
                                                         "session_id": f"conv-{name}"}, seat=name)
            self.assertEqual(begun.code, 0, begun.err)
        self.state = home.path / ".agentkit/state"
        ended, written = time.time() - 7200, []
        # many runs of another seat, ended hours ago: enough that the looker spaces its reads of
        # every run seconds apart (`open_runs.SHARE`), so a run at rest that changes is one it
        # has not read
        for number in range(1000):
            run_id = f"20261113-{number:04d}-fix-api"
            written.append(home.write(f".agentkit/runs/{run_id}/run.json", {
                "run_id": run_id, "launched_session": "docs-site", "state": "pass",
                "verdict": "PASS", "finished_at": ended, "handed_back": ended}, ago=7200))
        self.resting = set(map(str, written))
        home.write(f".agentkit/runs/{GOING}/run.json", {
            "run_id": GOING, "launched_session": WAITS, "state": "running",
            "started_at": ended})
        # the run that parks: passed and handed back hours ago, as the looker first reads it
        written.append(home.write(f".agentkit/runs/{PARKED}/run.json", {
            "run_id": PARKED, "launched_session": PARKS, "state": "pass", "verdict": "PASS",
            "started_at": ended - 600, "finished_at": ended, "handed_back": ended}, ago=7200))
        # A read trusts what it parsed of a file only once its stat is a second old: a
        # filesystem's clock can give two writes in one tick the same times.  As a run long over.
        while time.time_ns() - max(run.stat().st_ctime_ns for run in written) <= 1e9:
            time.sleep(0.05)
        self.reads = home.root / "reads"
        home.fake("python3", f"#!/bin/sh\ncase $1 in */agentkit/looker.py|*/agentkit/warm.py) "
                             f"exec {shlex.quote(sys.executable)} -c {shlex.quote(AUDIT)} \"$@\";; "
                             f"esac\nexec {shlex.quote(sys.executable)} \"$@\"\n")

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

    def stop(self, name, said):
        """What the hooks printed back at the seat's Stop, its last words `said`."""
        fired = self.hooks.fire("Stop", {"background_tasks": [], "last_assistant_message": said,
                                         "session_id": f"conv-{name}"},
                                seat=name, env={"LOOK_READS": str(self.reads)})
        self.assertEqual(fired.code, 0, fired.err)
        return fired.said

    def judged(self):
        """The three seats' answers once the parking run parks, still dated hours ago: held by
        that run, back on open work, standing on a run going.  The words sent back on open work."""
        ended = time.time() - 7200
        self.home.write(f".agentkit/runs/{PARKED}/run.json", {
            "run_id": PARKED, "launched_session": PARKS, "state": "exhausted", "error": SPENT,
            "started_at": ended - 600, "finished_at": ended}, ago=7200)
        held = self.stop(PARKS, "All done.")
        self.assertEqual([answer.get("decision") for answer in held], ["block"], held)
        self.assertIn(PARKED, held[0]["reason"])
        self.assertIn(SPENT, held[0]["reason"])
        back = self.stop(OWES, "Here is my recommendation.")
        self.assertEqual([answer.get("decision") for answer in back], ["block"], back)
        self.assertEqual(self.stop(WAITS, f"Waiting on run {GOING}."), [])
        return back

    def read(self):
        """(pid, its parent, event, what) for each written down."""
        lines = self.reads.read_text().splitlines() if self.reads.exists() else []
        return [(int(pid), int(parent), event, what) for pid, parent, event, what in (
            line.split("\t") for line in lines)]

    def clients(self):
        """What the hook's clients, and any Python they started, opened or imported."""
        clients = {pid for pid, _, event, _ in self.read() if event == "client"}
        self.assertTrue(clients, "the stop hook asked for a judgement")
        return {(event, what) for pid, parent, event, what in self.read()
                if event in ("open", "import") and {pid, parent} & clients}

    def forks(self, looker):
        """What each fork of the looker opened, once each has ended."""
        forks = {pid for pid, parent, *_ in self.read() if parent == looker}
        deadline = time.monotonic() + BOUND
        while any(os.path.exists(f"/proc/{fork}") for fork in forks):
            self.assertLess(time.monotonic(), deadline, "a judgement never ended")
            time.sleep(0.05)
        return forks, {(event, what) for pid, _, event, what in self.read() if pid in forks}

    def test_a_looker_up_judges_on_the_runs_it_read(self):
        cold = self.stop(OWES, "Here is my recommendation.")      # the words a cold Stop says
        self.reads.unlink()
        looker = self.warm()
        self.assertEqual(self.judged(), cold)
        forks, forked = self.forks(looker)
        self.assertTrue(forks, "the looker's forks judged")
        self.assertEqual({what for event, what in forked if event == "open"} & self.resting, set())
        self.assertEqual(self.clients(), set(), "nothing judged in the hook's own Python")

    def test_with_no_looker_up_the_turn_s_end_is_judged_cold(self):
        self.judged()
        cold = self.clients()
        self.assertLessEqual({("open", run) for run in self.resting}, cold)
        self.assertIn(("import", "agentkit.turn_end"), cold)


if __name__ == "__main__":
    unittest.main()
