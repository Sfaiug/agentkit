"""Where no systemd user manager holds this process and no weight can be read, `host.cpu_room` is
the cores less `/proc/stat`'s `procs_running`, the mean of five looks: no thread is left out.
Injected readings stand in for that count with their `procs_running` only where they hold no
`cpu_wanted`.

Offline: a stand-in /proc (`host.PROC`) whose count each look's sleep moves on, an injected
membership (AK_CGROUP_FILE) and an empty cgroup tree (AK_CGROUP_ROOT), so no weight is read.
"""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import host

MANAGER = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"


class CpuRoomCountsEveryThreadWhereNoUserManagerHoldsIt(unittest.TestCase):
    def room(self, membership, *counts):
        """`cpu_room` on 8 cores for a process in `membership`, each look reading the next of
        `counts`, None for a /proc/stat without the line."""
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / "cgroup").write_text(f"0::/{membership}\n")
        counts = iter(counts)

        def look(_seconds=None):
            count = next(counts)
            (root / "stat").write_text("" if count is None else f"procs_running {count}\n")

        look()
        with patch.dict(os.environ, {"AK_CGROUP_FILE": str(root / "cgroup"),
                                     "AK_CGROUP_ROOT": str(root)}), \
                patch.object(host, "PROC", root), patch.object(host, "cpu_count", return_value=8), \
                patch.object(host.time, "sleep", side_effect=look):
            os.environ.pop("AK_HOST_READINGS", None)
            return host.cpu_room()

    def test_the_cores_less_every_thread_that_wants_one(self):
        self.assertEqual(self.room("acme.slice/acme.scope", 2, 4, 4, 6, 4), 4)

    def test_none_where_the_host_shows_no_count(self):
        self.assertIsNone(self.room("acme.slice/acme.scope", None))

    def test_none_under_a_user_manager_whose_weights_cannot_be_read(self):
        self.assertIsNone(self.room(f"{MANAGER}/acme.slice/acme.scope", 2, 4, 4, 6, 4))

    def test_injected_readings_give_procs_running_only_where_they_hold_no_cpu_wanted(self):
        for given, room in (({}, 1), ({"cpu_wanted": None}, None), ({"cpu_wanted": 1}, 2)):
            readings = json.dumps({"cpus": 3, "procs_running": 2, **given})
            with self.subTest(given=given), patch.dict(os.environ, {
                    "AK_HOST_READINGS": readings, "AK_CGROUP_FILE": os.devnull}):
                self.assertEqual(host.cpu_room(), room)


if __name__ == "__main__":
    unittest.main()
