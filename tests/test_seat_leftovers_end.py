"""A seat's scope is stopped once its harness has ended, with everything it left running.

The pane runs the seat's real launch under a terminal of its own, as tmux runs it: a stand-in
`systemd-run` runs the command where it is, and the `systemctl` beside it writes down what it
was asked.  The harness is the test's own: it leaves a server running in a session of its own
and ends when told.  No real unit, seat or tmux is touched.
"""

import ctypes
import fcntl
import json
import os
import shlex
import signal
import subprocess
import sys
import termios
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import orch  # noqa: E402

RECORD = '''#!{python}
import json, os, sys
with open(os.environ["AK_TEST_{what}"], "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
'''
# Runs the scope's command in place, as the manager's scope does once the unit is made.
SYSTEMD_RUN = RECORD + '''rest = sys.argv[sys.argv.index("--") + 1:]
os.execvp(rest[0], rest)
'''
HARNESS = [sys.executable, "-c", """if True:
    import os, pathlib, signal, subprocess, sys, time
    here = pathlib.Path(sys.argv[1])
    server = subprocess.Popen(["sleep", "300"], start_new_session=True)
    hangup = int(signal.getsignal(signal.SIGHUP))
    (here / "pids").write_text(f"{os.getpid()} {server.pid} {hangup}")
    while not (here / "end").exists():
        time.sleep(0.05)
"""]
# ptrace's requests and options, as <sys/ptrace.h> numbers them
TRACEME, CONT, DETACH, SETOPTIONS, GETEVENTMSG = 0, 7, 17, 0x4200, 0x4201
TRACE_FORKS, EXITKILL = 2 | 4 | 8, 0x100000


def wait_for(test, done, what):
    deadline = time.monotonic() + 60
    while not done():
        test.assertLess(time.monotonic(), deadline, what)
        time.sleep(0.05)


class SeatScopeEndsWithHarness(Sandbox):
    def setUp(self):
        super().setUp()
        bin_ = self.root / "bin"
        bin_.mkdir()
        for name, text, what in (("systemd-run", SYSTEMD_RUN, "RUNS"),
                                 ("systemctl", RECORD, "STOPS")):
            (bin_ / name).write_text(text.format(python=sys.executable, what=what))
            (bin_ / name).chmod(0o755)
        self.runs, self.stops = self.root / "runs.jsonl", self.root / "stops.jsonl"
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_TEST_RUNS": str(self.runs), "AK_TEST_STOPS": str(self.stops),
            "XDG_RUNTIME_DIR": str(self.root)}))
        self.stack.enter_context(patch.object(orch, "user_manager", lambda: True))
        self.stack.enter_context(patch.object(orch, "seat_scope_run",
                                              lambda: [str(bin_ / "systemd-run")]))
        self.server = None
        self.addCleanup(self.end_server)

    def end_server(self):
        if self.server:
            os.kill(self.server, signal.SIGKILL)

    def pane(self, command):
        """The pane's process, leading a session whose terminal it holds, as tmux starts it."""
        main, side = os.openpty()
        self.addCleanup(os.close, main)

        def take_terminal():
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        proc = subprocess.Popen(shlex.split(command), stdin=side, stdout=side, stderr=side,
                                start_new_session=True, preexec_fn=take_terminal)
        os.close(side)
        return proc

    def stopped(self):
        return ([json.loads(line) for line in self.stops.read_text().splitlines()]
                if self.stops.exists() else [])

    def test_the_scope_is_stopped_once_the_harness_has_ended_and_not_before(self):
        proc = self.pane(orch.seat_command("acme", [*HARNESS, str(self.root)])[0])
        pids = self.root / "pids"
        wait_for(self, pids.exists, "the harness never started")
        harness, self.server, hangup = map(int, pids.read_text().split())
        # the harness keeps the pane's process, and its hangup: the scope's command hands it over
        self.assertEqual((harness, hangup), (proc.pid, signal.SIG_DFL))
        unit, = [word.removeprefix("--unit=") for word in json.loads(self.runs.read_text())
                 if word.startswith("--unit=")]
        self.assertTrue(unit.startswith("agentkit-seat-acme-"), unit)
        time.sleep(2.5)                  # more than one look by the scope's ending
        self.assertEqual(self.stopped(), [], "a scope is stopped under its live harness")

        (self.root / "end").touch()
        self.assertEqual(proc.wait(timeout=60), 0)
        # what it left is still running until the stop that follows takes it with the scope
        os.kill(self.server, 0)
        wait_for(self, self.stopped, "the ended harness's scope was never stopped")
        self.assertEqual(self.stopped(), [["--user", "stop", "--no-block", f"{unit}.scope"]])

    def test_a_harness_ending_at_once_still_has_its_scope_stopped(self):
        # its end hangs up the pane's group, which held a third of the endings still unforked
        for _ in range(20):
            self.assertEqual(self.pane(orch.seat_command("acme", ["true"])[0]).wait(timeout=60), 0)
        wait_for(self, lambda: len(self.stopped()) == 20, "a hangup ended a scope's ending")

    def test_a_pane_closed_as_the_scope_ending_forks_never_starts_its_harness(self):
        # the launch ignores the hangup while it forks the scope's ending: tracing it holds it
        # at that fork while the pane is closed
        libc = ctypes.CDLL(None, use_errno=True)
        libc.ptrace.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
        main, side = os.openpty()

        def traced_terminal():
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
            if libc.ptrace(TRACEME, 0, None, None):
                raise OSError(ctypes.get_errno(), "ptrace")

        try:
            proc = subprocess.Popen(shlex.split(orch.seat_command("acme", ["true"])[0]),
                                    stdin=side, stdout=side, stderr=side,
                                    start_new_session=True, preexec_fn=traced_terminal)
            os.close(side)
            os.waitpid(proc.pid, 0)                     # held at its first exec
            libc.ptrace(SETOPTIONS, proc.pid, None, TRACE_FORKS | EXITKILL)
            passed = 0
            while True:
                libc.ptrace(CONT, proc.pid, None, passed)
                _, status = os.waitpid(proc.pid, 0)
                if not os.WIFSTOPPED(status):
                    break
                passed = 0 if os.WSTOPSIG(status) == signal.SIGTRAP else os.WSTOPSIG(status)
                if status >> 16:                        # a fork, whose child goes untraced
                    child = ctypes.c_ulong()
                    libc.ptrace(GETEVENTMSG, proc.pid, None, ctypes.byref(child))
                    os.waitpid(child.value, 0)
                    libc.ptrace(DETACH, child.value, None, None)
                    if b"trap '' HUP" in Path(f"/proc/{proc.pid}/cmdline").read_bytes():
                        os.close(main)
                        main = None
        finally:
            if main is not None:
                os.close(main)
        self.assertEqual(os.waitstatus_to_exitcode(status), -signal.SIGHUP)
        wait_for(self, self.stopped, "the closed pane's scope was never stopped")


if __name__ == "__main__":
    unittest.main()
