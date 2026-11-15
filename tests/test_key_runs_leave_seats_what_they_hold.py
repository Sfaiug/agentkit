"""Each tick holds the runs' task cap at the runs slice's drop-in number or, lower, ak's slice's
ceiling less half again what its other children hold now, never under a third of that ceiling,
and sets nothing where no ceiling is set.

cgroups have ceilings and no reservations, so all seats keep is what the runs' cap leaves: four
harnesses died mid-turn when a seat was refused a fork (30 Oct 2026).  Now, not at their peak: a
peak only rises, and one burst held the runs at the floor for a boot (10 Nov 2026).  The numbers
are that host's: a ceiling of 7650 and a drop-in of 5355 once the user unit takes 8% of 127520
threads.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py.
The tick reads a fake cgroup tree (AK_CGROUP_ROOT, AK_CGROUP_FILE) and drop-ins in the Home, and
its systemctl records each argv and succeeds.
"""

import os
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import LOG, REFUSE, SOCKET, boxable, Home

SERVICE = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"
RUNS = f"{SOCKET}-runs.slice"


class Slice:
    """ak's slice in a fake cgroup tree, with no MemoryMax unless a test writes one, so the tick's
    memory part returns early and its task part runs all the same."""

    def __init__(self, home, ceiling=7650, dropin=5355):
        self.home = home
        root = home.root / "cgroup"
        self.dir = root / SERVICE / "agentkit.slice" / f"{SOCKET}.slice"
        (self.dir / RUNS).mkdir(parents=True)
        membership = home.root / "membership"
        membership.write_text(f"0::/{SERVICE}/app.slice/acme.service\n")
        home.env.update(AK_CGROUP_ROOT=str(root), AK_CGROUP_FILE=str(membership))
        if ceiling:
            (self.dir / "pids.max").write_text(f"{ceiling}\n")
        if dropin:
            home.write(f".config/systemd/user/{RUNS}.d/weights.conf",
                       f"[Slice]\nCPUWeight=40\nTasksMax={dropin}\n")
        config = home.path / ".agentkit" / "config.toml"     # no audit seat to open
        config.write_text(config.read_text() + "\n[audit]\non = false\n")
        self.systemctl(LOG)

    def systemctl(self, script):
        self.home.fake("systemctl", script.format(python=shlex.quote(sys.executable), name="systemctl",
                                                  log=shlex.quote(str(self.home.log("systemctl")))))

    def tasks(self, child, tasks, peak=None):
        """`child` holds `tasks` now, and has held `peak` at most where a test names one."""
        (self.dir / child).mkdir(exist_ok=True)
        (self.dir / child / "pids.current").write_text(f"{tasks}\n")
        if peak:
            (self.dir / child / "pids.peak").write_text(f"{peak}\n")

    def holds(self, cap):
        """The kernel says the runs' cap is `cap`, as after a set or a daemon-reload."""
        (self.dir / RUNS / "pids.max").write_text(f"{cap}\n")

    def tasks_of_that_host(self):
        self.tasks("seats.slice", 1611)
        self.tasks("acme-test.slice", 233)
        self.tasks(RUNS, 3672)


def caps(home):
    """Each TasksMax the ticks set on the runs slice, oldest first."""
    return [int(argv[4].removeprefix("TasksMax=")) for argv in home.calls("systemctl")
            if argv[:4] == ["--user", "set-property", "--runtime", RUNS]
            and argv[4].startswith("TasksMax=")]


