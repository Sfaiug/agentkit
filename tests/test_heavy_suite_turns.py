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
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import gate, host, config, run, worker
from agentkit import record as run_record

ACME = "/home/fixture/code/acme"
WIDGET = "/home/fixture/code/widget"
SMALL = {"cpus": 8, "load": 0, "free_mb": 4100, "mem_total_mb": 16384,
         "slice_cpu_quota": 8, "slice_cpu_used": 0,
         "slice_memory_used_mb": 0, "slice_memory_high_mb": 4100}
LARGE = {"cpus": 16, "load": 0, "free_mb": 8200, "mem_total_mb": 32768,
         "slice_cpu_quota": 16, "slice_cpu_used": 0,
         "slice_memory_used_mb": 0, "slice_memory_high_mb": 8200}
SATURATED = {"cpus": 16, "load": 0, "free_mb": 8200, "mem_total_mb": 32768,
             "slice_cpu_quota": 1, "slice_cpu_used": 1,
             "slice_memory_used_mb": 900, "slice_memory_high_mb": 1000}


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
            self.result = gate.run_done_when(*self.args, **self.kw)
        except BaseException as exc:      # noqa: BLE001 -- the test reads it
            self.error = exc

    def waited(self):
        return any(line.startswith("done-when: waiting for a heavy suite turn")
                   for line in self.logs)


