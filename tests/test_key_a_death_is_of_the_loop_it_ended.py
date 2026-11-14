"""A recorded death is of the loop it ended, never of a later one.

A run's record keeps its loops' deaths, and a seat's `ak run resume` starts a new loop and leaves
them as they were.  An entry noted before the record's loop started (its `process_identity`) is
an earlier loop's, even where that loop's pid came round again: the new loop's own death is
recorded and judged afresh, counted with the deaths of the last hour, and a park an earlier
loop's death carries holds that loop alone.  Each case holds whether the tick notices the death
first or `ak run status` does.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on run records whose loop is a process the test started and reaped, so
it is certainly gone, under this boot of the host but at a tick no loop of it has.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

FIRSTS = ("tick", "status")     # who notices the loop's death first
BOOT = Path("/proc/sys/kernel/random/boot_id").read_text().strip()    # the host stays up


def record(run_dir):
    return json.loads((run_dir / "run.json").read_text())


def gone_pid():
    """A process that ran and was reaped: its pid names no process now."""
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ADeathIsOfTheLoopItEnded(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        cls.now = now = time.time()
        cls.runs, cls.seats = {}, {}
        for first in FIRSTS:
            # A seat's resume answered the earlier loop's death, which a reap noted, and that
            # loop's pid came round to the new one: the third death within the hour, then the
            # first.
            cls.write(f"third-{first}", started=now - 1100, deaths=[
                {"at": now - 1500, "resumed_at": now - 1500},
                {"at": now - 1200, "pid": "loop"}])
            cls.write(f"first-{first}", started=now - 3900, deaths=[
                {"at": now - 4000, "pid": "loop"}])
            # The tick parked the run at its third death and its seat resumed it; the new loop
            # dies more than an hour on, its seat at its prompt.
            cls.seats[first] = Seat(home, f"acme-{first}")
            cls.write(f"resumed-{first}", started=now - 4700, launched_session=f"acme-{first}",
                      deaths=[{"at": now - 5400, "resumed_at": now - 5400},
                              {"at": now - 5000, "resumed_at": now - 5000},
                              {"at": now - 4800, "pid": "loop", "parked": True}])
            # The tick parked the run at its third death and nobody resumed it.
            cls.write(f"parked-{first}", state="interrupted", started=now - 2000,
                      recovery_pending=True, interrupted_at=now - 900,
                      interruption_reason="loop process gone",
                      deaths=[{"at": now - 1500, "resumed_at": now - 1500},
                              {"at": now - 1200, "resumed_at": now - 1200},
                              {"at": now - 900, "pid": "loop", "parked": True}])
        cls.looks = {name: home.ak("run", "status", run["dir"].name)
                     for name, run in cls.runs.items() if name.endswith("-status")}
        cls.ticks = [home.tick(), home.tick()]

    @classmethod
    def write(cls, name, *, started, deaths, state="running", **fields):
        run_id = f"20261111-0300-{name}"
        worktree = cls.home.path / ".agentkit/wt" / run_id
        worktree.mkdir(parents=True)
        pid = gone_pid()
        deaths = [{"pid": pid if death.get("pid") == "loop" else gone_pid(),
                   "reason": "loop process gone", **{k: v for k, v in death.items() if k != "pid"}}
                  for death in deaths]
        cls.home.write(f".agentkit/runs/{run_id}/run.json", {
            "run_id": run_id, "title": name, "state": state, "pid": pid,
            "process_identity": {"boot": BOOT, "ticks": 0, "started_at": started},
            "started_at": cls.now - 6000, "step": "executor", "rounds": 3,
            "worktree": str(worktree), "deaths": deaths, **fields})
        cls.runs[name] = {"dir": cls.home.path / ".agentkit/runs" / run_id, "pid": pid,
                          "deaths": deaths}

    def said(self, run):
        try:
            return (run["dir"] / "log.txt").read_text().splitlines()
        except FileNotFoundError:
            return []

    def test_every_command_exits_zero(self):
        for done in [*self.looks.values(), *self.ticks]:
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_a_third_death_within_the_hour_is_recorded_and_parks_the_run(self):
        for first in FIRSTS:
            with self.subTest(first=first):
                run = self.runs[f"third-{first}"]
                state = record(run["dir"])
                self.assertEqual(state["state"], "interrupted")
                self.assertEqual(state["pid"], run["pid"], "nothing resumed it")
                self.assertEqual(state["deaths"][:2], run["deaths"])
                self.assertEqual(len(state["deaths"]), 3, state["deaths"])
                third = state["deaths"][2]
                self.assertEqual((third["pid"], third.get("parked")), (run["pid"], True))
                self.assertGreaterEqual(third["at"], self.now)
                said = [line for line in self.said(run) if "loop died" in line]
                self.assertEqual(len(said), 1, said)
                self.assertIn(f"parked {run['dir'].name}: loop died (", said[0])
                self.assertTrue(said[0].endswith("; third death within an hour"), said[0])

    def test_a_first_death_in_the_hour_is_recorded_and_resumed_at_once(self):
        for first in FIRSTS:
            with self.subTest(first=first):
                self.assert_resumed(self.runs[f"first-{first}"])

    def test_a_parked_run_its_seat_resumed_is_resumed_and_its_seat_told_nothing(self):
        for first in FIRSTS:
            with self.subTest(first=first):
                self.assertEqual(self.seats[first].lines(), [])
                self.assert_resumed(self.runs[f"resumed-{first}"])

    def test_a_parked_run_nobody_resumed_stays_parked(self):
        for first in FIRSTS:
            with self.subTest(first=first):
                run = self.runs[f"parked-{first}"]
                state = record(run["dir"])
                self.assertEqual(state["state"], "interrupted")
                self.assertEqual(state["pid"], run["pid"])
                self.assertEqual(state["deaths"], run["deaths"])
                self.assertNotIn("stall_resume_at", state)
                self.assertEqual([line for line in self.said(run) if "loop died" in line], [])

    def assert_resumed(self, run):
        state = record(run["dir"])
        self.assertEqual(state["deaths"][:-1], run["deaths"])
        death = state["deaths"][-1]
        self.assertEqual(death["pid"], run["pid"])
        self.assertGreaterEqual(death["at"], self.now)
        self.assertGreaterEqual(death["resumed_at"], death["at"])
        self.assertFalse(death.get("parked"))
        said = [line for line in self.said(run) if "loop died" in line]
        self.assertEqual(len(said), 1, said)
        self.assertIn(f"resumed {run['dir'].name}: loop died (", said[0])


if __name__ == "__main__":
    unittest.main()
