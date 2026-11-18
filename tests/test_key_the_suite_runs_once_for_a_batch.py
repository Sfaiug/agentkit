"""On a busy host a lander starts no whole run of a suite before its line has waited: without
room for all its pieces at once, though some fit or what takes the rest runs outside ak's
runs, a pass starts none until the line's longest-ready member without a verdict has been in
line two hours, for a suite whose last green check took 40 minutes, then checks everyone ready
together, so one whole run covers two hours of changes; a member the pass would not check, its
own process still running, opens no wait however long it has been in line.  With room for all
its pieces nothing waits, nor does a line holding a run launched `--first`, nor a project with no
suite, though a suite only a member's branch declares waits like any, even where a member
stacked on it declares none again.  What the line already holds green is delivered whatever the
host's load: no suite starts for it.

Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py, with the host's readings injected (AK_HOST_READINGS) and the clock
moved by putting the members' joins back, the suite's length on record where ak keeps it.  The
Home here drops the test suites' `AK_MAX_RUNS=0`, which lifts every host gate, this one too.
"""

import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import owner
from fixtures.akline import SUITE, Line, rules

HOUR = 3600
# A piece unmeasured costs 0.7 of a processor: four fit five pieces.
BUSY = {"cpus": 4, "load": 2, "free_mb": 16000}     # idle processors for two
IDLE = {"cpus": 4, "load": 0.5, "free_mb": 16000}   # room for all five


class TheSuiteRunsOnceForABatch(unittest.TestCase):
    def setUp(self):
        self.line = Line({"t/ok.sh": "true\n"})
        self.addCleanup(self.line.close)
        self.line.home.env.pop("AK_MAX_RUNS")
        self.line.measured(40 * 60)

    def join(self, files=(), **fields):
        """Park the next member, joined now, its branch adding `files` too and its record
        holding `fields` besides."""
        self.line.member({f"member-{len(self.line.members) + 1}.txt": "x\n", **dict(files)})
        self.change(self.line.members[-1], lambda state: (
            state.update(fields), state["waiting_on"].update(joined=time.time())))

    def later(self, seconds):
        """The clock `seconds` on: every member joined that much earlier."""
        for directory in self.line.members:
            self.change(directory, lambda state: state["waiting_on"].update(
                joined=state["waiting_on"]["joined"] - seconds))

    @staticmethod
    def change(directory, edit):
        path = directory / "run.json"
        state = json.loads(path.read_text())
        edit(state)
        fresh = path.with_name("run.json.new")
        fresh.write_text(json.dumps(state))
        fresh.replace(path)

    def land(self, readings):
        """One lander pass over the line on a host reading `readings`."""
        done = self.line.home.ak("run", "--lander", self.line.line, timeout=600,
                                 env={"AK_HOST_READINGS": json.dumps(readings)})
        self.assertEqual(done.code, 0, done.out + done.err)

    def checked(self):
        """How many whole runs of the suite, and which members got a verdict to land."""
        return self.line.whole(), ["land" in self.line.verdict(n)
                                   for n in range(1, len(self.line.members) + 1)]

    def test_on_a_busy_host_two_members_an_hour_apart_are_checked_whole_once_together(self):
        self.join()
        self.land(BUSY)
        self.later(HOUR)
        self.join()
        self.land(BUSY)
        self.later(HOUR - 600)      # ten minutes short of the first's two hours
        self.land(BUSY)
        self.assertEqual(self.checked(), (0, [False, False]), self.line.runs())
        self.later(600)
        self.land(BUSY)
        self.assertEqual(self.checked(), (1, [True, True]), self.line.runs())

    def test_with_room_for_all_its_pieces_a_member_is_checked_at_once(self):
        self.join()
        self.land(IDLE)
        self.assertEqual(self.checked(), (1, [True]), self.line.runs())

    def test_cores_busy_outside_aks_runs_leave_no_room_for_all_its_pieces(self):
        self.join()
        self.land({**IDLE, "load": 3, "slice_cpu_quota": 4, "slice_cpu_used": 0,
                   "outside_cpu_used": 3})
        self.assertEqual(self.checked(), (0, [False]), self.line.runs())

    def test_a_member_launched_first_is_checked_at_once_on_a_busy_host(self):
        self.join(first=True)
        self.land(BUSY)
        self.assertEqual(self.checked(), (1, [True]), self.line.runs())

    def test_a_member_on_a_tree_the_line_holds_green_is_delivered_on_a_busy_host(self):
        self.join()
        self.land(IDLE)
        # its verdict unwritten, as a pass killed after it kept the green left it
        self.change(self.line.members[0], lambda state: state.update(
            waiting_on={key: state["waiting_on"][key] for key in ("line", "joined")}))
        self.land(BUSY)
        self.assertEqual(self.checked(), (1, [True]), self.line.runs())

    def test_a_suite_only_a_members_branch_declares_waits_like_any(self):
        self.line.rig.commit({"AGENTS.md": rules("none")})
        self.join({"AGENTS.md": rules(SUITE)})
        self.land(BUSY)
        self.assertEqual(self.checked(), (0, [False]), self.line.runs())
        self.later(2 * HOUR)
        self.land(BUSY)
        self.assertEqual(self.checked(), (1, [True]), self.line.runs())

    def test_a_suite_a_member_declares_waits_though_one_stacked_on_it_declares_none(self):
        self.line.rig.commit({"AGENTS.md": rules("none")})
        self.join({"AGENTS.md": rules(SUITE)})
        self.join()
        # the second's branch stands on the first's, and its AGENTS.md declares no suite again
        rig, (first, second) = self.line.rig, self.line.members
        rig.git("checkout", "-q", f"ak/{second.name}")
        rig.git("reset", "-q", "--hard", f"ak/{first.name}")
        head = rig.commit({"AGENTS.md": rules("none"), "member-2.txt": "x\n"}, push=False)
        rig.git("checkout", "-q", "main")
        tree = rig.git("rev-parse", f"{head}^{{tree}}")
        self.change(second, lambda state: state["review"].update(
            head_sha=head, passed_head_sha=head, tree_sha=tree))
        self.land(BUSY)
        self.assertEqual(self.checked(), (0, [False, False]), self.line.runs())
        self.later(2 * HOUR)
        self.land(BUSY)
        self.assertEqual(self.checked(), (1, [True, True]), self.line.runs())

    def test_a_member_whose_process_still_runs_opens_no_wait(self):
        self.join()
        self.later(3 * HOUR)
        self.join()
        live = subprocess.Popen(["cat"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
        self.addCleanup(live.wait)
        self.addCleanup(live.stdin.close)
        self.change(self.line.members[0], lambda state: state.update(owner(live.pid)))
        self.land(BUSY)
        self.assertEqual(self.checked(), (0, [False, False]), self.line.runs())

    def test_a_project_without_a_suite_lands_at_once_on_a_busy_host(self):
        self.line.rig.commit({"AGENTS.md": rules("none")})
        self.join()
        self.land(BUSY)
        self.assertEqual(self.checked(), (0, [True]), self.line.runs())


if __name__ == "__main__":
    unittest.main()
