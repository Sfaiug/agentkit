"""`host.idle_reading` hands on the kernel's whole numbers: the boot clock in nanoseconds, the
idle ticks of every processor (the fourth number of `/proc/stat`'s `cpu` line) and the ticks in a
second, or None where any cannot be read.  Injected readings: the key
tests/test_key_a_suite_starts_where_the_host_has_room_for_its_use.py.

Offline: a stand-in /proc (`host.PROC`), AK_HOST_READINGS unset.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import host

CPU_LINES = "cpu  4705 356 584 3699176 23 0 37 0 0 0\ncpu0 4705 356 584 3699176 23 0 37 0 0 0\n"


class TheHostReadsItsIdleProcessorTime(unittest.TestCase):
    def read(self, stat=None):
        """`idle_reading` over a /proc whose stat holds `stat`, None for no stat at all."""
        tmp = tempfile.TemporaryDirectory(prefix="idle-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        if stat is not None:
            (root / "stat").write_text(stat)
        with patch.dict(os.environ), patch.object(host, "PROC", root):
            os.environ.pop("AK_HOST_READINGS", None)
            return host.idle_reading()

    def test_the_cpu_lines_fourth_number_and_a_positive_tick_rate(self):
        reading = self.read(CPU_LINES + "procs_running 2\n")
        self.assertEqual(reading.cpu_idle_ticks, 3699176)
        self.assertGreater(reading.clk_tck, 0)
        self.assertGreater(reading.boot_ns, 0)

    def test_a_missing_stat_or_a_short_cpu_line_reads_none(self):
        self.assertIsNone(self.read())
        self.assertIsNone(self.read("cpu  4705 356 584\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
