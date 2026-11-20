"""The `tests:` line runs no suite in a sandbox that does not hold its host's unread notes
(`net.unix.max_dgram_qlen`).  The line wrote the value and started the suite whether or not the
write took: under a /proc/sys mounted read-only the suite ran holding the kernel's 10 for a host's
37, the hang the copy was to end.

Real namespaces, as test_the_offline_sandbox_holds_its_host_s_unread_notes.py, whose namespace
holding 37 this one mounts /proc/sys/net read-only in.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_a_helper_piece_holds_a_hosts_unread_notes import READ_ONLY
from test_the_offline_sandbox_holds_its_host_s_unread_notes import line


class UncopiedQueueLimit(unittest.TestCase):
    def test_a_read_only_proc_sys_runs_no_suite(self):
        code, printed, said = line(f"{READ_ONLY} && ")
        self.assertEqual((code, printed), (1, []), said)


if __name__ == "__main__":
    unittest.main(verbosity=2)