def ticked(home):
    done = home.tick()
    assert done.code == 0, done.out + done.err
    return caps(home)


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class RunsLeaveSeatsWhatTheyHold(unittest.TestCase):
    def test_the_cap_leaves_half_again_what_every_other_child_holds(self):
        with Home() as home:
            slice_ = Slice(home)
            slice_.tasks_of_that_host()
            slice_.tasks("seats.slice/acme.scope", 900)  # already in its parent's count
            self.assertEqual(ticked(home), [4884])      # 7650 - (1611 + 233) * 3 // 2

    def test_what_the_others_held_at_their_peak_and_let_go_of_costs_the_runs_nothing(self):
        with Home() as home:
            slice_ = Slice(home)
            slice_.tasks("seats.slice", 300, peak=17000)
            slice_.tasks("acme-test.slice", 77, peak=9522)
            self.assertEqual(ticked(home), [5355])      # 7650 - 377 * 3 // 2 is past the drop-in

    def test_the_cap_falls_while_the_others_hold_more_and_is_back_once_they_let_go(self):
        with Home() as home:
            slice_ = Slice(home)
            slice_.tasks("seats.slice", 1611)
            slice_.holds(ticked(home)[-1])
            slice_.tasks("seats.slice", 2011)
            slice_.holds(ticked(home)[-1])
            slice_.tasks("seats.slice", 300)
            self.assertEqual(ticked(home), [7650 - 1611 * 3 // 2, 7650 - 2011 * 3 // 2, 5355])

    def test_a_cap_already_held_is_not_set_again_until_it_is_lost(self):
        with Home() as home:
            slice_ = Slice(home)
            slice_.tasks_of_that_host()
            slice_.holds(4884)
            self.assertEqual(ticked(home), [])
            slice_.holds(5355)      # a daemon-reload put the drop-in back
            self.assertEqual(ticked(home), [4884])

    def test_runs_keep_a_third_of_the_ceiling_however_much_the_seats_hold(self):
        with Home() as home:
            Slice(home).tasks("seats.slice", 7000)
            self.assertEqual(ticked(home), [2550])

    def test_an_owners_lower_number_stands(self):
        with Home() as home:
            Slice(home, dropin=1000).tasks_of_that_host()
            self.assertEqual(ticked(home), [1000])

    def test_with_no_number_in_the_runs_drop_in_the_ceiling_takes_its_place(self):
        with Home() as home:
            Slice(home, dropin="infinity")
            self.assertEqual(ticked(home), [7650])

    def test_with_no_pids_current_the_runs_keep_the_drop_ins_number(self):
        with Home() as home:
            slice_ = Slice(home)
            (slice_.dir / "seats.slice").mkdir()    # no pids controller here
            (slice_.dir / "acme-test.slice" / "pids.current").mkdir(parents=True)  # unreadable
            self.assertEqual(ticked(home), [5355])
            slice_.holds(5355)
            self.assertEqual(ticked(home), [5355])

    def test_a_ceiling_only_the_slices_drop_in_names_counts(self):
        with Home() as home:
            slice_ = Slice(home, ceiling=None)
            slice_.tasks_of_that_host()
            home.write(f".config/systemd/user/{SOCKET}.slice.d/limits.conf",
                       "[Slice]\nTasksMax=7650\n")
            self.assertEqual(ticked(home), [4884])

    def test_no_ceiling_sets_nothing(self):
        with Home() as home:
            Slice(home, ceiling=None).tasks_of_that_host()
            self.assertEqual(ticked(home), [])

    def test_memory_and_tasks_are_held_in_one_tick(self):
        with Home() as home:
            slice_ = Slice(home)
            slice_.tasks_of_that_host()
            home.write(f".config/systemd/user/{SOCKET}.slice.d/50-memory.conf",
                       "[Slice]\nMemoryMax=10G\n")
            (slice_.dir / "memory.current").write_text(str(4 * 1024 ** 3))
            self.assertEqual(ticked(home), [4884])
            self.assertTrue([argv for argv in home.calls("systemctl")
                             if argv[:4] == ["--user", "set-property", "--runtime", RUNS]
                             and argv[4].startswith("MemoryHigh=")])

    def test_a_refused_set_is_a_warning_and_the_next_tick_tries_again(self):
        with Home() as home:
            slice_ = Slice(home)
            slice_.tasks_of_that_host()
            slice_.systemctl(REFUSE)
            done = home.tick()
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertRegex(done.out, r"WARN .*TasksMax")
            self.assertEqual(ticked(home), [4884, 4884])


if __name__ == "__main__":
    unittest.main()
