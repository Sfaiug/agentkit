"""A line's own check goes first for a heavy suite turn, and only its wait holds back new runs.

Owner, 29 Oct 2026: the line is where a repository's changes land one at a time, so its check's
wait delays every change behind it, while a run's check before it joins the line only spares the
line a red.  Black-box through tests/fixtures/akbin.py: runs against gitrig.py's origins,
fakegh.py's GitHub and fakeadapter.py's harnesses.  The host fits two suites (AK_HOST_READINGS);
the test fills what the suites leave by holding ak's turn files, and frees one at a time.  Each
repository's suite says when it starts and runs until the test lets it end.  A line checks its
member itself, and runs the suite, once its origin moved past the tree the run checked.
"""

from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# Two suites of 0.7 core fit 1.4 cores, however many run.
READINGS = {"cpus": 1.4, "free_mb": 8000, "slice_cpu_pressure": 0}
# Walled off from the test's files, a suite says it started on the test's socket, and ends
# once the test answers on its own.
SUITE = """import os, socket, sys
own = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
own.bind(address := f"\\0ak-suite-{{os.urandom(8).hex()}}")
own.sendto(f"{{sys.argv[1]}} {{address}}".encode(), {said!r})
own.recv(8)
"""
WAITS = "waiting for a heavy suite turn"
BOUND = 240


class LineCheckGoesFirst(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.turns = ExitStack()
        self.addCleanup(self.turns.close)
        home.env.update(AK_HOST_READINGS=json.dumps(READINGS), AK_MIN_FREE_MB="0",
                        AK_SLOT_POLL="0.5")
        home.env.pop("AK_MAX_RUNS")     # heavy suite turns and admission, which it turns off
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex="pass")["claude"].behave(
            {"write": {"retry.txt": "hello\n"}, "commit": "add retry.txt",
             "hand_in": [["done"]]})
        self.runs = home.path / ".agentkit" / "runs"
        self.rigs, self.started = {}, []
        self.said = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.addCleanup(self.said.close)
        self.said.bind(address := f"\0ak-line-first-{os.getpid()}")
        self.said.setblocking(False)
        self.suite = SUITE.format(said=address)

    def start(self, name, *args, every_round=False):
        """A run on the repository `name`, its suite run every round when told so."""
        if name not in self.rigs:
            suite = f"python3 suite.py {name}" + (" # AK_CHANGED" if every_round else "")
            self.rigs[name] = Rig(self.home, name, files={
                "AGENTS.md": f"---\ntests: {suite}\n---\n", "suite.py": self.suite})
            GitHub(self.home).grant(self.rigs[name].slug, "WRITE")
        before = set(taskfile.runs(self.home))
        task = taskfile.write(self.home, self.rigs[name].path, f"Add retry to {name}",
                              name=f"{name}-{len(before)}")
        done = self.home.ak("run", str(task), "--bg", *args)
        self.assertEqual(done.code, 0, done.out + done.err)
        return (set(taskfile.runs(self.home)) - before).pop()

    def until(self, check, what):
        deadline = time.monotonic() + BOUND
        while not check():
            self.assertLess(time.monotonic(), deadline, f"never happened: {what}")
            time.sleep(0.2)

    def order(self):
        """Whose suites started, in order."""
        while True:
            try:
                self.started.append(self.said.recv(64).decode().split(" ", 1))
            except BlockingIOError:
                return [name for name, _ in self.started]

    def waiting(self, run):
        """Whether `run` says it waits for a heavy suite turn."""
        done = self.home.ak("run", "status", run.name)
        return WAITS in done.out

    def lines_waiting(self):
        """How many lines' checkers said they waited for a heavy suite turn."""
        return sum(WAITS in path.read_text(errors="replace")
                   for path in self.runs.glob(".merge-*.log"))

    def hold(self):
        """Hold one more turn, so a suite that ends leaves none free."""
        for index in range(64):
            turn = self.turns.enter_context((self.runs / f".heavy-{index}.lock").open("a"))
            try:
                fcntl.flock(turn, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return turn
            except BlockingIOError:
                continue
        self.fail("no turn file left to hold")

    def end(self, name):
        """Let `name`'s running suite end."""
        self.said.sendto(b"end", [own for started, own in self.started if started == name][-1])

    def free(self, turn, name):
        """Free a held turn; the suite of `name` takes it next."""
        ran = len(self.order())
        fcntl.flock(turn, fcntl.LOCK_UN)
        self.until(lambda: len(self.order()) > ran, f"{name}'s suite to take the freed turn")
        self.assertEqual(self.order()[ran], name, self.order())
        held = self.hold()
        self.end(name)
        return held

    def queued(self, run):
        """Why `run` waits to start, while it does."""
        try:
            state = json.loads((run / "run.json").read_text())
        except (OSError, ValueError):
            return ""
        return state.get("slot_wait_reason", "") if state.get("state") == "queued" else ""

    def test_line_checks_go_first_and_alone_hold_back_new_runs(self):
        self.start("anvils")
        self.start("bolts")
        self.until(lambda: sorted(self.order()) == ["anvils", "bolts"],
                   "both runs' checks before the line to run")
        # Only a round check, then also a check before the line, waits: each next run goes in.
        cogs = self.start("cogs", every_round=True)
        self.until(lambda: self.waiting(cogs), "the round check to wait")
        dials = self.start("dials")
        self.until(lambda: self.waiting(dials), "a run admitted beside a round check")
        eagles = self.start("eagles")
        self.until(lambda: self.waiting(eagles), "a run admitted beside a check before the line")
        # Each origin moves past the tree its run checked, so each line checks its member.
        for waited, name in enumerate(("anvils", "bolts"), 1):
            self.rigs[name].commit({"notes.txt": "moved\n"}, "move the target")
            held = self.hold()
            self.end(name)
            self.until(lambda: self.lines_waiting() == waited, f"{name}'s line to wait")
        new = self.start("anvils", "--no-merge")
        self.until(lambda: "finished work goes first" in self.queued(new),
                   "a new run to wait behind the lines' checks")
        # The lines' checks, the older first, ahead of older checks before the line; those
        # by their waits, ahead of the older round check.
        for name in ("anvils", "bolts", "dials", "eagles", "cogs"):
            held = self.free(held, name)


if __name__ == "__main__":
    unittest.main()
