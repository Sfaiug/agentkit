"""A run starts while a line's check waits for a heavy suite turn: memory alone admits it.

Owner, 10 Nov 2026: "Remove it." -- the hold that let in no run but a `--first` one or a woken
member while a line's check waited for a turn.  It dates from 5 Oct 2026, when every round ran
the suite and a run let in soon asked for the turns that check waited for.  Since 10 Nov 2026 no
round runs the suite, so a run let in takes no heavy turn before its line's check does, which
goes first for a turn by rank anyway.

Black-box through tests/fixtures/akbin.py: runs against gitrig.py's origins, fakegh.py's GitHub
and fakeadapter.py's harnesses.  The host fits two suites (AK_HOST_READINGS); each repository's
suite says when it starts and runs until the test ends.
"""

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
# Walled off from the test's files, a suite says it started on the test's socket, then waits
# for an answer that never comes.
SUITE = """import os, socket, sys
own = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
own.bind(f"\\0ak-suite-{{os.urandom(8).hex()}}")
own.sendto(sys.argv[1].encode(), {said!r})
own.recv(8)
"""
WAITS = "waiting for a heavy suite turn"
BOUND = 240


class ARunStartsWhileALineSCheckWaits(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        home.env.update(AK_HOST_READINGS=json.dumps(READINGS), AK_MIN_FREE_MB="0",
                        AK_SLOT_POLL="0.5")
        home.env.pop("AK_MAX_RUNS")     # heavy suite turns and admission, which it turns off
        akconfig.write(home, ["opus", "astra"])
        self.executor = fakeadapter.install(home, claude="work", codex="pass")["claude"]
        self.started = []
        self.said = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.addCleanup(self.said.close)
        self.said.bind(address := f"\0ak-run-starts-{os.getpid()}")
        self.said.setblocking(False)
        self.rigs = {name: Rig(home, name, files={
            "AGENTS.md": f"---\nhealth: none\ntests: python3 suite.py {name}\n---\n",
            "suite.py": SUITE.format(said=address)}) for name in ("anvils", "bolts", "cogs")}
        for rig in self.rigs.values():
            GitHub(home).grant(rig.slug, "WRITE")

    def start(self, name):
        task = taskfile.write(self.home, self.rigs[name].path, f"Add retry to {name}",
                              name=f"{name}-{len(taskfile.runs(self.home))}")
        done = self.home.ak("run", str(task), "--bg")
        self.assertEqual(done.code, 0, done.out + done.err)

    def until(self, check, what):
        deadline = time.monotonic() + BOUND
        while not check():
            self.assertLess(time.monotonic(), deadline, f"never happened: {what}")
            time.sleep(0.2)

    def order(self):
        """Whose suites started, in order."""
        while True:
            try:
                self.started.append(self.said.recv(64).decode())
            except BlockingIOError:
                return self.started

    def lines_waiting(self):
        """How many lines' checkers said they waited for a heavy suite turn."""
        return sum(WAITS in path.read_text(errors="replace")
                   for path in (self.home.path / ".agentkit" / "runs").glob(".merge-*.log"))

    def test_a_run_starts_its_executor_while_a_line_s_check_waits_for_a_turn(self):
        self.start("anvils")
        self.start("bolts")
        self.until(lambda: sorted(self.order()) == ["anvils", "bolts"],
                   "two lines' checks to hold both turns")
        self.start("cogs")
        self.until(lambda: self.lines_waiting() == 1, "the third line's check to wait")
        built = self.executor.n
        self.start("anvils")
        self.until(lambda: self.executor.n > built, "the new run's executor to start")
        self.assertEqual(sorted(self.order()), ["anvils", "bolts"], "cogs' check still waits")


if __name__ == "__main__":
    unittest.main()
