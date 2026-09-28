"""Only the heavy suite takes a host-wide turn, counted from live headroom.  Offline.

A temporary HOME, fake run records and short shell commands; readings are injected
through AK_HOST_READINGS, never read off the real machine.  Nothing here touches
the real ~/.agentkit or any real process.
"""

from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, worker

ACME = "/home/fixture/code/acme"
WIDGET = "/home/fixture/code/widget"
SMALL = {"cpus": 8, "load": 0, "free_mb": 4100, "mem_total_mb": 16384}
LARGE = {"cpus": 16, "load": 0, "free_mb": 8200, "mem_total_mb": 32768}
SATURATED = {"cpus": 8, "load": 8, "free_mb": 100, "mem_total_mb": 16384,
             "unit_memory_current_mb": 900, "unit_memory_high_mb": 1000}


class Gate(threading.Thread):
    """One `run_done_when` in a thread of its own, its result or its exception kept."""

    def __init__(self, case, name, repo, cmds, heavy=True, **kw):
        super().__init__(daemon=True)
        self.run_dir = case.record(name, repo)
        self.logs, self.result, self.error = [], None, None
        self.args = (cmds, case.root, self.run_dir / "donewhen.log", set())
        self.kw = {"log": self.logs.append, "run_dir": self.run_dir,
                   "heavy": heavy, **kw}

    def run(self):
        try:
            self.result = run.run_done_when(*self.args, **self.kw)
        except BaseException as exc:      # noqa: BLE001 -- the test reads it
            self.error = exc

    def waited(self):
        return any(line.startswith("done-when: waiting for a heavy suite turn")
                   for line in self.logs)


class HeavySuiteTurns(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".heavy-suite-turns-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        # a worker running this file carries its run's marker, which a killed command
        # would end, and the suites' AK_MAX_RUNS=0, under which no suite takes a turn
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root),
                                                          "AGENTKIT_RUN": "", "AK_RUN_DEPTH": "0"}))
        os.environ.pop("AK_MAX_RUNS", None)
        os.environ.pop("AK_HOST_READINGS", None)
        self.stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        self.stack.enter_context(patch.object(run, "GATE_POLL", 0.05))
        self.stack.enter_context(patch.object(worker, "ACTIVITY_POLL", 0.05))
        config.RUNS.mkdir(parents=True)
        config.HOME.mkdir()
        self.marks = self.root / "marks"
        self.marks.touch()

    def gates(self, count):
        (config.HOME / config.CONFIG_NAME).write_text(f"max_gates = {count}\n")

    def record(self, name, repo):
        """A running run's record, this process its loop, of `repo`."""
        directory = config.RUNS / name
        directory.mkdir()
        run.save_state(directory, {"run_id": name, "title": name, "state": "running",
                                   "verdict": None, "repo": repo, **run.process_owner(),
                                   "started_at": time.time(), "round_summaries": []})
        return directory

    def mark(self, word, seconds=0):
        return f"echo {word} >> {shlex.quote(str(self.marks))}; sleep {seconds}"

    def until(self, check, what, seconds=20):
        deadline = time.monotonic() + seconds
        while not check():
            self.assertLess(time.monotonic(), deadline, f"timed out waiting for {what}")
            time.sleep(0.02)

    def test_a_light_check_runs_while_all_turns_are_taken(self):
        self.gates(1)
        with run.gate_lock(ACME, 0).open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)
            light = Gate(self, "light", ACME, [self.mark("light")], heavy=False)
            light.start()
            light.join(20)
            self.assertIsNone(light.error, light.error)
            self.assertTrue(light.result[0], light.result[1])
            self.assertFalse(light.waited(), light.logs)
            self.assertEqual(run.gate_turn_note(run.read_state(light.run_dir)), "")
        self.assertEqual(self.marks.read_text(), "light\n")

    def test_more_headroom_allows_more_suites(self):
        small = run.derived_heavy_limit(dict(SMALL))
        large = run.derived_heavy_limit(dict(LARGE))
        self.assertEqual(large, 2 * small)
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(SMALL)}):
            limit, pinned = run.heavy_suite_limit()
            self.assertEqual((limit, pinned), (small, False))
            self.assertIn(f"heavy suites: {small} at once (derived)",
                          run.host_status_line())

    def test_a_saturated_slice_waits_yet_one_turn_is_always_free(self):
        self.assertEqual(run.derived_heavy_limit(dict(SATURATED)), 1)
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(SATURATED)}):
            first = Gate(self, "one", ACME, [self.mark("start", 1), self.mark("end")])
            second = Gate(self, "two", WIDGET, [self.mark("queued")])
            first.start()
            self.until(lambda: "start" in self.marks.read_text(),
                       "the first suite to take the one turn")
            second.start()
            gate_log = second.run_dir / "donewhen.log"
            self.until(lambda: gate_log.is_file() and gate_log.read_text() ==
                       "waiting for a heavy suite turn · 1 running\n",
                       "the second suite to wait")
            self.assertEqual(run.gate_turn_note(run.read_state(second.run_dir)),
                             "waiting for a heavy suite turn")
            first.join(20)
            second.join(20)
            self.assertIsNone(first.error, first.error)
            self.assertIsNone(second.error, second.error)
            self.assertFalse(first.waited(), first.logs)
            self.assertTrue(second.waited(), second.logs)
            self.assertEqual(self.marks.read_text(), "start\nend\nqueued\n")

    def test_a_waiter_picks_up_a_changed_limit_on_its_next_poll(self):
        self.gates(1)
        with run.gate_lock(ACME, 0).open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)
            waiter = Gate(self, "waiter", ACME, [self.mark("waiter")])
            waiter.start()
            self.until(lambda: run.gate_turn_note(run.read_state(waiter.run_dir) or {}),
                       "the waiter to mark its wait")
            self.gates(2)
            waiter.join(20)
            self.assertIsNone(waiter.error, waiter.error)
            self.assertTrue(waiter.result[0], waiter.result[1])
            self.assertTrue(waiter.waited(), waiter.logs)
        self.assertEqual(self.marks.read_text(), "waiter\n")

    def test_a_pinned_max_gates_holds(self):
        self.gates(2)
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(SATURATED)}):
            self.assertEqual(run.heavy_suite_limit(), (2, True))
            self.assertIn("heavy suites: 2 at once (pinned)", run.host_status_line())
            first = Gate(self, "one", ACME, [self.mark("one", 1)])
            second = Gate(self, "two", WIDGET, [self.mark("two")])
            first.start()
            self.until(lambda: "one" in self.marks.read_text(),
                       "the first suite to start")
            second.start()
            second.join(20)
            first.join(20)
            self.assertIsNone(first.error, first.error)
            self.assertIsNone(second.error, second.error)
            self.assertFalse(first.waited(), first.logs)
            self.assertFalse(second.waited(), second.logs)
            self.assertEqual(self.marks.read_text(), "one\ntwo\n")


if __name__ == "__main__":
    unittest.main()
