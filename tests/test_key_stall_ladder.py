"""A run silent past its 20-minute limit is climbed down a ladder by the tick, then parked.

A hung model or test would otherwise hold a slot and its seat for ever.  Every run records the
limits it launched with: 20 minutes of silence and a 6-hour ceiling on its done-when list.  The
tick measures a running run's silence from outside, by its newest write, and climbs one rung a
tick: it kills the step and the loop carries on; it kills the loop and resumes the run; then it
parks the run `stalled` and tells the seat that launched it, once.  A run silent for less is
left alone, and a dry run only says what a tick would do.  A run waiting for a slot whose
process died is started again, still waiting.  Black-box: the program `AK_BIN` names runs from
outside through tests/fixtures/akbin.py, its turns on a fake harness from fakeadapter.py that
hangs, launched from a seat of akseat.py; silence is made by back-dating the run's files.
"""

import json
import os
import signal
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

HANG = {"sh": "sleep 600"}         # a turn that prints nothing and never ends
OFFLINE = "http://127.0.0.1:9"    # a refused port: the tick's public-board reads stay on loopback


def offline_home(**env):
    home = Home()
    home.env.update(https_proxy=OFFLINE, HTTPS_PROXY=OFFLINE, no_proxy="127.0.0.1,localhost",
                    **env)
    return home


def record(run_dir):
    return json.loads((run_dir / "run.json").read_text())


def silent_for(run_dir, minutes):
    """Every file of the run last written that long ago: the silence the tick measures."""
    stamp = time.time() - minutes * 60
    for path in run_dir.rglob("*"):
        os.utime(path, (stamp, stamp), follow_symlinks=False)


