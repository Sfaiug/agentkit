"""A seat whose own scope holds a core over two ticks in a row is told so once, and again each
hour while it goes on.

From 12 to 17 Nov 2026 a seat waited on a log with `read -t 20 < /dev/zero`, which never sleeps,
and held a core for five days that nothing saw.  Each tick reads how much CPU time each seat's
scope used or waited for since the tick before (its `cpu.pressure`'s `some` total, where it has
one): 0.9 core or more, averaged over the time between them, two ticks in a row, and the seat is
typed one line at its quiet prompt naming how long, its busiest command and where a wait
belongs; the tick's log says the same.  Only a difference over a known interval counts: a seat
seen first, a scope new since the last tick and a late tick are no offence.

Black-box: the program `AK_BIN` names ticks from outside through tests/fixtures/akbin.py, on a
stand-in cgroup tree (AK_CGROUP_ROOT, AK_CGROUP_FILE) whose CPU counters the test moves, and a
clock it steps (AK_CORES_CLOCK), beside tests/fixtures/akseat.py's seats at Claude's prompt.  No
wait is real.  The file runs whole in one box (`rerun_boxed`), where the tick sees the processes
this test lists in a scope: a tick's own box (`home.tick()`) would hide them.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import BOXED, REAL_TMUX, SOCKET, Home, rerun_boxed
from fixtures.akseat import Seat

SERVICE = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"
ACME, IDLE = "agentkit-seat-acme-89abcdef.scope", "agentkit-seat-acme-idle-0123abcd.scope"
ONCE = "agentkit-seat-acme-once-4567cdef.scope"
# acme-new's seat launched again between two ticks, in a scope of another name
OLD, NEW = "agentkit-seat-acme-new-1111aaaa.scope", "agentkit-seat-acme-new-2222bbbb.scope"
WAITS, SLOW = "agentkit-seat-acme-waits-3333cccc.scope", "agentkit-seat-acme-slow-4444dddd.scope"
START = 1_800_000_000
# Each tick's clock past START, and the CPU seconds each seat scope has used by then.  acme holds
# a core from the first interval on, after five days' use before it was first seen; acme-idle
# half of one, and a core's worth of three minutes over the late last interval; acme-once a core
# every other interval; acme-new a core in the interval before its scope was made again, at once
# holding more than its old one did; acme-waits and acme-slow 0.8 of one.  The last tick is over
# an hour after acme was first told.
TICKS = [(0, {ACME: 432_000, IDLE: 0, ONCE: 0, OLD: 0, WAITS: 0, SLOW: 0}),
         (180, {ACME: 432_180, IDLE: 90, ONCE: 180, OLD: 180, WAITS: 144, SLOW: 144}),
         (360, {ACME: 432_360, IDLE: 180, ONCE: 190, NEW: 1_000, WAITS: 288, SLOW: 288}),
         (540, {ACME: 432_540, IDLE: 270, ONCE: 370, NEW: 1_180, WAITS: 432, SLOW: 432}),
         (4_000, {ACME: 436_000, IDLE: 450, ONCE: 470, NEW: 1_180, WAITS: 3_200, SLOW: 3_200})]
# The CPU seconds by each tick in which a task of a scope with a `cpu.pressure` was ready and had
# none: acme-waits waits 0.15 of a core, while another of its threads runs (`full` stays 0), and
# acme-slow none since it was first seen.
WAITED = [{WAITS: 0, SLOW: 60}, {WAITS: 27, SLOW: 60}, {WAITS: 54, SLOW: 60},
          {WAITS: 81, SLOW: 60}, {WAITS: 600, SLOW: 60}]
TOLD = [0, 0, 1, 1, 2]      # the lines acme and acme-waits have taken by the end of each tick
BOUND = 120     # seconds what a tick started may outlive it, or a typed line take to arrive
# acme's scope holds a process that spends a fifth of a second on a CPU before each tick, and a
# younger one that spent its first second there and sleeps since: the larger share of its life,
# and none of any interval.
BUSY = ("# acme-busy-wait\nimport sys, time\nwhile sys.stdin.readline():\n"
        "    began = time.process_time()\n    while time.process_time() - began < 0.2:\n"
        "        pass\n    print(flush=True)\n")
HELPER = ("# acme-done-helper\nimport sys, time\nwhile time.process_time() < 1:\n    pass\n"
          "print(flush=True)\nsys.stdin.readline()\n")


def processes():
    return {entry for entry in os.listdir("/proc") if entry.isdigit()}


@unittest.skipUnless(REAL_TMUX and BOXED, "no tmux, or no bwrap able to box the test here")
class ASeatHoldingACoreIsTold(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        # a collection on record from just now: one due would outlive the tick
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        root = home.root / "cgroup"
        cls.seats = root / SERVICE / "agentkit.slice" / f"{SOCKET}.slice" / f"{SOCKET}.slice"
        membership = home.root / "membership"
        membership.write_text(f"0::/{SERVICE}/app.slice/acme.service\n")
        clock = home.root / "clock"
        home.env.update(AK_CGROUP_ROOT=str(root), AK_CGROUP_FILE=str(membership),
                        AK_CORES_CLOCK=str(clock))
        busy, helper = cls.held(BUSY), cls.held(HELPER)
        helper.stdout.readline()      # its second on a CPU spent
        (cls.seats / ACME).mkdir(parents=True)
        (cls.seats / ACME / "cgroup.procs").write_text(f"{busy.pid}\n{helper.pid}\n")
        cls.seat = {name: Seat(home, name) for name in ("acme", "acme-idle", "acme-once",
                                                        "acme-new", "acme-waits", "acme-slow")}
        cls.ticks = []
        for (at, used), waited, told in zip(TICKS, WAITED, TOLD):
            clock.write_text(str(START + at))
            for scope in {ACME, IDLE, ONCE, OLD, NEW, WAITS, SLOW} - used.keys():
                shutil.rmtree(cls.seats / scope, ignore_errors=True)
            for scope, seconds in used.items():
                (cls.seats / scope).mkdir(exist_ok=True)
                (cls.seats / scope / "cpu.stat").write_text(
                    f"usage_usec {seconds * 1_000_000}\nuser_usec 0\nsystem_usec 0\n")
            for scope, seconds in waited.items():
                (cls.seats / scope / "cpu.pressure").write_text(
                    f"some avg10=0.00 avg60=0.00 avg300=0.00 total={seconds * 1_000_000}\n"
                    "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")
            busy.stdin.write("\n")
            busy.stdin.flush()
            busy.stdout.readline()
            done = cls.tick()
            deadline = time.monotonic() + BOUND
            while (min(len(cls.seat[name].lines()) for name in ("acme", "acme-waits")) < told
                   and time.monotonic() < deadline):
                time.sleep(0.05)
            cls.ticks.append((done, {name: seat.lines() for name, seat in cls.seat.items()}))

    @classmethod
    def held(cls, code):
        """A process running `code`, which ends once its input does."""
        proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True)
        cls.addClassCleanup(proc.wait)
        cls.addClassCleanup(proc.stdout.close)
        cls.addClassCleanup(proc.stdin.close)
        return proc

    @classmethod
    def tick(cls):
        """One tick, waited out with every process it started."""
        before = processes()
        done = cls.home.ak("watch")
        assert done.code == 0, done.out + done.err
        deadline = time.monotonic() + BOUND
        while left := processes() - before:
            assert time.monotonic() < deadline, f"the tick left {sorted(left)} running"
            time.sleep(0.1)
        return done

    def lines(self, name):
        return [lines[name] for _, lines in self.ticks]

    def test_a_seat_over_a_core_two_ticks_in_a_row_is_told_once_naming_its_busiest_command(self):
        heard = self.lines("acme")
        self.assertEqual([len(lines) for lines in heard][:4], [0, 0, 1, 1], heard)
        [line] = heard[2]
        self.assertIn("acme-busy-wait", line)
        self.assertNotIn("acme-done-helper", line)
        self.assertIn("`sleep`", line)
        self.assertIn("`ak wait`", line)
        self.assertIn(line, self.ticks[2][0].out)

    def test_a_seat_still_over_an_hour_later_hears_a_second_line(self):
        heard = self.lines("acme")[-1]
        self.assertEqual(len(heard), 2, heard)
        self.assertIn("acme-busy-wait", heard[1])
        self.assertIn(heard[1], self.ticks[-1][0].out)

    def test_a_seat_given_less_than_a_core_and_waiting_for_the_rest_is_told(self):
        heard = self.lines("acme-waits")
        self.assertEqual([len(lines) for lines in heard], TOLD, heard)
        self.assertIn(heard[2][0], self.ticks[2][0].out)

    def test_a_seat_using_less_than_a_core_and_waiting_for_none_hears_nothing(self):
        self.assertEqual(self.lines("acme-slow"), [[]] * len(TICKS))

    def test_a_seat_under_a_core_hears_nothing_however_late_a_tick(self):
        self.assertEqual(self.lines("acme-idle"), [[]] * len(TICKS))

    def test_a_seat_over_a_core_for_single_ticks_hears_nothing(self):
        self.assertEqual(self.lines("acme-once"), [[]] * len(TICKS))

    def test_a_scope_new_since_the_last_tick_is_no_offence(self):
        self.assertEqual(self.lines("acme-new"), [[]] * len(TICKS))


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