class HeavySuiteTurns(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-heavy-suite-turns-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        # a worker running this file carries its run's marker, which a killed command
        # would end, and the suites' AK_MAX_RUNS=0, under which no suite takes a turn; the
        # line's checker runs it at the top CPU weight, where a turn samples the real slice
        # beside the injected readings: in no cgroup it samples none
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root),
                                                          "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
                                                          "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
                                                          "AK_CGROUP_FILE": str(self.root / "no-cgroup")}))
        os.environ.pop("AK_MAX_RUNS", None)
        os.environ.pop("AK_HOST_READINGS", None)
        # nor its cgroup: a landing check runs this file at the top CPU weight
        self.stack.enter_context(patch.object(host, "process_cgroup", return_value=None))
        self.stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        self.stack.enter_context(patch.object(gate, "GATE_POLL", 0.05))
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
        run_record.save_state(directory, {"run_id": name, "title": name, "state": "running",
                                   "verdict": None, "repo": repo, **run_record.process_owner(),
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
        with gate.gate_lock(ACME, 0).open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)
            light = Gate(self, "light", ACME, [self.mark("light")], heavy=False)
            light.start()
            light.join(20)
            self.assertIsNone(light.error, light.error)
            self.assertTrue(light.result[0], light.result[1])
            self.assertFalse(light.waited(), light.logs)
            self.assertEqual(gate.gate_turn_note(run_record.read_state(light.run_dir)), "")
        self.assertEqual(self.marks.read_text(), "light\n")

    def test_more_headroom_allows_more_suites(self):
        small = gate.derived_heavy_limit(dict(SMALL))
        large = gate.derived_heavy_limit(dict(LARGE))
        self.assertEqual(large, 2 * small)
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(SMALL)}):
            self.assertIn(f"heavy suites: {small} at once (derived)",
                          gate.host_status_line())

    def test_an_opted_in_suite_holds_one_turn_per_piece(self):
        directory = self.record("pieces", ACME)
        command = 'echo "$AK_SHARD"'
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(SMALL)}):
            expected = gate.derived_heavy_limit(SMALL, running=0)
            with gate.gate_turn(directory, directory / "gate.log", None, command, self.root):
                self.assertEqual(gate._heavy_running(), expected)
                self.assertEqual(len(gate._GATE_HELD.hold.slots), expected)
                gate._GATE_HELD.hold.alone()
                self.assertEqual(gate._heavy_running(), 1)
            self.assertEqual(gate._heavy_running(), 0)

    def test_headroom_admits_a_fifth_suite_with_four_running(self):
        for resource, readings in (
                ("cpu", {**SMALL, "slice_cpu_used": 2.8 + 3}),
                ("memory", {**SMALL, "slice_memory_used_mb": 2870})):
            with self.subTest(resource=resource), ExitStack() as holders:
                holders.enter_context(patch.dict(os.environ, {
                    "AK_HOST_READINGS": json.dumps(readings)}))
                holders.enter_context(patch.object(gate.time, "sleep", side_effect=
                    AssertionError("headroom for three more suites must admit a fifth")))
                for index in range(4):
                    holder = holders.enter_context(gate.gate_lock(ACME, index).open("a"))
                    fcntl.flock(holder, fcntl.LOCK_EX)
                directory = self.record(resource, WIDGET)
                hold = gate._acquire_gate_turn(directory, directory / "donewhen.log", None)
                self.assertIsNotNone(hold)
                hold.release()

    def test_status_and_smoke_pool_count_held_turns(self):
        caller = self.root / "caller"
        home = caller / ".agentkit"
        runs = home / "runs"
        runs.mkdir(parents=True)
        smoke = (REPO / "tests/smoke.sh").read_text()
        pool_bound = smoke[smoke.index("smoke_pool_bound() {"):
                           smoke.index("\nsmoke_lock_probe()")]
        with patch.object(config, "HOME", home), patch.object(config, "RUNS", runs), \
                patch.dict(os.environ, {"HOME": str(caller), "REPO": str(REPO),
                                        "SMOKE_CALLER_HOME": str(caller)}), ExitStack() as holders:
            for index in (0, 1, 5, 9):
                holder = holders.enter_context(gate.gate_lock(ACME, index).open("a"))
                fcntl.flock(holder, fcntl.LOCK_EX)
            gate.gate_lock(ACME, 10).touch()
            for name, readings, pinned, expected in (
                    ("cpu", {**SMALL, "slice_cpu_used": 5.8}, "", 7),
                    ("memory", {**SMALL, "slice_memory_used_mb": 2870}, "", 7),
                    ("saturated", SATURATED, "", 4),
                    ("bad-config", {**SMALL, "slice_cpu_used": 5.8}, 'max_gates = "bad"', 7),
                    ("pinned", SMALL, "max_gates = 2", 2),
                    ("uncapped", SMALL, "max_gates = 0", 0)):
                with self.subTest(name=name), patch.dict(os.environ, {
                        "AK_HOST_READINGS": json.dumps(readings)}):
                    (home / config.CONFIG_NAME).write_text(pinned)
                    status = (f"{expected} at once ({'pinned' if name == 'pinned' else 'derived'})"
                              if expected else "no cap (pinned)")
                    status_line = gate.host_status_line().splitlines()[-1]
                    proc = subprocess.run(["bash", "-c", pool_bound + "\nsmoke_pool_bound"],
                                          capture_output=True, text=True, timeout=30)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual((status_line, proc.stdout.strip()),
                                     (f"heavy suites: {status}", str(expected)))
            holders.close()
            (home / config.CONFIG_NAME).write_text("")
            self.assertEqual(gate.derived_heavy_limit(SMALL), 10)

    def test_either_resource_below_one_suite_waits_with_one_running(self):
        for resource, readings in (
                ("cpu", {**SMALL, "slice_cpu_used": 8}),
                ("memory", {**SMALL, "slice_memory_used_mb": 4100 - 409})):
            with self.subTest(resource=resource), \
                    patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(readings)}), \
                    gate.gate_lock(ACME, 0).open("a") as holder, \
                    patch.object(gate.time, "sleep", side_effect=InterruptedError):
                fcntl.flock(holder, fcntl.LOCK_EX)
                directory = self.record(resource, WIDGET)
                log_path = directory / "donewhen.log"
                with self.assertRaises(InterruptedError):
                    gate._acquire_gate_turn(directory, log_path, None)
                self.assertEqual(log_path.read_text(),
                                 "waiting for a heavy suite turn · 1 running · 0 more fit\n")

    def test_waiting_line_uses_each_admission_reading(self):
        directory = self.record("waiter", WIDGET)
        log_path = directory / "donewhen.log"
        seen = []
        def poll(_seconds):
            seen.append(log_path.read_text())
            if len(seen) == 3:
                raise InterruptedError
        with ExitStack() as holders:
            for index in range(4):
                holder = holders.enter_context(gate.gate_lock(ACME, index).open("a"))
                fcntl.flock(holder, fcntl.LOCK_EX)
            with patch.object(host, "host_readings", side_effect=[
                    {**SMALL, "slice_cpu_used": used} for used in (5.8, 6.6, 8)]) as readings, \
                    patch.object(gate, "_gate_waiter_before", return_value=True), \
                    patch.object(gate.time, "sleep", side_effect=poll):
                with self.assertRaises(InterruptedError):
                    gate._acquire_gate_turn(directory, log_path, None)
            self.assertEqual(readings.call_count, 3)
        self.assertEqual(seen, [f"waiting for a heavy suite turn · 4 running · {more} more fit\n"
                                for more in (3, 2, 0)])

    def test_sampling_headroom_leaves_free_slots_unlocked(self):
        for name, config_text in (("derived", ""), ("fallback", 'max_gates = "bad"')):
            (config.HOME / config.CONFIG_NAME).write_text(config_text)
            for running in (0, 1):
                with self.subTest(config=name, running=running), ExitStack() as holders:
                    for index in range(6):
                        gate.gate_lock(ACME, index).touch()
                    if running:
                        holder = holders.enter_context(gate.gate_lock(ACME, 0).open("a"))
                        fcntl.flock(holder, fcntl.LOCK_EX)
                    directory = self.record(f"{name}-{running}", WIDGET)
                    log_path = directory / "donewhen.log"
                    def sample(**_kw):
                        self.assertEqual(gate._heavy_running(), running)
                        self.assertEqual(gate.derived_heavy_limit(SATURATED), 1)
                        return SATURATED
                    with patch.object(host, "host_readings", side_effect=sample) as readings, \
                            patch.object(gate.time, "sleep", side_effect=InterruptedError):
                        if running:
                            with self.assertRaises(InterruptedError):
                                gate._acquire_gate_turn(directory, log_path, None)
                            self.assertEqual(log_path.read_text(),
                                "waiting for a heavy suite turn · 1 running · 0 more fit\n")
                        else:
                            hold = gate._acquire_gate_turn(directory, log_path, None)
                            self.assertIsNotNone(hold)
                            hold.release()
                        self.assertEqual(readings.call_count, 1)

    def test_a_saturated_slice_waits_yet_one_turn_is_always_free(self):
        self.assertEqual(gate.derived_heavy_limit(dict(SATURATED)), 1)
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(SATURATED)}):
            first = Gate(self, "one", ACME, [self.mark("start", 1), self.mark("end")])
            second = Gate(self, "two", WIDGET, [self.mark("queued")])
            first.start()
            self.until(lambda: "start" in self.marks.read_text(),
                       "the first suite to take the one turn")
            second.start()
            gate_log = second.run_dir / "donewhen.log"
            self.until(lambda: gate_log.is_file() and gate_log.read_text() ==
                       "waiting for a heavy suite turn · 1 running · 0 more fit\n",
                       "the second suite to wait")
            self.assertEqual(gate.gate_turn_note(run_record.read_state(second.run_dir)),
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
        with gate.gate_lock(ACME, 0).open("a") as holder, \
                patch.object(host, "host_readings", side_effect=
                    AssertionError("a pinned limit needs no host reading")):
            fcntl.flock(holder, fcntl.LOCK_EX)
            waiter = Gate(self, "waiter", ACME, [self.mark("waiter")])
            waiter.start()
            self.until(lambda: gate.gate_turn_note(run_record.read_state(waiter.run_dir) or {}),
                       "the waiter to mark its wait")
            self.gates(2)
            waiter.join(20)
            self.assertIsNone(waiter.error, waiter.error)
            self.assertTrue(waiter.result[0], waiter.result[1])
            self.assertTrue(waiter.waited(), waiter.logs)
        self.assertEqual(self.marks.read_text(), "waiter\n")

    def test_a_shrinking_limit_counts_holders_beyond_its_prefix(self):
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(SATURATED)}):
            self.assertEqual(gate.derived_heavy_limit(), 1)
            # two suites ran at limit 2; one finished, freeing slot 0, while the
            # other still holds slot 1 -- a saturated limit of 1 admits none more
            with gate.gate_lock(ACME, 0).open("a"):
                pass
            with gate.gate_lock(ACME, 1).open("a") as holder:
                fcntl.flock(holder, fcntl.LOCK_EX)
                third = Gate(self, "three", ACME, [self.mark("third")])
                third.start()
                self.until(lambda: gate.gate_turn_note(
                    run_record.read_state(third.run_dir) or {}),
                    "the third suite to wait on the saturated turn")
                self.assertNotIn("third", self.marks.read_text())
            third.join(20)
            self.assertIsNone(third.error, third.error)
            self.assertTrue(third.waited(), third.logs)
            self.assertEqual(self.marks.read_text(), "third\n")

    def test_a_pinned_max_gates_holds(self):
        self.gates(2)
        with patch.dict(os.environ, {"AK_HOST_READINGS": json.dumps(SATURATED)}):
            self.assertIn("heavy suites: 2 at once (pinned)", gate.host_status_line())
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