def alive(pid):
    """Whether that process still runs: a zombie has ended, whoever has yet to collect it."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def until(what, test, bound=60, running=None):
    """Wait for `test` to hold; a `running` process that has ended will not make it."""
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline or running and running.poll() is not None:
            raise AssertionError(f"after {bound} s, still not: {what}")
        time.sleep(0.1)


def tick(home, *args):
    done = home.ak("watch", *args)
    assert done.code == 0, done.err
    return done


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Ladder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = offline_home()
        cls.addClassCleanup(home.close)
        rig = Rig(home, "widgets")
        akconfig.write(home, ["opus"])
        cls.seat = Seat(home, "acme")
        claude = fakeadapter.install(home, claude=HANG)["claude"]
        loop = home.spawn("run", str(taskfile.write(home, rig.path, "Add retry file")),
                          "--no-merge", env={"AGENTKIT_SESSION": "acme"})
        until("the first turn started", lambda: claude.n == 1, running=loop)
        cls.run_dir = run_dir = taskfile.only_run(home)
        cls.addClassCleanup(home.ak, "run", "stop", run_dir.name)
        cls.launched = record(run_dir)
        silent_for(run_dir, 19)
        tick(home)
        cls.at_19, cls.turns_at_19 = record(run_dir), claude.n
        silent_for(run_dir, 22)
        cls.dry = tick(home, "--dry-run").out
        cls.after_dry, cls.turns_after_dry = record(run_dir), claude.n
        silent_for(run_dir, 22)
        tick(home)
        cls.rung = [record(run_dir)]
        until("the loop started another turn", lambda: claude.n == 2)
        silent_for(run_dir, 22)
        tick(home)
        cls.rung.append(record(run_dir))
        until("the first loop ended", lambda: loop.poll() is not None)
        until("a new loop took the run", lambda: record(run_dir)["pid"] != cls.launched["pid"]
              and claude.n == 3)
        cls.resumed = record(run_dir)
        silent_for(run_dir, 22)
        tick(home)
        cls.rung.append(record(run_dir))
        cls.told = cls.seat.wait_lines(1)
        until("the parked loop ended", lambda: not alive(cls.resumed["pid"]))
        tick(home)
        cls.later, cls.told_later, cls.turns = record(run_dir), cls.seat.lines(), claude.n

    def test_a_run_records_the_silence_limit_and_the_done_when_ceiling_it_launched_with(self):
        self.assertEqual((self.launched["silence_minutes"], self.launched["ceiling_hours"]),
                         (20, 6))

    def test_a_run_silent_for_less_than_its_limit_is_left_alone(self):
        self.assertEqual((self.at_19["state"], self.at_19["stalls"], self.at_19["pid"]),
                         ("running", [], self.launched["pid"]))
        self.assertEqual(self.turns_at_19, 1)

    def test_a_dry_run_names_the_silent_run_and_changes_nothing(self):
        self.assertIn(self.run_dir.name, self.dry)
        self.assertEqual((self.after_dry["state"], self.after_dry["stalls"]), ("running", []))
        self.assertEqual(self.turns_after_dry, 1)

    def test_the_first_rung_kills_the_step_and_the_loop_carries_on_with_another_turn(self):
        first = self.rung[0]
        self.assertEqual([(stall["round"], stall["action"]) for stall in first["stalls"]],
                         [(1, "killed step")])
        self.assertEqual((first["state"], first["pid"]), ("running", self.launched["pid"]))

    def test_the_second_rung_ends_the_loop_and_a_new_one_resumes_the_run(self):
        second = self.rung[1]
        self.assertEqual([stall["action"] for stall in second["stalls"]],
                         ["killed step", "resumed"])
        self.assertEqual(self.resumed["state"], "running")
        self.assertEqual((self.resumed["worktree"], self.resumed["branch"]),
                         (self.launched["worktree"], self.launched["branch"]))

    def test_the_third_rung_parks_the_run_stalled_with_nothing_of_it_running(self):
        third = self.rung[2]
        self.assertEqual(third["state"], "stalled")
        self.assertEqual([(stall["round"], stall["action"]) for stall in third["stalls"]],
                         [(1, "killed step"), (1, "resumed"), (1, "parked")])
        self.assertFalse(alive(self.resumed["pid"]))

    def test_the_launching_seat_is_told_once_how_to_resume_it(self):
        name = self.run_dir.name
        line, = self.told
        # what it names as the step is left out: it is the box's command line, not the step
        self.assertTrue(line.startswith(f"run {name} stalled three times at "), line)
        self.assertTrue(line.endswith(f"; parked: ak run resume {name}"), line)
        self.assertEqual(self.told_later, self.told)

    def test_a_later_tick_leaves_the_parked_run_where_it_is(self):
        self.assertEqual((self.later["state"], len(self.later["stalls"])), ("stalled", 3))
        self.assertEqual(self.turns, 3)


class SlotWaiter(unittest.TestCase):
    def test_a_queued_run_whose_waiting_process_died_waits_again_in_a_new_one(self):
        # one run at a time, and the slot asked every second rather than every half minute
        home = offline_home(AK_MAX_RUNS="1", AK_SLOT_POLL="1")
        self.addCleanup(home.close)
        first, second = Rig(home, "widgets"), Rig(home, "gadgets")
        akconfig.write(home, ["opus"])
        claude = fakeadapter.install(home, claude=HANG)["claude"]
        holding = home.spawn("run", str(taskfile.write(home, first.path, "Add retry file")),
                             "--no-merge")
        until("the first run started", lambda: claude.n == 1, bound=120, running=holding)
        holder, = taskfile.runs(home)
        self.addCleanup(home.ak, "run", "stop", holder.name)
        waiter = home.spawn("run", str(taskfile.write(home, second.path, "Add gadget file")),
                            "--no-merge")

        def queued():
            found = [run for run in taskfile.runs(home) if run != holder]
            return found and (found[0] / "run.json").is_file() and record(found[0]).get(
                "slot_waiting")

        until("the second run waits for the slot", queued, bound=120, running=waiter)
        waiting, = (run for run in taskfile.runs(home) if run != holder)
        self.addCleanup(home.ak, "run", "stop", waiting.name)
        self.assertEqual(record(waiting)["state"], "queued")
        os.killpg(waiter.pid, signal.SIGKILL)
        waiter.wait()
        tick(home)
        # the tick starts the new waiter, which writes itself into the record a moment later
        until("a new process waits for the slot",
              lambda: record(waiting).get("pid") not in (None, waiter.pid), bound=60)
        state = record(waiting)
        self.assertEqual((state["state"], state["slot_waiting"]), ("queued", True))
        self.assertTrue(alive(state["pid"]))
        self.assertEqual(claude.n, 1)


if __name__ == "__main__":
    unittest.main()
