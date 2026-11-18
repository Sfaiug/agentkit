"""An ending says its verdict and its reason from one reading of the config.

On 17 Nov 2026 a provider edited between two reads of the config could tell a seat its run
finished `PASS merged` with no PR, or FAIL for a reason only a passing run gives.  Here the
config changes between every two reads: config.toml is a FIFO serving it with the reviewer's
provider as reviewed and as edited in turn, each whole to one reader, the next only once that
reader has closed it (inotify).  Either may be the one the ending reads; both orders run, so
each verdict is read once.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, the ending its seat's look by id prints (`ak run status <id>`).
"""

import ctypes
import fcntl
from itertools import cycle
import json
import os
from pathlib import Path
import select
import struct
import sys
import termios
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home

RUN = "20261117-2300-acme-api"
PR = "https://github.com/acme/widget/pull/1"
IN_CLOSE_NOWRITE = 0x10
READINGS = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}


class AnEndingReadsOneConfig(unittest.TestCase):
    def serve(self, path, texts):
        """Each open of `path` reads the next of `texts`, whole, from a FIFO in its place."""
        libc = ctypes.CDLL(None, use_errno=True)
        queue = libc.inotify_init1(os.O_CLOEXEC)
        self.assertGreaterEqual(queue, 0, os.strerror(ctypes.get_errno()))
        self.addCleanup(os.close, queue)
        path.unlink()
        os.mkfifo(path)
        self.assertGreaterEqual(libc.inotify_add_watch(queue, os.fsencode(path), IN_CLOSE_NOWRITE),
                                0, os.strerror(ctypes.get_errno()))
        stop = threading.Event()

        def unread(fd):
            return struct.unpack("i", fcntl.ioctl(fd, termios.FIONREAD, b"\0" * 4))[0]

        def feed():
            turns = cycle(texts)
            text = next(turns)
            while not stop.is_set():
                fd = os.open(path, os.O_WRONLY)     # waits for a reader
                try:
                    os.write(fd, text)
                    # Held until a reader has it all: the kernel tells a close before the reader
                    # lets go, so this open may have met one that never reads again, and the
                    # next reader joins this pipe while it is held.
                    while unread(fd) and not stop.is_set():
                        time.sleep(0.001)
                except BrokenPipeError:     # met one letting go: the text waits for the next
                    continue
                finally:
                    os.close(fd)
                # its reader's close: a write before it would run on into the read it ends
                while not select.select([queue], [], [], 0.1)[0]:
                    if stop.is_set():
                        return
                os.read(queue, 1 << 16)
                text = next(turns)

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()

        def end():
            stop.set()
            while feeder.is_alive():
                os.close(os.open(path, os.O_RDONLY | os.O_NONBLOCK))   # frees a waiting open
                feeder.join(0.1)

        self.addCleanup(end)

    def told(self, *models):
        """The ending a seat's look prints of a merged run opus built and astra reviewed, while
        config.toml gives `models` in turn, a read each."""
        home = Home()
        self.addCleanup(home.close)
        now = time.time()
        home.write(f".agentkit/runs/{RUN}/run.json", {
            "run_id": RUN, "title": "Acme api", "launched_session": "acme", "state": "pass",
            "verdict": "PASS", "pr": PR, "merged": True, "executor": "opus", "reviewer": "astra",
            "review": {"executor": "opus", "reviewer": "astra", "executor_provider": "anthropic",
                       "reviewer_provider": "openai", "verdict": "PASS", "returncode": 0,
                       "done_when": True},
            "started_at": now - 3600, "finished_at": now - 600, "handback_pending": True})
        texts = [akconfig.write(home, each).read_bytes() for each in models]
        self.serve(home.path / ".agentkit" / "config.toml", texts)
        done = home.ak("run", "status", RUN, env={
            "AGENTKIT_SESSION": "acme", "AK_HOST_READINGS": json.dumps(READINGS), "COLUMNS": "120"})
        self.assertEqual(done.code, 0, done.out + done.err)
        return next(line for line in done.out.splitlines() if line.startswith(f"  run {RUN} "))

    def test_its_verdict_and_reason_come_from_one_config(self):
        reviewed = ["opus", "astra"]
        edited = {"opus": {}, "astra": {"provider": "anthropic"}}   # its reviewer's own provider
        merged = set()
        for models in ((reviewed, edited), (edited, reviewed)):
            line = self.told(*models)
            merged.add(f"run {RUN} finished PASS merged: {PR}." in line)
            self.assertEqual("PASS merged" in line, PR in line, line)
        self.assertEqual(merged, {True, False})     # each order's ending read the other config


if __name__ == "__main__":
    unittest.main()
