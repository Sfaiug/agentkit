"""Ctrl-C keeps what the destination takes in a second, and nobody else holding it sees a thing.

For Python's `bin/ak`, where a command prints unflushed and is interrupted: `ak fetch` flushes
every line, so tests/test_key_sigint_130.py, which judges any build, cannot see this.  The command
here is the only fake; bin/ak's own entry, exit and interpreter run it.
"""

import fcntl
import os
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home, REPO

LINE = "\nak fetch: interrupted\n"
# `ak fetch` with a command that buffers `size` bytes ending in `kept\n`, its buffer big enough to
# hold them all, closes the descriptor it was given and waits for Ctrl-C.
COMMAND = """
import atexit, io, os, runpy, signal, sys
from pathlib import Path
ak, ready, size = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
sys.path.insert(0, str(Path(ak).parents[1]))
from agentkit import macbridge

def buffers(_argv):
    atexit.register(Path("atexit-ran").touch)
    # both names, as the interpreter's own stdout has
    sys.stdout = sys.__stdout__ = io.TextIOWrapper(
        io.BufferedWriter(io.FileIO(1, "w", closefd=False), size + 1))
    sys.stdout.write("x" * (size - 5) + "kept\\n")
    os.close(ready)
    while True:
        signal.pause()

macbridge.fetch_main = buffers
sys.argv = [ak, "fetch"]
runpy.run_path(ak, run_name="__main__")
"""


class InterruptKeepsOutput(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.err = self.home.root / "err"

    def buffered(self, stdout, size=5, stderr=None):
        """The command, holding its `size` bytes and waiting."""
        ready_read, ready_write = os.pipe()
        with self.err.open("w") as err:
            proc = subprocess.Popen(
                [sys.executable, "-c", COMMAND, str(REPO / "bin/ak"), str(ready_write), str(size)],
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=err if stderr is None else stderr,
                cwd=self.home.path, env=self.home.env, start_new_session=True,
                pass_fds=[ready_write])
        os.close(ready_write)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        os.read(ready_read, 1)
        os.close(ready_read)
        return proc

    def pipe(self, free):
        """A pipe with `free` bytes of room and the rest full, and nobody reading."""
        read_end, write_end = os.pipe()
        self.addCleanup(os.close, read_end)
        self.addCleanup(os.close, write_end)
        os.write(write_end, b"x" * (fcntl.fcntl(write_end, fcntl.F_GETPIPE_SZ) - free))
        return read_end, write_end

    def assert_interrupted(self, proc):
        os.killpg(proc.pid, signal.SIGINT)
        self.assertEqual(proc.wait(timeout=30), 130, self.err.read_text())
        self.assertEqual(self.err.read_text(), LINE)

    def test_a_megabyte_buffered_for_a_file_all_arrives(self):
        size = 1_048_577    # a byte past the most a pipe of ak's own could hold
        out = self.home.root / "out"
        with out.open("wb") as stdout:
            proc = self.buffered(stdout, size)
        self.assertEqual(out.stat().st_size, 0)     # or this flushes nothing
        self.assert_interrupted(proc)
        self.assertEqual(out.read_bytes(), b"x" * (size - 5) + b"kept\n")
        # The exit went on as any other: this one was not cut short.
        self.assertTrue((self.home.path / "atexit-ran").exists())

    def test_a_pipe_with_just_the_room_takes_the_line(self):
        read_end, write_end = self.pipe(free=5)
        self.assert_interrupted(self.buffered(write_end))
        self.assertTrue((self.home.path / "atexit-ran").exists())
        fcntl.fcntl(read_end, fcntl.F_SETFL, os.O_NONBLOCK)
        room = fcntl.fcntl(read_end, fcntl.F_GETPIPE_SZ)
        self.assertEqual(os.read(read_end, room + 1), b"x" * (room - 5) + b"kept\n")

    def test_another_holder_of_the_stdout_sees_nothing(self):
        read_end, write_end = os.pipe()
        self.addCleanup(os.close, read_end)
        self.addCleanup(os.close, write_end)
        flags = fcntl.fcntl(write_end, fcntl.F_GETFL)
        refused, done = [], threading.Event()

        def hold():
            while not done.is_set():
                try:
                    os.write(write_end, b"h" * 512)
                except BlockingIOError as exc:
                    refused.append(exc)

        def read_some():
            """A little at a time, so the holder keeps the pipe full and each write waits."""
            if select.select([read_end], [], [], 0.01)[0]:
                os.read(read_end, 4096)
            time.sleep(0.005)

        holder = threading.Thread(target=hold)
        holder.start()
        try:
            # more than the reader takes in the wait, so ak's flush is in the pipe all through it
            proc = self.buffered(write_end, 1_048_577)
            for _ in range(10):
                read_some()
            os.killpg(proc.pid, signal.SIGINT)
            deadline = time.monotonic() + 30
            while proc.poll() is None and time.monotonic() < deadline:
                read_some()
            self.assertEqual(proc.returncode, 130)
        finally:
            done.set()
            while holder.is_alive():
                read_some()
            holder.join()
        self.assertEqual(refused, [])
        self.assertEqual(fcntl.fcntl(write_end, fcntl.F_GETFL), flags)

    def test_a_stalled_stdout_leaves_the_line_and_a_second_interrupt_changes_nothing(self):
        _read_end, write_end = self.pipe(free=0)
        err_read, err_write = os.pipe()
        proc = self.buffered(write_end, stderr=err_write)
        os.close(err_write)
        os.killpg(proc.pid, signal.SIGINT)
        with os.fdopen(err_read) as err:
            self.assertEqual(err.readline() + err.readline(), LINE)
            os.killpg(proc.pid, signal.SIGINT)
            self.assertEqual(proc.wait(timeout=30), 130)
            self.assertEqual(err.read(), "")

    def test_a_stream_that_refuses_changes_no_exit(self):
        closed_read, closed_write = os.pipe()
        os.close(closed_read)
        self.addCleanup(os.close, closed_write)
        with open("/dev/full", "wb") as full:
            for stdout in (closed_write, full):
                with self.subTest(stdout=stdout):
                    self.assert_interrupted(self.buffered(stdout))
            for stderr in (closed_write, full):
                with self.subTest(stderr=stderr):
                    proc = self.buffered(subprocess.DEVNULL, stderr=stderr)
                    os.killpg(proc.pid, signal.SIGINT)
                    self.assertEqual(proc.wait(timeout=30), 130)


if __name__ == "__main__":
    unittest.main()
