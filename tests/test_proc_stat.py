"""A process's /proc stat and statm are read in one place, host.py.

The stat fields are counted after the command name's last `)`, since the name may hold
anything. Offline: a fixture /proc tree under a temporary directory, and this process.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import host  # noqa: E402


def stat_line(pid, comm, state, ppid, start):
    fields = [state, str(ppid)] + ["0"] * 17 + [str(start)] + ["0"] * 10
    return f"{pid} ({comm}) " + " ".join(fields) + "\n"


class ProcStat(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="proc-stat-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write(self, pid, name, text):
        (self.root / str(pid)).mkdir(exist_ok=True)
        (self.root / str(pid) / name).write_text(text)

    def test_a_command_name_holding_spaces_and_parens_keeps_its_fields(self):
        self.write(41, "stat", stat_line(41, "x) S 9 (y", "R", 7, 12345))
        self.assertEqual(host.proc_stat(41, self.root), host.ProcStat("R", 7, 12345))
        self.assertFalse(host.proc_stat(41, self.root).exited)

    def test_a_zombie_or_a_dead_task_has_exited(self):
        for pid, state in ((42, "Z"), (43, "X")):
            self.write(pid, "stat", stat_line(pid, "gone", state, 1, 5))
            self.assertTrue(host.proc_stat(pid, self.root).exited)

    def test_a_missing_or_torn_stat_reads_none(self):
        self.write(44, "stat", "44 (cut) S 1 0\n")
        self.assertIsNone(host.proc_stat(44, self.root))
        self.assertIsNone(host.proc_stat(45, self.root))

    def test_resident_bytes_are_statm_pages(self):
        self.write(46, "statm", "100 25 3 1 0 20 0\n")
        self.assertEqual(host.resident_bytes(46, self.root), 25 * os.sysconf("SC_PAGE_SIZE"))
        self.assertIsNone(host.resident_bytes(47, self.root))

    def test_this_process_reads_its_parent_and_its_identity_start(self):
        stat = host.proc_stat(os.getpid())
        self.assertEqual(stat.ppid, os.getppid())
        self.assertEqual(host.process_identity(os.getpid())["ticks"], stat.start)


if __name__ == "__main__":
    unittest.main(verbosity=2)
