"""A freed gate turn goes to the longest waiter, `--first` before the rest.  Offline.

A temporary HOME, fake run records and fake repositories; live waiters are this
process's own records, the dead one a pid that already exited. Nothing here
signals a real process.
"""

from contextlib import ExitStack
import fcntl
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
from agentkit import config, run, worker

ACME = "/home/fixture/code/acme"        # main checkouts as the records name them; never opened
ELSEWHERE = "/home/fixture/other/acme"  # the same folder name, another repository


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
        except BaseException as exc:      # noqa: BLE001 -- the test reads it
            self.error = exc

    def waited(self):
        return any(line.startswith("done-when: waiting for a gate turn") for line in self.logs)


class GateOrder(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".gate-turns-order-", dir=REPO)
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
        (config.HOME / config.CONFIG_NAME).write_text("max_gates = 1\n")
        self.marks = self.root / "marks"
        self.marks.touch()
        self.dead = self.reaped_pid()

    def reaped_pid(self):
        """A pid that is already gone: spawned, waited on, and checked still gone."""
        for _ in range(10):
            proc = subprocess.Popen(["true"])
            proc.wait()
            if not run.alive(proc.pid):
                return proc.pid
        self.fail("could not find a dead pid")

    def record(self, name, repo, first=False, owner=None):
        """A running run's record, this process its loop unless `owner` says otherwise."""
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "title": name, "state": "running", "verdict": None,
                 "repo": repo, **(owner if owner is not None else run.process_owner()),
                 "started_at": time.time(), "round_summaries": []}
        if first:
            state["first"] = True
        run.save_state(directory, state)
        return directory

    def waiter(self, name, repo, since, first=False, owner=None, stale=False):
        """A record marked waiting for a gate turn of `repo` since `since`.

        `stale` leaves a kill-or-resume mark behind: the wait's pid is no longer the
        record's, so the note is gone but the dict is still there.
        """
        directory = self.record(name, repo, first, owner)
        state = run.read_state(directory)
        pid = self.dead if stale else state["pid"]
        state["gate_turn"] = {"pid": pid, "of": str(run.main_checkout(repo)), "since": since}
        run.save_state(directory, state)
        return directory

    def since(self, name):
        turn = (run.read_state(config.RUNS / name) or {}).get("gate_turn") or {}
        return turn.get("since")

    def mark(self, word, seconds=0):
        return f"echo {word} >> {shlex.quote(str(self.marks))}; sleep {seconds}"

    def until(self, check, what, seconds=20):
        deadline = time.monotonic() + seconds
        while not check():
            self.assertLess(time.monotonic(), deadline, f"timed out waiting for {what}")
            time.sleep(0.02)

    def test_three_waiters_take_freed_turns_in_wait_order_whichever_polls_first(self):
        one = Gate(self, "one", ACME, [self.mark("one")])
        two = Gate(self, "two", ACME, [self.mark("two")])
        three = Gate(self, "three", ACME, [self.mark("three")])
        holder = run.gate_lock(ACME, 0).open("a")
        self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)
        one.start()
        self.until(lambda: self.since("one") is not None, "one to mark its wait")
        two.start()
        self.until(lambda: self.since("two") is not None, "two to mark its wait")
        three.start()
        self.until(lambda: self.since("three") is not None, "three to mark its wait")
        first, second, third = self.since("one"), self.since("two"), self.since("three")
        self.assertLess(first, second)
        self.assertLess(second, third)
        repo = run.main_checkout(ACME)
        # whatever order they poll in, the last to wait still finds two before it
        self.assertTrue(run._gate_waiter_before(repo, "three", False, third))
        self.assertTrue(run._gate_waiter_before(repo, "two", False, second))
        self.assertFalse(run._gate_waiter_before(repo, "one", False, first))
        fcntl.flock(holder, fcntl.LOCK_UN)
        one.join(20)
        two.join(20)
        three.join(20)
        self.assertIsNone(one.error, one.error)
        self.assertIsNone(two.error, two.error)
        self.assertIsNone(three.error, three.error)
        self.assertTrue(one.result[0] and two.result[0] and three.result[0])
        self.assertEqual(self.marks.read_text(), "one\ntwo\nthree\n")

    def test_first_goes_before_earlier_plain_waiter_while_dead_marks_hold_nobody(self):
        repo = run.main_checkout(ACME)
        # a dead --first waiter's mark still reads waiting, and a kill-or-resume mark
        # left its dict behind; neither holds another back
        self.waiter("dead-first", ACME, 500, first=True, owner={"pid": self.dead})
        self.waiter("stale-first", ACME, 400, first=True, stale=True)
        dead = run.read_state(config.RUNS / "dead-first")
        self.assertEqual(run.gate_turn_note(dead), "waiting for a gate turn of acme")
        self.assertEqual(dead["gate_turn"]["of"], ACME)
        stale = run.read_state(config.RUNS / "stale-first")
        self.assertEqual(run.gate_turn_note(stale), "")
        self.assertFalse(run._gate_waiter_before(repo, "ghost", False, 3000))
        self.assertFalse(run._gate_waiter_before(repo, "ghost-first", True, 3000))
        self.waiter("plain", ACME, 1000)
        self.waiter("first-run", ACME, 2000, first=True)
        self.assertFalse(run._gate_waiter_before(repo, "first-run", True, 2000))
        self.assertTrue(run._gate_waiter_before(repo, "plain", False, 1000))

    def test_waiter_of_same_named_checkout_elsewhere_is_ignored(self):
        self.waiter("elsewhere-first", ELSEWHERE, 500, first=True)
        state = run.read_state(config.RUNS / "elsewhere-first")
        self.assertEqual(run.gate_turn_note(state), "waiting for a gate turn of acme")
        self.assertEqual(state["gate_turn"]["of"], ELSEWHERE)
        repo = run.main_checkout(ACME)
        self.assertFalse(run._gate_waiter_before(repo, "ghost", False, 3000))
        self.assertFalse(run._gate_waiter_before(repo, "ghost-first", True, 3000))
        gate = Gate(self, "quick", ACME, [self.mark("quick")])
        gate.start()
        gate.join(20)
        self.assertIsNone(gate.error, gate.error)
        self.assertTrue(gate.result[0])
        self.assertFalse(gate.waited(), gate.logs)
        self.assertEqual(self.marks.read_text(), "quick\n")
        # and a waiter of this checkout still counts
        self.waiter("plain", ACME, 1000)
        self.assertTrue(run._gate_waiter_before(repo, "ghost", False, 3000))


if __name__ == "__main__":
    unittest.main()
