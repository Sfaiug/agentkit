"""A pair's machine reads how long ago a stamp was on two clocks, and a key sets both, and the boot.

A home asks how old its proof is at most, a standby how long its home has been silent at least:
the wall clock steps, and the clock since boot stands still while a machine is halted and begins
at nothing at a reboot.  Each clock here is the one AK_NOW sets, as a key sets it.
"""

import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import host, pair_clock, watch

WALL, SINCE, BOOT = 1_789_000_000.0, 3600.0, "acme-boot-1"
MINUTE = 60.0


def at(wall, since, boot=BOOT):
    """A clock set as AK_NOW sets it."""
    return patch.dict(os.environ, {pair_clock.NOW: f"{wall} {since} {boot}"})


def ages(wall, since, boot=BOOT):
    """The ages, at most and at least, of a stamp made at (WALL, SINCE, BOOT), read at that
    clock."""
    with at(WALL, SINCE):
        stamp = pair_clock.now()
    with at(wall, since, boot):
        return stamp.age_at_most(), stamp.age_at_least()


class TwoClocks(unittest.TestCase):
    def test_clocks_running_alike_give_the_time_that_passed(self):
        self.assertEqual(ages(WALL + 10 * MINUTE, SINCE + 10 * MINUTE), (10 * MINUTE,) * 2)

    def test_a_wall_clock_set_back_is_older_at_most_by_the_boot_clock(self):
        self.assertEqual(ages(WALL + 2 * MINUTE, SINCE + 10 * MINUTE), (10 * MINUTE, 2 * MINUTE))

    def test_a_wall_clock_set_forward_is_younger_at_least_by_the_boot_clock(self):
        self.assertEqual(ages(WALL + 18 * MINUTE, SINCE + 10 * MINUTE),
                         (18 * MINUTE, 10 * MINUTE))

    def test_a_wall_clock_set_back_before_the_stamp_is_no_age_at_least(self):
        self.assertEqual(ages(WALL - 8 * MINUTE, SINCE + 10 * MINUTE), (10 * MINUTE, 0))

    def test_after_a_reboot_only_the_wall_clock_answers(self):
        self.assertEqual(ages(WALL + 30 * MINUTE, 2 * MINUTE, "acme-boot-2"), (30 * MINUTE,) * 2)

    def test_after_a_reboot_a_stamp_later_than_now_is_older_than_any_limit_at_most(self):
        oldest, youngest = ages(WALL - 8 * MINUTE, 2 * MINUTE, "acme-boot-2")
        self.assertGreater(oldest, 24 * 60 * MINUTE)
        self.assertEqual(youngest, 0)


class AStampsLine(unittest.TestCase):
    def test_a_stamp_written_and_read_back_is_the_same(self):
        stamp = pair_clock.now()
        self.assertEqual(pair_clock.read(stamp.line()), stamp)
        with at(WALL + 0.1, SINCE / 3):
            stamp = pair_clock.now()
        self.assertEqual(pair_clock.read(stamp.line()), stamp)

    def test_a_line_that_cannot_be_read_is_no_stamp(self):
        for line in ("", "1789000000.0 3600.0", "now 3600.0 acme-boot-1",
                     "1789000000.0 3600.0 acme boot"):
            self.assertIsNone(pair_clock.read(line), line)

    def test_a_clock_that_is_no_time_is_no_stamp(self):
        for clock in ("nan", "inf", "-inf", "1e1000"):
            for line in (f"{clock} 3600.0 acme-boot-1", f"1789000000.0 {clock} acme-boot-1"):
                self.assertIsNone(pair_clock.read(line), line)
                with at(*line.split()), self.assertRaises(ValueError):
                    pair_clock.now()


class TheClockAKeySets(unittest.TestCase):
    def test_the_variable_gives_both_clocks_and_the_boot(self):
        with at(WALL, SINCE):
            self.assertEqual(pair_clock.now(), (WALL, SINCE, BOOT))
            self.assertEqual(pair_clock.boot(), BOOT)

    def test_without_it_the_module_reads_the_machines_own(self):
        with patch.dict(os.environ):
            os.environ.pop(pair_clock.NOW, None)
            before = time.time(), time.clock_gettime(time.CLOCK_BOOTTIME)
            stamp = pair_clock.now()
            after = time.time(), time.clock_gettime(time.CLOCK_BOOTTIME)
            for clock in (0, 1):
                self.assertLessEqual(before[clock], stamp[clock])
                self.assertLessEqual(stamp[clock], after[clock])
            self.assertEqual(stamp.boot,
                             Path("/proc/sys/kernel/random/boot_id").read_text().strip())

    def test_the_whole_of_ak_sees_the_boot_it_gives(self):
        with at(WALL, SINCE):
            self.assertEqual(watch.boot_id(), BOOT)
            self.assertEqual(host.process_identity(os.getpid())["boot"], BOOT)

    def test_the_module_loads_nothing_else_of_ak(self):
        loaded = subprocess.run(
            [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
             "import agentkit.pair_clock; "
             "print(sorted(name for name in sys.modules if name.startswith('agentkit')))",
             REPO], capture_output=True, text=True, check=True).stdout
        self.assertEqual(loaded.strip(), "['agentkit', 'agentkit.pair_clock']")


if __name__ == "__main__":
    unittest.main()
