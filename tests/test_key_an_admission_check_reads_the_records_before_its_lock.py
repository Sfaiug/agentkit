"""An admission check opens only the run records that changed, and those before it takes its lock.

On 13 Nov 2026 a host held 6,373 run folders, and every check parsed each one's record with the
slot lock held: one held it 21 s, three more waiting behind it.  A check that waits for a slot
reads the records before it takes the lock, each poll, so under the lock it opens only those
changed in between.  Black-box: the program `AK_BIN` names a run from outside through
tests/fixtures/akbin.py, on a project from gitrig.py with scripted harnesses from fakeadapter.py,
on a host that lets one run in (`max_runs`); a record written beside a live process holds the
slot.  An ended run's record becomes a FIFO, which holds whoever opens it until it is written to,
only once a poll of the waiting run has rewritten the queue, and under the slot lock: what the
launch reads on its way to its first check never meets it, and the waiting run's next check is
the first to open it.
"""

import errno
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, owner
from fixtures.gitrig import Rig

POLL = 30   # the shipped poll: the FIFO is in place long before the waiting run's next one
READINGS = {"free_mb": 64000, "mem_total_mb": 128000, "cpus": 8, "load": 0.1,
            "slice_cpu_pressure": 0, "slice_memory_pressure": 0}
HOLDS, PASSED = "20261113-1100-acme-holds", "20261113-1000-acme-passed"
ENDED = {"run_id": PASSED, "title": "passed", "state": "pass", "verdict": "PASS"}


def until(found, what, bound=4 * POLL):
    """What `found()` returns once it is not None."""
    deadline = time.monotonic() + bound
    while (value := found()) is None:
        if time.monotonic() > deadline:
            raise AssertionError(f"never happened: {what}")
        time.sleep(0.05)
    return value


def stamp(path):
    try:
        info = path.stat()
    except OSError:
        return None
    return info.st_ino, info.st_mtime_ns


def writer(fifo):
    """A writing end of the FIFO once something opens it to read, else None."""
    try:
        return os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as exc:
        if exc.errno != errno.ENXIO:
            raise
        return None


def state(run):
    try:
        return json.loads((run / "run.json").read_text())
    except (OSError, ValueError):
        return {}


class ACheckReadsTheRecordsBeforeItsLock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        del home.env["AK_MAX_RUNS"]     # 0 turns admission off
        home.env.update(AK_SLOT_POLL=str(POLL), AK_HOST_READINGS=json.dumps(READINGS))
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"], settings={"max_runs": 1})
        fakeadapter.install(home, claude="work", codex="pass")
        holder = subprocess.Popen(["sleep", "600"], start_new_session=True)

        def end_holder():
            holder.kill()
            holder.wait()
        cls.addClassCleanup(end_holder)
        now = time.time()
        home.write(f".agentkit/runs/{HOLDS}/run.json", {
            "run_id": HOLDS, "title": "holds", "state": "running", "slot_waiting": False,
            **owner(holder.pid), "run_depth": 0, "started_at": now, "queued_at": now,
            "slot_started_at": now})
        record = home.write(f".agentkit/runs/{PASSED}/run.json", ENDED)
        runs = record.parent.parent
        queue, lock_path = runs / ".slots.queue", runs / ".slots.lock"
        done = home.ak("run", str(taskfile.write(home, rig.path)), "--no-merge", "--bg")
        assert done.code == 0, done.out + done.err
        run = next(run for run in taskfile.runs(home) if run.name not in (HOLDS, PASSED))
        launched = stamp(queue)
        until(lambda: stamp(queue) != launched or None, "a poll of the waiting run")
        fifo = record.with_name("fifo")
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)    # past that poll's check
            os.mkfifo(fifo)
            fifo.replace(record)
        reading = until(lambda: writer(record), "a check opening the FIFO")
        with lock_path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                cls.free = True
            except BlockingIOError:
                cls.free = False
        plain = record.with_name("plain")
        plain.write_text(json.dumps(ENDED))
        plain.replace(record)
        end_holder()
        os.write(reading, json.dumps(ENDED).encode())
        os.close(reading)
        until(lambda: state(run).get("state") not in ("queued", "running") or None,
              "the run's end", 300)
        cls.record = state(run)

    def test_the_check_that_opens_a_record_holds_no_admission_lock(self):
        self.assertTrue(self.free)

    def test_the_waiting_run_goes_in_once_the_slot_frees(self):
        self.assertIn("slot_started_at", self.record)
        self.assertEqual(self.record.get("verdict"), "PASS")


if __name__ == "__main__":
    unittest.main()
