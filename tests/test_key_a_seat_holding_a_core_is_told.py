"""A seat whose own scope holds `cores.FLOOR` of a core over two ticks in a row is told so once,
and again each hour while it goes on.

From 12 to 17 Nov 2026 a seat waited on a log with `read -t 20 < /dev/zero`, which never sleeps,
and held a core for five days that nothing saw.  Each tick reads how much CPU time each seat's
scope used or waited for since the tick before (its `cpu.pressure`'s `some` total, where both
ticks read it): `cores.FLOOR` or more, averaged over the time between them, two ticks in a row,
and the seat is typed one line at its quiet prompt naming how much of a core, to one decimal, how
long, its busiest command and where a wait belongs; the tick's log says the same.  Only a
difference over a known interval counts: a seat seen first, a scope new since the last tick and a
late tick are no offence, and a process moved into a scope brings none of the CPU time it spent
before.  Nor is all a scope ever waited, where one tick of two left its waiting unread or the
version before this one saved its count without saying whether the waiting was in it
(`.agentkit/state/watch.json`): what it used counts through that, and a seat told before it is
told again no sooner for it.

Black-box: the program `AK_BIN` names ticks from outside through tests/fixtures/akbin.py, on a
stand-in cgroup tree (AK_CGROUP_ROOT, AK_CGROUP_FILE) whose CPU counters and processes the test
moves, and a clock it steps (AK_CORES_CLOCK), beside tests/fixtures/akseat.py's seats at Claude's
prompt.  No wait is real.  The file runs whole in one box (`rerun_boxed`), where the tick sees the
processes this test lists in a scope: a tick's own box (`home.tick()`) would hide them.
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
BACK, ON = "agentkit-seat-acme-back-5555eeee.scope", "agentkit-seat-acme-on-6666ffff.scope"
SAVED, HOUR = "agentkit-seat-acme-saved-7777aaaa.scope", "agentkit-seat-acme-hour-8888bbbb.scope"
START = 1_800_000_000
# Each tick's clock past START, and the CPU seconds each seat scope has used by then.  acme holds
# a core from the first interval on, after five days' use before it was first seen; acme-idle
# 0.4 of one, and a core's worth of three minutes over the late last interval; acme-once a core
# every other interval; acme-new a core in the interval before its scope was made again, at once
# holding more than its old one did; acme-waits 0.45 of one, and 0.85 over the late last interval;
# acme-slow 0.4; acme-back two cores over the first interval and none after; acme-on and acme-hour
# a core throughout; acme-saved a core over the first interval alone.  The last tick is over an
# hour after acme was first told.
TICKS = [(0, {ACME: 432_000, IDLE: 0, ONCE: 0, OLD: 0, WAITS: 0, SLOW: 0,
              BACK: 200, ON: 0, SAVED: 300, HOUR: 540}),
         (180, {ACME: 432_180, IDLE: 72, ONCE: 180, OLD: 180, WAITS: 81, SLOW: 72,
                BACK: 560, ON: 180, SAVED: 480, HOUR: 720}),
         (360, {ACME: 432_360, IDLE: 144, ONCE: 190, NEW: 1_000, WAITS: 162, SLOW: 144,
                BACK: 560, ON: 360, SAVED: 480, HOUR: 900}),
         (540, {ACME: 432_540, IDLE: 216, ONCE: 370, NEW: 1_180, WAITS: 243, SLOW: 216,
                BACK: 560, ON: 540, SAVED: 480, HOUR: 1_080}),
         (4_000, {ACME: 436_000, IDLE: 396, ONCE: 470, NEW: 1_180, WAITS: 3_184, SLOW: 1_600,
                  BACK: 560, ON: 4_000, SAVED: 480, HOUR: 4_540})]
# The CPU seconds by each tick in which a task of a scope with a `cpu.pressure` was ready and had
# none: acme-waits waits 0.15 of a core while another of its threads runs (`full` stays 0), 0.6
# with what it uses and a core over the last interval, 0.946 since it was first seen; acme-slow
# none since it was first seen, and the last four none since the 170 s each waited before that:
# the second tick finds acme-back's and acme-on's `cpu.pressure` gone, and the third back.
WAITED = [{WAITS: 0, SLOW: 60, BACK: 170, ON: 170, SAVED: 170, HOUR: 170},
          {WAITS: 27, SLOW: 60, SAVED: 170, HOUR: 170},
          {WAITS: 54, SLOW: 60, BACK: 170, ON: 170, SAVED: 170, HOUR: 170},
          {WAITS: 81, SLOW: 60, BACK: 170, ON: 170, SAVED: 170, HOUR: 170},
          {WAITS: 600, SLOW: 60, BACK: 170, ON: 170, SAVED: 170, HOUR: 170}]
# What the version before this one saved three minutes before the first tick, in microseconds
# and with no word on whether a count has the scope's waiting in it: acme-saved's without, of a
# tick that left it unread, and acme-hour's with, after two intervals of a core and the line told
# for them at that tick.
BEFORE = {SAVED: {"at": START - 180, "held": 300_000_000},
          HOUR: {"at": START - 180, "held": 530_000_000, "since": START - 540,
                 "since_held": 170_000_000, "told": START - 180, "ticks": {}}}
# The lines each seat that is told has taken by the end of each tick: acme-hour none more inside
# the hour of the one the version before told it.
TOLD = [0, 0, 1, 1, 2]
HEARD = {"acme": TOLD, "acme-waits": TOLD, "acme-on": TOLD, "acme-hour": [0, 0, 0, 0, 1]}
BOUND = 120     # seconds what a tick started may outlive it, or a typed line take to arrive
# acme's scope holds a process that spends a fifth of a second on a CPU before each tick, and a
# younger one that spent its first second there and sleeps since: the larger share of its life,
# and none of any interval.  A third spends its first second outside any seat and sleeps, moved
# into acme's scope at the tick acme is first told.
BUSY = ("# acme-busy-wait\nimport sys, time\nwhile sys.stdin.readline():\n"
        "    began = time.process_time()\n    while time.process_time() - began < 0.2:\n"
        "        pass\n    print(flush=True)\n")
HELPER = ("# acme-{}-helper\nimport sys, time\nwhile time.process_time() < 1:\n    pass\n"
          "print(flush=True)\nsys.stdin.readline()\n")


def processes():
    return {entry for entry in os.listdir("/proc") if entry.isdigit()}


def pressure(seconds):
    """The `cpu.pressure` of a cgroup that had a task ready and no CPU for it that long."""
    return (f"some avg10=0.00 avg60=0.00 avg300=0.00 total={seconds * 1_000_000}\n"
            "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")


@unittest.skipUnless(REAL_TMUX and BOXED, "no tmux, or no bwrap able to box the test here")
class ASeatHoldingACoreIsTold(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        # a collection on record from just now: one due would outlive the tick
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        home.write(".agentkit/state/watch.json", {"seat_cores": BEFORE})
        root = home.root / "cgroup"
        cls.seats = root / SERVICE / "agentkit.slice" / f"{SOCKET}.slice" / f"{SOCKET}.slice"
        membership = home.root / "membership"
        membership.write_text(f"0::/{SERVICE}/app.slice/acme.service\n")
        clock = home.root / "clock"
        home.env.update(AK_CGROUP_ROOT=str(root), AK_CGROUP_FILE=str(membership),
                        AK_CORES_CLOCK=str(clock))
        busy, helper = cls.held(BUSY), cls.held(HELPER.format("done"))
        moved = cls.held(HELPER.format("moved"))
        helper.stdout.readline()      # its second on a CPU spent
        moved.stdout.readline()       # and this one's, in no seat
        (cls.seats / ACME).mkdir(parents=True)
        # The kernel counts the waiting of the seats' slice, and a scope under it may still have
        # no `cpu.pressure`, its own `cgroup.pressure` 0: acme's has none, and what it used counts.
        (cls.seats / "cpu.pressure").write_text(pressure(900))
        procs = cls.seats / ACME / "cgroup.procs"
        procs.write_text(f"{busy.pid}\n{helper.pid}\n")
        cls.seat = {name: Seat(home, name) for name in (
            "acme", "acme-idle", "acme-once", "acme-new", "acme-waits", "acme-slow", "acme-back",
            "acme-on", "acme-saved", "acme-hour")}
        cls.ticks = []
        for tick, ((at, used), waited) in enumerate(zip(TICKS, WAITED)):
            clock.write_text(str(START + at))
            for scope in {ACME, IDLE, ONCE, OLD, NEW, WAITS, SLOW} - used.keys():
                shutil.rmtree(cls.seats / scope, ignore_errors=True)
            for scope, seconds in used.items():
                (cls.seats / scope).mkdir(exist_ok=True)
                (cls.seats / scope / "cpu.stat").write_text(
                    f"usage_usec {seconds * 1_000_000}\nuser_usec 0\nsystem_usec 0\n")
            for scope in used.keys() - waited.keys():
                (cls.seats / scope / "cpu.pressure").unlink(missing_ok=True)
            for scope, seconds in waited.items():
                (cls.seats / scope / "cpu.pressure").write_text(pressure(seconds))
            if TOLD[tick]:
                procs.write_text(f"{busy.pid}\n{helper.pid}\n{moved.pid}\n")
            busy.stdin.write("\n")
            busy.stdin.flush()
            busy.stdout.readline()
            done = cls.tick()
            deadline = time.monotonic() + BOUND
            while (any(len(cls.seat[name].lines()) < heard[tick] for name, heard in HEARD.items())
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
        self.assertNotIn("acme-moved-helper", line)
        self.assertIn("`sleep`", line)
        self.assertIn("`ak wait`", line)
        self.assertIn(line, self.ticks[2][0].out)

    def test_a_seat_still_over_an_hour_later_hears_a_second_line(self):
        heard = self.lines("acme")[-1]
        self.assertEqual(len(heard), 2, heard)
        self.assertIn("acme-busy-wait", heard[1])
        self.assertIn(heard[1], self.ticks[-1][0].out)

    def test_a_seat_given_less_than_the_floor_and_waiting_past_it_is_told_how_much_it_held(self):
        heard = self.lines("acme-waits")
        self.assertEqual([len(lines) for lines in heard], TOLD, heard)
        self.assertIn("0.6", heard[2][0])
        self.assertIn(heard[2][0], self.ticks[2][0].out)
        self.assertIn("0.9", heard[-1][1])      # what it held since it was first seen

    def test_a_seat_using_less_than_the_floor_and_waiting_for_none_hears_nothing(self):
        self.assertEqual(self.lines("acme-slow"), [[]] * len(TICKS))

    def test_a_seat_whose_waiting_is_read_again_is_not_told_of_all_it_ever_waited(self):
        self.assertEqual(self.lines("acme-back"), [[]] * len(TICKS))

    def test_a_seat_using_a_core_is_told_on_time_though_a_tick_left_its_waiting_unread(self):
        heard = self.lines("acme-on")
        self.assertEqual([len(lines) for lines in heard], TOLD, heard)
        self.assertIn("1.0", heard[2][0])       # what it used, and none of what it ever waited

    def test_a_count_the_version_before_saved_without_the_waiting_gains_none_of_it(self):
        self.assertEqual(self.lines("acme-saved"), [[]] * len(TICKS))

    def test_a_seat_the_version_before_told_is_told_again_when_its_hour_is_over(self):
        heard = self.lines("acme-hour")
        self.assertEqual([len(lines) for lines in heard], HEARD["acme-hour"], heard)

    def test_a_seat_under_the_floor_hears_nothing_however_late_a_tick(self):
        self.assertEqual(self.lines("acme-idle"), [[]] * len(TICKS))

    def test_a_seat_over_a_core_for_single_ticks_hears_nothing(self):
        self.assertEqual(self.lines("acme-once"), [[]] * len(TICKS))

    def test_a_scope_new_since_the_last_tick_is_no_offence(self):
        self.assertEqual(self.lines("acme-new"), [[]] * len(TICKS))


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
