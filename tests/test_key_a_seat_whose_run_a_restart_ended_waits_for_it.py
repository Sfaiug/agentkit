"""A seat whose run a restart ended waits for it.

A seat resting at its prompt with an open line in its plan rests on a run of its own while that
run goes.  A restart of the host ends the run's loop, and the next tick resumes it: until then the
run is no less going, so in that tick the seat is told nothing and a new loop takes the run over,
whether the tick notices the ending first or a look does (`ak run status`, as the menu's `ak orch`
does after a restart).  A run the tick parks instead, at its third death within an hour, is the
seat's again, and it is told to go on.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, before seats of tests/fixtures/akseat.py whose hooks fire as
Claude fires them (tests/fixtures/hookdrive.py).  Each restarted run is a real one whose turns
never end (tests/fixtures/fakeadapter.py), its loop killed mid-turn and its record put under
another boot, as a restart leaves it; the parked one is a record whose loop is a process the test
started and reaped.  The file runs whole in one box (`rerun_boxed`), where a tick leaves the loops
it resumes running.
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
from fixtures import akconfig, fakeadapter, hookdrive, taskfile
from fixtures.akbin import BOXED, REAL_TMUX, Home, rerun_boxed
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

BOOT = Path("/proc/sys/kernel/random/boot_id").read_text().strip()    # the host's boot now


def record(run_dir):
    return json.loads((run_dir / "run.json").read_text())


def until(what, test, bound=120, shown=lambda: ""):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"after {bound} s, still not: {what} {shown()}")
        time.sleep(0.1)


def gone_pid():
    """A process that ran and was reaped: its pid names no process now."""
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


@unittest.skipUnless(REAL_TMUX and BOXED, "no tmux, or no bwrap able to box the test here")
class ASeatWhoseRunARestartEndedWaitsForIt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        cls.hooks = hookdrive.Hooks(home)
        adapters = home.root / "adapters"
        hold = {"sh": f"while [ -d '{adapters}' ]; do sleep 0.1; done"}
        cls.claude = fakeadapter.install(home, claude=[hold] * 4)["claude"]
        now = time.time()
        # the tick notices the restart's ending first, or a look does
        cls.runs = {name: cls.restarted(name) for name in ("restarted", "looked")}

        # two deaths of its own within the hour, and a third while the host stays up
        parked = home.path / ".agentkit/runs/20261124-0900-parked"
        worktree = home.path / ".agentkit/wt" / parked.name
        worktree.mkdir(parents=True)
        home.write(f".agentkit/runs/{parked.name}/run.json", {
            "run_id": parked.name, "title": "parked", "state": "running", "step": "reviewer",
            "rounds": 3, "started_at": now - 6000, "worktree": str(worktree),
            "launched_session": "parked", "pid": gone_pid(),
            "process_identity": {"boot": BOOT, "ticks": 0, "started_at": now - 600},
            "deaths": [{"pid": gone_pid(), "reason": "loop process gone", "at": at,
                        "resumed_at": at} for at in (now - 1200, now - 900)]})
        cls.runs["parked"] = {"seat": cls.turn("parked"), "dir": parked}

        for name, run in cls.runs.items():
            cls.stop(run["seat"])
            if name != "restarted":
                done = home.ak("run", "status", run["dir"].name)    # the look that notices it
                assert done.code == 0, done.out + done.err
            run["ticked"] = record(run["dir"])
        cls.ticked = home.ak("watch")
        until("a new loop took each restarted run", lambda: cls.claude.n == 4,
              shown=lambda: [(run["dir"] / "log.txt").read_text() for run in cls.runs.values()])
        time.sleep(0.5)     # keys reach the pane a moment after tmux takes them

    @classmethod
    def restarted(cls, name):
        """A seat given a turn, and a run of its own in its first turn, its loop killed and its
        record put under the boot a restart ended."""
        seat, began = cls.turn(name), cls.claude.n
        rig = Rig(cls.home, f"{name}-api")
        before = set(taskfile.runs(cls.home))
        loop = cls.home.spawn("run", str(taskfile.write(cls.home, rig.path, f"Fix {name} api")),
                              "--no-merge", env={"AGENTKIT_SESSION": name})
        until(f"{name}'s first turn began", lambda: cls.claude.n > began or loop.poll() is not None)
        assert loop.poll() is None, f"{name}'s run ended before its first turn"
        run_dir, = set(taskfile.runs(cls.home)) - before
        cls.addClassCleanup(cls.home.ak, "run", "stop", run_dir.name)
        os.killpg(loop.pid, signal.SIGKILL)
        loop.wait()
        state = record(run_dir)
        state["process_identity"]["boot"] = "acme-boot-1"
        (run_dir / "run.json").write_text(json.dumps(state, indent=1))
        return {"seat": seat, "dir": run_dir, "dead": state["pid"]}

    @classmethod
    def turn(cls, name):
        """A seat the owner has given a turn, its plan's line open."""
        seat = Seat(cls.home, name, screen="claude-working-pane.txt", planned=True)
        cls.hooks.prompt("Build the acme parser.", seat)
        return seat

    @classmethod
    def stop(cls, seat):
        """That seat's turn ends at its prompt, on its run, and its hook lets the stop stand."""
        seat.show("claude-prompt-pane.txt")
        chat = hookdrive.transcript(cls.home, seat.name, "The parser is in review.")
        fired = cls.hooks.fire("Stop", {"background_tasks": [], "stop_hook_active": False,
                                        "transcript_path": chat}, seat=seat.name, pane=seat)
        assert fired.code == 0 and not any(out.get("decision") == "block" for out in fired.said), \
            (fired.err, fired.said)

    def test_the_tick_exits_zero(self):
        self.assertEqual(self.ticked.code, 0, self.ticked.out + self.ticked.err)

    def test_the_tick_finds_one_restarted_run_running_and_one_a_look_found_ended(self):
        for name, state in (("restarted", "running"), ("looked", "interrupted")):
            with self.subTest(name):
                self.assertEqual(self.runs[name]["ticked"]["state"], state)

    def test_a_seat_whose_run_a_restart_ended_is_told_nothing_and_a_new_loop_takes_the_run(self):
        for name in ("restarted", "looked"):
            with self.subTest(name):
                run = self.runs[name]
                self.assertEqual(run["seat"].lines(), [])
                state = record(run["dir"])
                self.assertEqual(state["state"], "running")
                self.assertNotEqual(state["pid"], run["dead"])
                self.assertEqual(state["process_identity"]["boot"], BOOT)
                self.assertTrue(state["deaths"][-1].get("restart"), state["deaths"])

    def test_a_seat_whose_run_is_parked_on_its_third_death_goes_on(self):
        run = self.runs["parked"]
        state = record(run["dir"])
        self.assertEqual((state["state"], state["deaths"][-1].get("parked")), ("interrupted", True))
        self.assertEqual(run["seat"].wait_lines(1)[0], "continue")


if __name__ == "__main__":
    rerun_boxed()
    unittest.main(verbosity=2)
