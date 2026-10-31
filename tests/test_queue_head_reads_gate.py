"""Only the run first in line reads the gate: a waiter behind it opens no run.json and takes no
`.slots.lock` on its poll, and moves up as the first is admitted, under the same gate as before.

Offline: a throwaway HOME, fake run records, healthy host readings, and each waiter's own
`gate.wait_for_slot` in a thread that polls only when the test gives it a turn, on a clock the
test moves.
"""

from contextlib import ExitStack
from io import StringIO
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, handback, host, record  # noqa: E402
from fixtures.clock import Clock  # noqa: E402

READINGS = {"free_mb": 4096, "mem_total_mb": 16384, "cpus": 8, "load": 1,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000,
            "slice_cpu_pressure": 5}
GATE_FILES = ("run.json", ".slots.lock")


class QueueHeadReadsGate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-queue-head-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "STATE"):
            stack.enter_context(patch.object(config, name, root / name.lower()))
        config.RUNS.mkdir(parents=True)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "AK_MAX_RUNS": "1", "AK_MIN_FREE_MB": "3072",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0"}))
        os.environ.pop("AK_MAX_LOAD", None)
        stack.enter_context(patch.object(host, "host_readings", return_value=READINGS))
        stack.enter_context(patch.object(handback, "redress_seat"))
        stack.enter_context(patch("sys.stdout", StringIO()))
        self.now = 1000.0
        clock = Clock(self.sleep)
        clock.time = clock.monotonic = lambda: self.now
        stack.enter_context(patch.object(gate, "time", clock))
        stack.enter_context(patch.object(gate, "SLOT_POLL", 30))
        self.opened = []
        real_open = Path.open

        def recording_open(path, *args, **kwargs):
            if path.name in GATE_FILES:
                self.opened.append(path.name)
            return real_open(path, *args, **kwargs)
        stack.enter_context(patch.object(Path, "open", recording_open))
        self.waiters = {}
        self.addCleanup(self.release)

    def sleep(self, _seconds):
        """A waiter's poll interval: it hands the turn back and waits for the test's next one."""
        waiter = self.waiters[threading.current_thread().name]
        waiter["asleep"].set()
        waiter["turn"].wait()
        waiter["turn"].clear()
        if waiter["killed"]:
            raise SystemExit("killed")

    def release(self):
        for waiter in self.waiters.values():
            waiter["killed"] = True
            waiter["turn"].set()
            waiter["thread"].join(60)

    def receipt(self, name, queued_at, word="queued", **extra):
        directory = config.RUNS / name
        directory.mkdir()
        (directory / "log.txt").write_text("launch\n")
        record.save_state(directory, {"run_id": name, "state": word,
                                      "slot_waiting": word == "queued", "queued_at": queued_at,
                                      "started_at": queued_at, "run_depth": 0,
                                      **record.process_owner(), **extra})
        return directory

    def end(self, name):
        directory = config.RUNS / name
        record.save_state(directory, {**record.read_state(directory), "state": "pass"})

    def queue(self, name, queued_at, **extra):
        """A waiter's thread, back asleep after its first poll, the one that queues it."""
        directory = self.receipt(name, queued_at, **extra)
        waiter = self.waiters[name] = {"turn": threading.Event(), "asleep": threading.Event(),
                                       "killed": False, "state": None}

        def wait():
            try:
                waiter["state"] = gate.wait_for_slot(directory)
            except BaseException as exc:  # noqa: BLE001 -- the test reads it
                waiter["error"] = exc
            finally:
                waiter["asleep"].set()
        waiter["thread"] = threading.Thread(target=wait, name=name, daemon=True)
        waiter["thread"].start()
        self.assertTrue(waiter["asleep"].wait(60), f"{name} never queued")

    def poll(self, *names):
        """One poll interval: the clock moves on, then each named waiter polls once, in turn.

        Returns which of run.json and .slots.lock each one opened.
        """
        self.now += gate.SLOT_POLL
        opened = {}
        for name in names:
            waiter = self.waiters[name]
            self.opened.clear()
            waiter["asleep"].clear()
            waiter["turn"].set()
            self.assertTrue(waiter["asleep"].wait(60), f"{name} never finished its poll")
            opened[name] = sorted(set(self.opened))
        return opened

    def admitted(self, name):
        return (self.waiters[name]["state"] or {}).get("state") == "running"

    def note(self, name):
        return gate.slot_note(record.read_state(config.RUNS / name))

    def test_only_the_first_reads_and_each_next_moves_up(self):
        self.receipt("holder", 1, word="running")
        for queued_at, name in enumerate(("fix-api", "fix-ui", "fix-db"), 10):
            self.queue(name, queued_at)
        full = [".slots.lock", "run.json"]
        for _ in range(3):
            self.assertEqual(self.poll("fix-api", "fix-ui", "fix-db"),
                             {"fix-api": full, "fix-ui": [], "fix-db": []})
        self.assertEqual(self.note("fix-db"),
                         "waiting for a slot · limit full (1 running) · 2 ahead")

        # Each freed slot goes to the next in line at its next poll.
        for name, behind, before in (("fix-api", ["fix-ui", "fix-db"], "holder"),
                                     ("fix-ui", ["fix-db"], "fix-api"),
                                     ("fix-db", [], "fix-ui")):
            self.end(before)
            opened = self.poll(name, *behind)
            self.assertTrue(self.admitted(name))
            expected = {name: full, **{other: [] for other in behind}}
            if behind:
                expected[behind[0]] = full    # the next in line moves up at once, and only it
            self.assertEqual(opened, expected)
            if behind:
                self.assertEqual(self.note(behind[-1]),
                                 f"waiting for a slot · limit full (1 running) · "
                                 f"{len(behind) - 1} ahead")
            self.assertRegex((config.RUNS / name / "log.txt").read_text().splitlines()[0],
                             r"^waited \d+ min for a slot \(count\)$")

    def test_a_first_that_stops_polling_hands_its_turn_on_within_two_polls(self):
        self.receipt("holder", 1, word="running")
        for queued_at, name in enumerate(("fix-api", "fix-ui", "fix-db"), 10):
            self.queue(name, queued_at)
        self.poll("fix-api", "fix-ui", "fix-db")
        # `ak run stop` ends the first in line while it sleeps between polls.
        directory = config.RUNS / "fix-api"
        record.save_state(directory, {**record.read_state(directory), "state": "stopped"})
        self.waiters["fix-api"]["killed"] = True
        self.assertEqual(self.poll("fix-api", "fix-ui", "fix-db"),
                         {"fix-api": [], "fix-ui": [], "fix-db": []})
        self.assertEqual(self.poll("fix-ui", "fix-db"),
                         {"fix-ui": [".slots.lock", "run.json"], "fix-db": []})
        self.assertEqual(self.note("fix-db"),
                         "waiting for a slot · limit full (1 running) · 1 ahead")
        self.end("holder")
        self.poll("fix-ui", "fix-db")
        self.assertTrue(self.admitted("fix-ui"))
        self.assertFalse(self.admitted("fix-db"))


if __name__ == "__main__":
    unittest.main()
