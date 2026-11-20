"""Where a systemd user manager holds a check but its cgroup shows no CPU weight, as under a
manager the CPU controller is not delegated to, its piece starts beside another of its own only
while the host's cores, less every thread that wants one now, leave room for it: no weight lets
any thread yield to another.

Black-box, as tests/test_key_a_piece_looks_for_room_where_no_user_manager_holds_it.py, with the
lander's membership injected under this user's `user@<uid>.service` (AK_CGROUP_FILE) and a cgroup
tree (AK_CGROUP_ROOT) in which its cgroup shows `cpu.weight`, or none.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import Line
from test_key_a_place_is_given_by_what_the_pieces_need_now import CORES, FIT, HELD, MORE
from test_key_a_piece_looks_for_room_where_no_user_manager_holds_it import MANAGER

SCOPE = f"{MANAGER}/acme.slice/acme.scope"


class APieceLooksForRoomWhereItsCpuWeightCannotBeRead(unittest.TestCase):
    def started_together(self, weight, running):
        """How many pieces of a member's check start side by side for a lander whose cgroup
        shows `weight`, None for no `cpu.weight`, while `running` threads want a core; the check
        lands once they are released."""
        line = Line({f"t/{name}.sh": HELD for name in "abcdef"})
        self.addCleanup(line.close)
        home, storage = line.home, line.rig.path / ".git"
        home.env["AK_MAX_RUNS"] = ""    # heavy suite turns
        (home.root / "cgroup").write_text(f"0::/{SCOPE}\n")
        scope = home.root / "cgroups" / SCOPE
        scope.mkdir(parents=True)
        if weight is not None:
            (scope / "cpu.weight").write_text(f"{weight}\n")
        line.member({"fix-1.txt": "x\n"})
        lander = home.spawn("run", "--lander", line.line, env={
            "AK_CGROUP_FILE": str(home.root / "cgroup"),
            "AK_CGROUP_ROOT": str(home.root / "cgroups"), "AK_HOST_READINGS": json.dumps(
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
        self.assertEqual(self.started_together(None, CORES), 1)

    def test_pieces_run_side_by_side_while_the_cores_have_room_for_one(self):
        self.assertEqual(self.started_together(None, CORES - 1), FIT)

    def test_pieces_whose_cgroup_shows_a_weight_take_no_count_from_the_whole_hosts_threads(self):
        self.assertEqual(self.started_together(100, CORES), FIT)


if __name__ == "__main__":
    unittest.main()
