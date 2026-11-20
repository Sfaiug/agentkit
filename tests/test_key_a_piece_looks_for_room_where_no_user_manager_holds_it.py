"""Where no systemd user manager holds a check, its piece starts beside another of its own only
while the host's cores, less every thread that wants one now, leave room for it.

Black-box, as tests/test_key_a_place_is_given_by_what_the_pieces_need_now.py, but the host's
readings (AK_HOST_READINGS) give the threads that want a core only as `procs_running`, the whole
host's count, and the lander's membership is injected (AK_CGROUP_FILE): under this user's
`user@<uid>.service`, or outside it, as in a container or under cron.
"""

import json
import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line
from test_key_a_place_is_given_by_what_the_pieces_need_now import CORES, FIT, HELD, MORE

MANAGER = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"


class APieceLooksForRoomWhereNoUserManagerHoldsIt(unittest.TestCase):
    def started_together(self, membership, running):
        """How many pieces of a member's check start side by side for a lander in `membership`
        while `running` threads want a core; the check lands once they are released."""
        line = Line({f"t/{name}.sh": HELD for name in "abcdef"})
        self.addCleanup(line.close)
        home, storage = line.home, line.rig.path / ".git"
        home.env["AK_MAX_RUNS"] = ""    # heavy suite turns
        (home.root / "cgroup").write_text(f"0::/{membership}\n")
        line.member({"fix-1.txt": "x\n"})
        lander = home.spawn("run", "--lander", line.line, env={
            "AK_CGROUP_FILE": str(home.root / "cgroup"), "AK_HOST_READINGS": json.dumps(
                {"cpus": CORES, "load": 0, "free_mb": 16000, "procs_running": running})})

        def started():
            return len(list(storage.glob("started-*")))

        for pieces, seconds in ((1, 300), (FIT, MORE)):
            deadline = time.monotonic() + seconds
            while started() < pieces and lander.poll() is None and time.monotonic() < deadline:
                time.sleep(0.2)
        together = started()
        (storage / "release").touch()
        self.assertEqual(lander.wait(timeout=300), 0, home.log("spawn-1.err").read_text())
        self.assertIn("land", line.verdict(1))
        return together

    def test_pieces_run_one_after_another_while_the_hosts_threads_fill_the_cores(self):
        self.assertEqual(self.started_together("acme.slice/acme.scope", CORES), 1)

    def test_pieces_run_side_by_side_while_the_cores_have_room_for_one(self):
        self.assertEqual(self.started_together("acme.slice/acme.scope", CORES - 1), FIT)

    def test_a_system_unit_named_like_the_user_manager_is_not_it(self):
        unit = f"system.slice/backup-user@{os.getuid()}.service"
        self.assertEqual(self.started_together(unit, CORES), 1)

    def test_pieces_under_a_user_manager_take_no_count_from_the_whole_hosts_threads(self):
        self.assertEqual(self.started_together(f"{MANAGER}/acme.slice/acme.scope", CORES), FIT)


if __name__ == "__main__":
    unittest.main()
