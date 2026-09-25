"""`ak run --first` jumps the admission queue and its repository's gate turns."""

import fcntl
import json
import os
import shlex
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, worker  # noqa: E402

ACME = "/home/fixture/code/acme"
HEALTHY = {"free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
           "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}
FAKE_OWNER = {"pid": 999999, "process_identity": {"boot": "test", "ticks": 1}}


class Gate(threading.Thread):
    """One `run_done_when` in a thread of its own, its result or its exception kept."""

    def __init__(self, case, name, repo, cmds, first=False, **kw):
        super().__init__(daemon=True)
        self.run_dir = case.record(name, repo, first)
        self.logs, self.result, self.error = [], None, None
        self.args = (cmds, case.root, self.run_dir / "donewhen.log", set())
        self.kw = {"log": self.logs.append, "run_dir": self.run_dir, **kw}

    def run(self):
        try:
            self.result = run.run_done_when(*self.args, **self.kw)
        except BaseException as exc:  # noqa: BLE001 -- the test reads it
            self.error = exc


class First(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".first-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root),
                                                          "AGENTKIT_RUN": "",
                                                          "AK_PARENT_RUN": "",
                                                          "AK_RUN_LOG": "",
                                                          "AK_RUN_DEPTH": "0",
                                                          "AGENTKIT_SESSION": ""}))
        os.environ.pop("AK_MAX_RUNS", None)
        config.RUNS.mkdir(parents=True)
        config.HOME.mkdir(exist_ok=True)

    def queued(self, name, queued_at, first=False):
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "title": name, "state": "queued", "verdict": None,
                 "queued_at": queued_at, "started_at": queued_at, "slot_waiting": True,
                 "run_depth": 0, **FAKE_OWNER}
        if first:
            state["first"] = True
        run.save_state(directory, state)
        return directory

    def record(self, name, repo, first=False):
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "title": name, "state": "running", "verdict": None,
                 "repo": repo, **run.process_owner(), "started_at": time.time(),
                 "round_summaries": []}
        if first:
            state["first"] = True
        run.save_state(directory, state)
        return directory

    def mark(self, word, seconds=0):
        return f"echo {word} >> {shlex.quote(str(self.marks))}; sleep {seconds}"

    def until(self, check, what, seconds=20):
        deadline = time.monotonic() + seconds
        while not check():
            self.assertLess(time.monotonic(), deadline, f"timed out waiting for {what}")
            time.sleep(0.02)

    def test_first_admitted_before_earlier_queued(self):
        earlier = self.queued("20250925-1200-earlier", 1000)
        first = self.queued("20250925-1201-first", 2000, first=True)
        with patch.dict(os.environ, {"AK_MAX_RUNS": "1", "AK_MIN_FREE_MB": "3072",
                                      "AK_MAX_LOAD": "8",
                                      "AK_HOST_READINGS": json.dumps(HEALTHY)}), \
                patch.object(run, "process_owner", return_value=dict(FAKE_OWNER)), \
                patch.object(run, "process_active", return_value=True):
            self.assertLess(run.slot_order(run.read_state(first)),
                            run.slot_order(run.read_state(earlier)))
            state = run.read_state(first)
            self.assertFalse(run.claim_slot(state, 1))
            self.assertTrue(run.claim_slot(state, 1))
            self.assertEqual(state["state"], "running")
            behind = run.read_state(earlier)
            self.assertFalse(run.claim_slot(behind, 1))
            self.assertEqual(behind["slot_wait_kind"], "count")

    def test_first_admitted_above_load_but_not_below_memory_floor(self):
        loaded = self.queued("20250925-1200-loaded", 1000, first=True)
        with patch.dict(os.environ, {"AK_MAX_RUNS": "1", "AK_MIN_FREE_MB": "3072",
                                      "AK_MAX_LOAD": "8"}), \
                patch.object(run, "process_owner", return_value=dict(FAKE_OWNER)), \
                patch.object(run, "process_active", return_value=True):
            os.environ["AK_HOST_READINGS"] = json.dumps({**HEALTHY, "load": 41})
            state = run.read_state(loaded)
            self.assertFalse(run.claim_slot(state, 1))
            self.assertTrue(run.claim_slot(state, 1))
            self.assertEqual(state["state"], "running")
            run.save_state(loaded, state)
            thirsty = self.queued("20250925-1201-thirsty", 2000, first=True)
            os.environ["AK_HOST_READINGS"] = json.dumps({**HEALTHY, "free_mb": 1024})
            dry = run.read_state(thirsty)
            self.assertFalse(run.claim_slot(dry, 1))
            self.assertEqual(dry["slot_wait_kind"], "memory")
            self.assertIn("needs 3 G", dry["slot_wait_reason"])

    def test_two_first_runs_keep_fifo(self):
        one = self.queued("20250925-1200-one", 1000, first=True)
        two = self.queued("20250925-1201-two", 2000, first=True)
        with patch.dict(os.environ, {"AK_MAX_RUNS": "1", "AK_MIN_FREE_MB": "3072",
                                      "AK_MAX_LOAD": "8",
                                      "AK_HOST_READINGS": json.dumps(HEALTHY)}), \
                patch.object(run, "process_owner", return_value=dict(FAKE_OWNER)), \
                patch.object(run, "process_active", return_value=True):
            later = run.read_state(two)
            self.assertFalse(run.claim_slot(later, 1))
            self.assertEqual(later["slot_wait_kind"], "count")
            early = run.read_state(one)
            self.assertFalse(run.claim_slot(early, 1))
            self.assertTrue(run.claim_slot(early, 1))
            run.save_state(one, early)
            self.assertFalse(run.claim_slot(later, 1))
            self.assertTrue(run.claim_slot(later, 1))
            self.assertEqual(later["state"], "running")

    def test_first_takes_next_gate_turn_ahead_of_waiters(self):
        self.stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        self.stack.enter_context(patch.object(run, "GATE_POLL", 0.05))
        self.stack.enter_context(patch.object(worker, "ACTIVITY_POLL", 0.05))
        (config.HOME / config.CONFIG_NAME).write_text("max_gates = 1\n")
        self.marks = self.root / "marks"
        self.marks.touch()
        waiter = Gate(self, "waiter", ACME, [self.mark("waiter", 0.5)])
        first = Gate(self, "first-run", ACME, [self.mark("first", 0.2)], first=True)
        holder = run.gate_lock(ACME, 0).open("a")
        self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)
        waiter.start()
        self.until(lambda: run.gate_turn_note(run.read_state(waiter.run_dir) or {}),
                   "the waiter to mark its wait")
        first.start()
        self.until(lambda: run.gate_turn_note(run.read_state(first.run_dir) or {}),
                   "the first run to mark its wait")
        fcntl.flock(holder, fcntl.LOCK_UN)
        waiter.join(20)
        first.join(20)
        self.assertIsNone(waiter.error, waiter.error)
        self.assertIsNone(first.error, first.error)
        self.assertTrue(waiter.result[0] and first.result[0])
        self.assertEqual(self.marks.read_text(), "first\nwaiter\n")

    def test_status_marks_first(self):
        for name, first in (("20250925-1200-first", True), ("20250925-1201-plain", False)):
            directory = config.RUNS / name
            directory.mkdir()
            state = {"run_id": name, "title": name, "state": "running", "verdict": None,
                     "executor": "opus", "reviewer": "astra", "branch": "ak/fix",
                     "rounds": 1, "round_summaries": [], "started_at": time.time() - 60,
                     "reported": False, **FAKE_OWNER}
            if first:
                state["first"] = True
            run.save_state(directory, state)
        with patch.dict(os.environ, {"AK_MAX_RUNS": "1", "AK_MIN_FREE_MB": "3072",
                                      "AK_MAX_LOAD": "8",
                                      "AK_HOST_READINGS": json.dumps(HEALTHY)}), \
                patch.object(run, "process_active", return_value=True):
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(run.cmd_status(["--plain"]), 0)
            self.assertEqual(out.getvalue().count("\n  first\n"), 1)
            details = run.status_details(config.RUNS / "20250925-1200-first",
                                         run.read_state(config.RUNS / "20250925-1200-first"))
            self.assertIn("  first", details)


if __name__ == "__main__":
    unittest.main()
