"""A heavy suite whose own host-wide lock is another copy's gives its turn back.  Offline.

A temporary HOME and a fake suite that takes a lock file of its own under it; nothing here
reads the real ~/.agentkit, a real suite's lock or the machine's readings.
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
from test_red_target import make_loop, make_repos

ACME = "/home/fixture/code/acme"        # main checkouts as the records name them; never opened
WIDGET = "/home/fixture/code/widget"
# One copy at a time behind its own lock: on a heavy suite turn a busy lock is said at once,
# exit 75; told nothing, the suite waits for its lock like any by-hand run.
SUITE = """
import fcntl, os, sys, time
lock, marks, word, go = sys.argv[1:]
fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    if os.environ.get("AK_HEAVY_TURN") == "1":
        with open(marks, "a") as fh:
            fh.write("busy\\n")
        print("busy: another copy holds the lock")
        sys.exit(75)
    fcntl.flock(fd, fcntl.LOCK_EX)
with open(marks, "a") as fh:
    fh.write(word + "\\n")
while go != "-" and not os.path.exists(go):
    time.sleep(0.05)
"""


class Gate(threading.Thread):
    """One `run_done_when` in a thread of its own, its result or its exception kept."""

    def __init__(self, case, name, repo, cmds, heavy=True):
        super().__init__(daemon=True)
        directory = config.RUNS / name
        directory.mkdir()
        run.save_state(directory, {"run_id": name, "title": name, "state": "running",
                                   "verdict": None, "repo": repo, **run.process_owner(),
                                   "started_at": time.time(), "round_summaries": []})
        self.logs, self.result, self.error = [], None, None
        self.args = (cmds, case.root, directory / "donewhen.log", set())
        self.kw = {"log": self.logs.append, "run_dir": directory, "heavy": heavy}

    def run(self):
        try:
            self.result = run.run_done_when(*self.args, **self.kw)
        except BaseException as exc:      # noqa: BLE001 -- the test reads it
            self.error = exc

    def waited(self):
        return any(line.startswith("done-when: waiting for a heavy suite turn")
                   for line in self.logs)


class BusySuite(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".heavy-turn-busy-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        # a worker running this file carries its run's marker, which a killed command would
        # end, and the suites' AK_MAX_RUNS=0, under which no suite takes a turn
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_RUN_DEPTH": "0",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        for name in ("AK_MAX_RUNS", "AK_HOST_READINGS", "AK_HEAVY_TURN", "AK_PARENT_RUN",
                     "AK_RUN_LOG"):
            os.environ.pop(name, None)
        self.stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        self.stack.enter_context(patch.object(run, "GATE_POLL", 0.05))
        self.stack.enter_context(patch.object(worker, "ACTIVITY_POLL", 0.05))
        config.RUNS.mkdir(parents=True)
        config.HOME.mkdir()
        self.marks = self.root / "marks"
        self.marks.touch()
        self.lock = self.root / "suite.lock"
        self.go = self.root / "go"
        (self.root / "suite.py").write_text(SUITE)

    def gates(self, count):
        (config.HOME / config.CONFIG_NAME).write_text(f"max_gates = {count}\n")

    def suite(self, word, hold=False):
        return shlex.join([sys.executable, str(self.root / "suite.py"), str(self.lock),
                           str(self.marks), word, str(self.go) if hold else "-"])

    def until(self, check, what, seconds=20):
        deadline = time.monotonic() + seconds
        while not check():
            self.assertLess(time.monotonic(), deadline, f"timed out waiting for {what}")
            time.sleep(0.02)

    def turn_free(self):
        """Whether one of the host's heavy-suite turns is free this instant; it stays free."""
        for path in sorted(config.RUNS.glob(".heavy-*.lock")):
            with path.open("a") as slot:
                try:
                    fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                return True
        return False

    def hold_lock(self):
        """This test as the other copy of the suite, holding its lock until it lets go."""
        held = self.lock.open("a")
        self.addCleanup(held.close)
        fcntl.flock(held, fcntl.LOCK_EX)
        return held

    def test_a_busy_suite_gives_its_turn_to_another_repositorys_and_runs_once_free(self):
        self.gates(2)
        self.addCleanup(self.go.touch)     # a test that fails first must not leave one running
        with patch.object(run, "GATE_POLL", 2):
            first = Gate(self, "one", ACME, [self.suite("one", hold=True)])
            first.start()
            self.until(lambda: self.marks.read_text() == "one\n", "the first copy to start")
            second = Gate(self, "two", ACME, [self.suite("two")])
            second.start()
            self.until(lambda: self.marks.read_text() == "one\nbusy\n", "the second to say busy")
            self.until(self.turn_free, "the busy copy to give its turn back")
            # the one turn left, while the first copy runs and the second waits for its lock
            other = Gate(self, "three", WIDGET, [f"echo other >> {shlex.quote(str(self.marks))}"])
            other.start()
            other.join(20)
            self.assertTrue(other.result[0], other.result)
            self.assertFalse(other.waited(), other.logs)
            self.assertEqual(self.marks.read_text().replace("busy\n", ""), "one\nother\n")
            self.go.touch()
            first.join(20)
            second.join(20)
        self.assertEqual(self.marks.read_text().replace("busy\n", ""), "one\nother\ntwo\n")
        self.assertTrue(first.result[0], first.result)
        ok, text = second.result
        self.assertTrue(ok, text)
        self.assertNotIn("exit 75", text)
        self.assertNotIn("flaky:", text)
        busy = [line for line in second.logs if line.startswith("done-when: busy:")]
        self.assertEqual(len(busy), 1, second.logs)

    def test_only_a_suite_on_a_turn_is_told_it_holds_one(self):
        self.gates(1)
        said = f'echo "[${{AK_HEAVY_TURN:-}}]" >> {shlex.quote(str(self.marks))}'
        with patch.dict(os.environ, {"AK_HEAVY_TURN": "1"}):    # a suite this loop runs below
            for n, (heavy, repo) in enumerate(((True, ACME), (False, ACME), (True, None))):
                gate = Gate(self, f"run-{n}", repo, [said], heavy)
                gate.start()
                gate.join(20)
                self.assertTrue(gate.result[0], gate.result)
        self.assertEqual(self.marks.read_text(), "[1]\n[]\n[]\n")

    def test_a_busy_probe_of_the_target_gives_its_turn_back_and_runs_once_free(self):
        self.gates(1)
        held = self.hold_lock()
        (self.root / "probe").mkdir()
        _, _, wt = make_repos(self.root / "probe")
        cmd = self.suite("probe")
        lp, run_dir, _ = make_loop(self.root / "probe", wt, ["true", f"{cmd}  # once"])
        results = {}

        def body():
            try:
                results["probed"] = run.target_fails(lp, "origin/main", f"$ {cmd}\n[exit 1]\nFAIL")
            except BaseException as exc:      # noqa: BLE001 -- the test reads it
                results["probed"] = exc
        probe = threading.Thread(target=body, daemon=True)
        probe.start()
        self.until(lambda: "busy" in self.marks.read_text(), "the probe to say busy")
        self.until(self.turn_free, "the busy probe to give its turn back")
        self.assertTrue(probe.is_alive(), results)
        fcntl.flock(held, fcntl.LOCK_UN)
        probe.join(20)
        self.assertFalse(probe.is_alive(), "the probe never ran once its lock was free")
        # it passed on the target, so the branch broke it: no busy answer read as red
        self.assertEqual(results["probed"], "")
        self.assertEqual(self.marks.read_text().replace("busy\n", ""), "probe\n")


if __name__ == "__main__":
    unittest.main()
