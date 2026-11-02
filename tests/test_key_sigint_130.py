"""Ctrl-C during a command that is waiting ends it with exit 130, one word, and nothing left behind.

A person or a harness interrupts `ak fetch` while it waits on the Mac for a file.  The shell and
any script around it read the interrupt from the exit status, 130 as for any program a SIGINT
ended; the person reads one line saying the command was interrupted, never a traceback; and the
request the command had queued for the Mac is taken back, so the Mac does not send a file
nobody waits for.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, signalled as a terminal's Ctrl-C signals its foreground process group,
and this test fails against `/bin/false`.
"""

import fcntl
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, Home

MAC_FILE = "/Users/acme/report.pdf"   # a path on the Mac, which this host does not have
# Where the kernel holds a thread whose write to a full pipe or local socket waits for room.
STALLED = {"pipe_write", "sock_alloc_send_pskb", "unix_stream_sendmsg"}


def stalled_writing(pid):
    """Whether any thread of the process waits in a write."""
    for wchan in Path(f"/proc/{pid}/task").glob("*/wchan"):
        try:
            if wchan.read_text().strip() in STALLED:
                return True
        except OSError:     # the thread ended meanwhile
            pass
    return False


class SigintExits130(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.bridge = self.home.path / ".agentkit" / "macbridge"

    def queued(self, proc, bound=30):
        """The requests the command queued for the Mac, once there is one; a dot file is one
        still being written."""
        requests = self.bridge / "requests"
        deadline = time.monotonic() + bound
        while True:
            queued = [path for path in requests.glob("*") if not path.name.startswith(".")]
            if queued:
                return queued
            if proc.poll() is not None or time.monotonic() > deadline:
                raise AssertionError(f"ak fetch queued no request (exit {proc.poll()})")
            time.sleep(0.05)

    def interrupt(self, *args):
        """Start `ak fetch`, Ctrl-C it once it waits on the Mac, and return its exit and its
        output."""
        # Long enough that the wait is still on when the interrupt comes.
        proc = self.home.spawn("fetch", *args, env={"AK_FETCH_TIMEOUT": "600"})
        self.assertEqual(len(self.queued(proc)), 1)
        os.killpg(proc.pid, signal.SIGINT)
        code = proc.wait(timeout=30)
        # the Home's first spawn, as each case has a Home of its own
        return (code, self.home.log("spawn-1.out").read_text(),
                self.home.log("spawn-1.err").read_text())

    def test_an_interrupted_wait_exits_130_saying_only_that(self):
        code, out, err = self.interrupt(MAC_FILE)
        self.assertEqual(code, 130, err)
        self.assertEqual(out, "")
        self.assertEqual(err, "\nak fetch: interrupted\n")

    def test_the_request_the_mac_was_asked_for_is_taken_back(self):
        code, _out, err = self.interrupt(MAC_FILE)
        self.assertEqual(code, 130, err)
        self.assertEqual(list((self.bridge / "requests").iterdir()), [])
        self.assertEqual(list((self.bridge / "inbox").iterdir()), [])

    def test_a_file_already_printed_stays_printed(self):
        here = self.home.write("notes.txt", "kept\n")
        code, out, err = self.interrupt(str(here), MAC_FILE)
        self.assertEqual(code, 130, err)
        self.assertEqual(out, f"{here}\n")
        self.assertEqual(err, "\nak fetch: interrupted\n")

    def full_pipe(self):
        read_end, write_end = os.pipe()
        self.addCleanup(os.close, read_end)
        self.addCleanup(os.close, write_end)
        os.write(write_end, b"x" * fcntl.fcntl(write_end, fcntl.F_GETPIPE_SZ))
        return write_end

    def interrupt_stalled(self, stdout, stderr=subprocess.DEVNULL):
        """Start `ak fetch` of a file here and Ctrl-C it, only once its write to `stdout` has
        stalled: sooner, nothing is in flight and the case tests nothing."""
        here = self.home.write("notes.txt", "kept\n")
        proc = subprocess.Popen([AK, "fetch", str(here)], stdin=subprocess.DEVNULL,
                                stdout=stdout, stderr=stderr, cwd=self.home.path,
                                env=self.home.env, start_new_session=True)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        deadline = time.monotonic() + 30
        while not stalled_writing(proc.pid):
            if proc.poll() is not None or time.monotonic() > deadline:
                raise AssertionError(f"ak fetch never stalled writing (exit {proc.poll()})")
            time.sleep(0.01)
        os.killpg(proc.pid, signal.SIGINT)
        self.assertIn(proc.wait(timeout=30), (130, -signal.SIGINT))

    def test_a_full_pipe_nobody_reads_does_not_outlast_the_interrupt(self):
        self.interrupt_stalled(self.full_pipe())

    def test_a_full_socket_nobody_reads_does_not_outlast_the_interrupt(self):
        near, far = socket.socketpair()
        self.addCleanup(near.close)
        self.addCleanup(far.close)
        with self.assertRaises(BlockingIOError):
            while True:
                near.send(b"x" * 4096, socket.MSG_DONTWAIT)
        self.interrupt_stalled(near)

    def test_a_full_stderr_as_well_does_not_outlast_the_interrupt(self):
        self.interrupt_stalled(self.full_pipe(), stderr=self.full_pipe())


if __name__ == "__main__":
    unittest.main()
