"""A run whose loop died is carried on by the next tick, held after a quick second death, and
parked at its third death within an hour.

A run's loop can die under its work: a kill, the host's memory, a reboot.  `ak watch` finds a
running record whose loop process is gone, records the death on it and starts the resume in the
same tick, so the work goes on with nobody asked; a death within ten minutes of that resume
waits the ten minutes out, and a third death inside an hour parks the run for a person instead
of resuming it for ever.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py; the first case kills a real run's loop mid-turn, the others are run
records whose loop is a process the test started and reaped, so it is certainly gone.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import boxable, Home
from fixtures.gitrig import Rig

# No loop of this host's boot has it: a pid the system hands out again is still not this loop.
NO_LOOP = {"boot": "acme-boot", "ticks": 0, "started_at": 0}


def record(run_dir):
    try:
        return json.loads((run_dir / "run.json").read_text())
    except (OSError, ValueError):
        return None


def wait_for(test, what, shown=lambda: "", bound=120):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}: {shown()}")
        time.sleep(0.1)


def gone_pid():
    """A process that ran and was reaped: its pid names no process now."""
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class LoopKilledMidTurn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"])
        adapters = home.root / "adapters"
        # The first turn never ends on its own, so the loop dies with the turn still going,
        # its conversation's id already handed back.
        held = adapters / "held"
        hold = {"sh": f"touch '{held}'; while [ -d '{adapters}' ]; do sleep 0.1; done"}
        cls.fakes = fakeadapter.install(home, claude=[hold, "work"], codex="pass")
        loop = home.spawn("run", str(taskfile.write(home, rig.path)), "--no-merge")
        wait_for(lambda: held.exists() or loop.poll() is not None, "started the first turn")
        assert loop.poll() is None, home.log("spawn-1.err").read_text()
        cls.run_dir = taskfile.only_run(home)
        cls.dead = record(cls.run_dir)["pid"]
        os.killpg(loop.pid, signal.SIGKILL)
        loop.wait()
        cls.before = record(cls.run_dir)
        cls.tick = home.tick()
        wait_for(lambda: (record(cls.run_dir) or {}).get("state") == "pass",
                 "finished the resumed run", lambda: (cls.run_dir / "log.txt").read_text())
        cls.state = record(cls.run_dir)
        cls.log = (cls.run_dir / "log.txt").read_text()

    def test_a_killed_loop_leaves_its_record_running_under_a_pid_that_is_gone(self):
        self.assertEqual(self.before["state"], "running")
        self.assertEqual(self.before["pid"], self.dead)
        self.assertFalse(self.before.get("deaths"))

    def test_the_tick_records_the_death_and_says_where_the_run_goes_on(self):
        self.assertEqual(self.tick.code, 0, self.tick.out + self.tick.err)
        deaths = self.state["deaths"]
        self.assertEqual(len(deaths), 1, deaths)
        self.assertEqual(deaths[0]["pid"], self.dead)
        self.assertTrue(deaths[0]["reason"].startswith(f"loop process {self.dead} gone"),
                        deaths[0])
        self.assertIn("resumed_at", deaths[0])
        self.assertFalse(deaths[0].get("parked"))
        said = [line for line in self.log.splitlines()
                if f"resumed {self.run_dir.name}: loop died" in line]
        self.assertEqual(len(said), 1, self.log)
        self.assertIn(f"(loop process {self.dead} gone", said[0])
        self.assertTrue(said[0].endswith("continuing executor of round 1"), said[0])

    def test_the_resumed_loop_finishes_the_work_in_the_dead_turns_conversation(self):
        self.assertEqual(self.state["verdict"], "PASS")
        self.assertNotEqual(self.state["pid"], self.dead)
        runs = self.fakes["claude"].runs()
        self.assertEqual([run["n"] for run in runs], [2], "the dead turn never finished")
        self.assertEqual(runs[0]["argv"][5:], ["sid-claude-1"])
        tree = self.home.run("git", "-C", self.state["worktree"], "ls-tree", "--name-only", "HEAD")
        self.assertIn("retry.txt", tree.out.split())


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class DeathsCounted(unittest.TestCase):
    """One tick over two runs whose loops are gone: one resumed two minutes ago, one resumed
    twice within the last twenty minutes."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        now = time.time()
        cls.held = cls.write("20261001-0300-fix-api", [now - 120])
        cls.parked = cls.write("20261001-0310-beta", [now - 1200, now - 900])
        cls.ticks = [home.tick(), home.tick()]

    @classmethod
    def write(cls, run_id, resumed):
        worktree = cls.home.path / ".agentkit/wt" / run_id
        worktree.mkdir(parents=True)
        deaths = [{"at": at, "pid": gone_pid(), "reason": "loop process gone", "resumed_at": at}
                  for at in resumed]
        pid = gone_pid()
        cls.home.write(f".agentkit/runs/{run_id}/run.json", {
            "run_id": run_id, "title": run_id[14:], "state": "running", "pid": pid,
            "process_identity": NO_LOOP, "started_at": resumed[0] - 60, "step": "executor",
            "rounds": 3, "worktree": str(worktree), "deaths": deaths})
        return {"dir": cls.home.path / ".agentkit/runs" / run_id, "pid": pid, "deaths": deaths}

    def said(self, run):
        try:
            return (run["dir"] / "log.txt").read_text().splitlines()
        except FileNotFoundError:
            return []

    def test_every_tick_exits_zero(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_a_death_within_ten_minutes_of_a_resume_waits_them_out(self):
        state = record(self.held["dir"])
        self.assertEqual(state["state"], "running")
        self.assertEqual(state["pid"], self.held["pid"], "nothing resumed it")
        self.assertEqual(state["deaths"][:1], self.held["deaths"])
        self.assertEqual(len(state["deaths"]), 2, state["deaths"])
        self.assertEqual(state["deaths"][1]["pid"], self.held["pid"])
        self.assertNotIn("resumed_at", state["deaths"][1])
        self.assertAlmostEqual(state["resume_after"], self.held["deaths"][0]["at"] + 600,
                               delta=1)
        said = self.said(self.held)
        self.assertEqual(len(said), 1, "the second tick holds it without a word")
        self.assertIn("waiting to resume 20261001-0300-fix-api: loop died (loop process "
                      f"{self.held['pid']} gone", said[0])
        self.assertTrue(said[0].endswith("; next try after 10 min"), said[0])

    def test_a_third_death_within_an_hour_parks_the_run_and_it_stays_parked(self):
        state = record(self.parked["dir"])
        self.assertEqual(state["state"], "interrupted")
        self.assertEqual(state["pid"], self.parked["pid"], "nothing resumed it")
        self.assertEqual(state["deaths"][:2], self.parked["deaths"])
        self.assertEqual(len(state["deaths"]), 3, state["deaths"])
        third = state["deaths"][2]
        self.assertEqual((third["pid"], third.get("parked")), (self.parked["pid"], True))
        self.assertTrue(third["reason"].startswith(f"loop process {self.parked['pid']} gone"))
        said = self.said(self.parked)
        self.assertEqual(len(said), 1, "the second tick leaves it parked without a word")
        self.assertIn("parked 20261001-0310-beta: loop died (loop process "
                      f"{self.parked['pid']} gone", said[0])
        self.assertTrue(said[0].endswith("; third death within an hour"), said[0])


if __name__ == "__main__":
    unittest.main()
