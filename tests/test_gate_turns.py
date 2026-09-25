"""A repository's done-when gates take turns, `max_gates` at a time, host-wide.  Offline.

A temporary HOME, repositories that are only paths on the run records or fake ones made
here, and short shell commands; nothing here touches the real ~/.agentkit or any real process.
"""

from contextlib import ExitStack
import fcntl
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

ACME = "/home/fixture/code/acme"        # main checkouts as the records name them; never opened
WIDGET = "/home/fixture/code/widget"
WAITING = "waiting for a gate turn · 1 of acme running"


class Gate(threading.Thread):
    """One `run_done_when` in a thread of its own, its result or its exception kept."""

    def __init__(self, case, name, repo, cmds, **kw):
        super().__init__(daemon=True)
        self.run_dir = case.record(name, repo)
        self.logs, self.result, self.error = [], None, None
        self.args = (cmds, case.root, self.run_dir / "donewhen.log", set())
        self.kw = {"log": self.logs.append, "run_dir": self.run_dir, **kw}

    def run(self):
        try:
            self.result = run.run_done_when(*self.args, **self.kw)
        except BaseException as exc:      # noqa: BLE001 -- the test reads it
            self.error = exc

    def waited(self):
        return any(line == f"done-when: {WAITING}" for line in self.logs)


class GateTurns(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".gate-turns-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        # a worker running this file carries its run's marker, which a killed command below
        # would end, and the suites' AK_MAX_RUNS=0, under which no gate takes a turn
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root),
                                                          "AGENTKIT_RUN": "", "AK_RUN_DEPTH": "0"}))
        os.environ.pop("AK_MAX_RUNS", None)
        self.stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        self.stack.enter_context(patch.object(run, "GATE_POLL", 0.05))
        self.stack.enter_context(patch.object(worker, "ACTIVITY_POLL", 0.05))
        config.RUNS.mkdir(parents=True)
        config.HOME.mkdir()
        self.gates(1)
        self.marks = self.root / "marks"
        self.marks.touch()

    def gates(self, count):
        (config.HOME / config.CONFIG_NAME).write_text(f"max_gates = {count}\n")

    def record(self, name, repo):
        """A running run's record, this process its loop, of `repo` (or of no repository)."""
        directory = config.RUNS / name
        directory.mkdir()
        run.save_state(directory, {"run_id": name, "title": name, "state": "running",
                                   "verdict": None, "repo": repo, **run.process_owner(),
                                   "started_at": time.time(), "round_summaries": []})
        return directory

    def mark(self, word, seconds=0):
        return f"echo {word} >> {shlex.quote(str(self.marks))}; sleep {seconds}"

    def hold(self, word):
        """A command that writes its mark, then keeps its turn until `self.release()`."""
        self.addCleanup(self.release)      # a test that fails first must not leave it running
        go = shlex.quote(str(self.root / "go"))
        return f"{self.mark(word)}; until [ -e {go} ]; do sleep 0.05; done"

    def release(self):
        (self.root / "go").touch()

    def checkout(self):
        """A fake repository under the sandbox and a linked worktree added from it, as recorded."""
        main, linked = self.root / "acme", self.root / "acme-topic"
        run.git(self.root, "init", "-q", str(main))
        run.git(main, "-c", "user.name=fixture", "-c", "user.email=fixture@localhost",
                "commit", "-q", "--allow-empty", "-m", "baseline")
        run.git(main, "worktree", "add", "-q", str(linked), "-b", "topic")
        return str(main), str(linked)

    def until(self, check, what, seconds=20):
        deadline = time.monotonic() + seconds
        while not check():
            self.assertLess(time.monotonic(), deadline, f"timed out waiting for {what}")
            time.sleep(0.02)

    def started(self, gate):
        """Once `gate`'s first command has written its mark, so the next gate is the waiter."""
        gate.start()
        self.until(lambda: "start" in self.marks.read_text(), "the first gate to start")

    def test_two_gates_of_one_repository_run_one_after_the_other(self):
        first = Gate(self, "one", ACME, [self.mark("start", 1), self.mark("end")])
        second = Gate(self, "two", ACME, [self.mark("start", 0.2), self.mark("end")])
        self.started(first)
        second.start()
        gate_log = second.run_dir / "donewhen.log"
        self.until(lambda: gate_log.is_file() and gate_log.read_text() == WAITING + "\n",
                   "the gate log's waiting line")
        state = run.read_state(second.run_dir)
        self.assertEqual(run.gate_turn_note(state), "waiting for a gate turn of acme")
        self.assertIn("  waiting for a gate turn of acme",
                      run.status_details(second.run_dir, state))
        first.join(20)
        second.join(20)
        self.assertEqual(self.marks.read_text(), "start\nend\nstart\nend\n")
        self.assertFalse(first.waited(), first.logs)
        self.assertEqual(second.logs[0], f"done-when: {WAITING}")
        self.assertRegex(second.logs[1], r"^done-when: took a gate turn of acme after \d+s$")
        self.assertTrue(second.result[0], second.result[1])
        self.assertNotIn("waiting", second.result[1])
        self.assertEqual(run.gate_turn_note(run.read_state(second.run_dir)), "")

    def test_gates_of_different_repositories_do_not_wait_on_each_other(self):
        first = Gate(self, "one", ACME, [self.mark("start", 3), self.mark("end")])
        other = Gate(self, "two", WIDGET, [self.mark("other")])
        self.started(first)
        other.start()
        other.join(20)
        first.join(20)
        self.assertEqual(self.marks.read_text(), "start\nother\nend\n")
        self.assertFalse(other.waited(), other.logs)
        self.assertTrue(first.result[0] and other.result[0])

    def test_a_wait_past_the_silence_window_costs_neither_the_gate_nor_its_ceiling(self):
        first = Gate(self, "one", ACME, [self.mark("start", 4)])
        chatty = (f"{shlex.quote(sys.executable)} -u -c "
                  "'import time\nfor i in range(8): print(i); time.sleep(0.2)'")
        # a silence window the wait outlasts, and a ceiling the wait plus the command would
        # spend, were either charged with the wait
        second = Gate(self, "two", ACME, [chatty], silence=1, limit=3.5)
        self.started(first)
        began = time.monotonic()
        second.start()
        first.join(20)
        second.join(20)
        self.assertGreater(time.monotonic() - began, 3.5)
        self.assertTrue(second.waited(), second.logs)
        self.assertTrue(second.result[0], second.result[1])
        self.assertNotIn("stopped after", second.result[1])
        self.assertIn("[exit 0]\n0\n1\n", second.result[1])

    def test_a_stop_while_waiting_runs_no_command(self):
        with run.gate_lock(ACME, 0).open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)
            waiter = Gate(self, "two", ACME, [self.mark("ran")])
            waiter.start()
            self.until(lambda: run.gate_turn_note(run.read_state(waiter.run_dir) or {}),
                       "the record's waiting mark")
            run.save_state(waiter.run_dir, {**run.read_state(waiter.run_dir), "state": "stopped"})
            waiter.join(20)
        self.assertIsInstance(waiter.error, run.StopRequested)
        self.assertEqual(self.marks.read_text(), "")
        self.assertEqual(run.gate_turn_note(run.read_state(waiter.run_dir)), "")

    def test_a_killed_command_lets_the_turn_go_and_max_gates_zero_never_waits(self):
        killed = Gate(self, "one", ACME, ["sleep 30"], silence=0.3)
        killed.start()
        killed.join(30)
        self.assertFalse(killed.result[0])
        self.assertIn("[killed at the limit]", killed.result[1])
        after = Gate(self, "two", ACME, [self.mark("after")])
        after.start()
        after.join(20)
        self.assertFalse(after.waited(), after.logs)
        self.gates(0)
        with run.gate_lock(ACME, 0).open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)
            uncapped = Gate(self, "three", ACME, [self.mark("uncapped")])
            uncapped.start()
            uncapped.join(20)
        self.assertFalse(uncapped.waited(), uncapped.logs)
        self.assertEqual(self.marks.read_text(), "after\nuncapped\n")

    def test_no_repository_and_the_suites_escape_hatch_take_no_turn(self):
        with run.gate_lock(ACME, 0).open("a") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)
            scratch = Gate(self, "one", None, [self.mark("scratch")])
            scratch.start()
            scratch.join(20)
            with patch.dict(os.environ, {"AK_MAX_RUNS": "0"}):
                suite = Gate(self, "two", ACME, [self.mark("suite")])
                suite.start()
                suite.join(20)
        self.assertEqual(self.marks.read_text(), "scratch\nsuite\n")
        self.assertFalse(scratch.waited() or suite.waited(), scratch.logs + suite.logs)

    def test_a_gate_recorded_in_a_linked_worktree_waits_for_a_gate_of_its_main_checkout(self):
        main, linked = self.checkout()
        first = Gate(self, "one", main, [self.hold("start")])
        second = Gate(self, "two", linked, [self.mark("linked")])
        self.started(first)
        second.start()
        gate_log = second.run_dir / "donewhen.log"
        self.until(lambda: gate_log.is_file() and gate_log.read_text() == WAITING + "\n",
                   "the linked worktree's gate to wait")
        self.assertEqual(run.gate_turn_note(run.read_state(second.run_dir)),
                         "waiting for a gate turn of acme")
        self.assertEqual(self.marks.read_text(), "start\n")
        self.release()
        first.join(20)
        second.join(20)
        self.assertEqual(self.marks.read_text(), "start\nlinked\n")
        self.assertTrue(first.result[0] and second.result[0], (first.result, second.result))
        self.assertRegex(second.logs[1], r"^done-when: took a gate turn of acme after \d+s$")

    def test_a_bad_config_runs_the_gate_under_the_default_and_names_the_problem(self):
        path = config.HOME / config.CONFIG_NAME
        path.write_text('max_gates = "x"\n')
        with ExitStack() as held:
            for slot in range(config.RUN_DEFAULTS["max_gates"]):
                holder = held.enter_context(run.gate_lock(ACME, slot).open("a"))
                fcntl.flock(holder, fcntl.LOCK_EX)
            gate = Gate(self, "one", ACME, [self.mark("ran")])
            gate.start()
            gate_log = gate.run_dir / "donewhen.log"
            self.until(lambda: gate_log.is_file()
                       and gate_log.read_text() == "waiting for a gate turn · 3 of acme running\n",
                       "the gate to wait on the default's three turns")
        gate.join(20)
        self.assertTrue(gate.result[0], gate.result[1])
        self.assertEqual(self.marks.read_text(), "ran\n")
        problem = f"{path}: max_gates must be a non-negative integer"
        self.assertEqual(gate.logs[0], f"done-when: {problem} · the gate takes one of the shipped "
                                       "default's 3 turns")


if __name__ == "__main__":
    unittest.main()
