"""The scoreboard shows who built each week's merged changes and how many runs the park held.

`built`: the week's merged runs split by who built the change, a seat (its change is a pull
request, `owner/repo#N`, the seat's own or another's) or a worker (a task or fix run, whose
change is a run), each with the share of its merged runs that merged in round 1.  `parks`: the
runs `leases.park` stopped that week, stamped `parked_at` on their history rows, since a
stopped run is in no other count.

Offline: a sandbox HOME with its own history database, git answering nothing, and the stop a
park makes faked to answer as `stop.end` does; overlapping scans on the lease stage
(`fixtures.leases`), its stop real.
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import OLDER, YOUNGER, LiveRuns
from agentkit import config, history, leases, record, scoreboard, stop, terminal

NOW = 1_800_000_000
WEEK = 7 * 86400


class WhoBuilt(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-built-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, value in (("HOME", root / ".agentkit"), ("RUNS", root / ".agentkit" / "runs"),
                            ("REPO", root / "toolkit")):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {"HOME": str(root), "NO_COLOR": "1"})
        env.start()
        self.addCleanup(env.stop)
        for target, name, value in ((scoreboard, "_git", lambda *args, **kw: None),
                                    (scoreboard.time, "time", lambda: NOW),
                                    (terminal, "content_width", lambda: 400)):   # a row a line
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def ended(self, name, change, *, ago=1, state="pass", rounds=1, merged=True):
        finish = NOW - ago
        history.start_run(name, repo="acme", started_at=finish - 3600, change=change)
        history.finish_run(name, final_state=state, verdict=state.upper(), finished_at=finish,
                           rounds_used=rounds, changed_lines=0 if merged else None)
        history.update_run(name, executor_tokens=80, reviewer_tokens=20)

    def test_the_built_row_splits_the_merged_runs_by_who_built_the_change(self):
        self.ended("r1", "acme/api#1")
        self.ended("r2", "acme/api#2", rounds=2)
        self.ended("r3", "acme/api#3", state="fail", merged=False)
        self.ended("t1", "t1")
        self.ended("t2", "t2", rounds=3)
        self.ended("f1", "f1", state="fail", merged=False)
        self.ended("old", "acme/api#9", ago=WEEK + 1, rounds=2)
        board = scoreboard.compute(NOW)
        self.assertEqual(board["built"], [
            {"seat_merged": 2, "seat_first_round": .5, "worker_merged": 2, "worker_first_round": .5},
            {"seat_merged": 1, "seat_first_round": 0, "worker_merged": 0, "worker_first_round": None}])
        row = [line for line in scoreboard.render() if line.startswith("built")][0]
        self.assertIn("by seats, through their PRs' reviews: 2 merged, 50% in round 1; "
                      "by workers, task and fix runs: 2 merged, 50% in round 1", row)
        # last week: one seat's change merged after a FAIL, and no worker's, so no share to show
        self.assertIn("by seats, through their PRs' reviews: 1 merged, 0% in round 1; "
                      "by workers, task and fix runs: 0 merged", row)

    def test_a_row_from_before_changes_were_recorded_is_told_by_its_record_or_by_neither(self):
        for name, saved in (("pr", {"review_pr": "https://github.com/acme/api/pull/42"}),
                            ("task", {"run_id": "task"}), ("gone", None)):
            self.ended(name, None)
            if saved is not None:
                (config.RUNS / name).mkdir(parents=True)
                record.save_state(config.RUNS / name, {**saved, "merged": True})
        self.assertEqual(scoreboard.compute(NOW)["built"][0], {
            "seat_merged": 1, "seat_first_round": 1, "worker_merged": 1, "worker_first_round": 1})

    def test_a_park_stamps_the_moment_on_the_run_s_row_and_the_week_counts_it(self):
        history.start_run("young", repo="acme", started_at=NOW - 60, change="young")
        history.start_run("other", repo="acme", started_at=NOW - 60, change="other")
        history.start_run("done", repo="acme", started_at=NOW - 60, change="done")
        wait = {"on": "old", "files": ["app.py"], "since": NOW}
        answers = {"young": {"state": "stopped", "lease_wait": wait},      # this call stopped it
                   "other": {"state": "stopped", "error": "stopped by hand"},   # stopped before
                   "done": None}                                             # ended meanwhile
        calls = []

        def end(run_dir, **kw):
            calls.append((run_dir.name, kw["keep"], kw["only_if"], kw["extra"]))
            return answers[run_dir.name]

        with patch.object(stop, "end", end):
            for name in ("young", "other", "done"):
                leases.park({"run": name}, "old", ["app.py"], NOW)
        self.assertEqual([call[0] for call in calls], ["young", "other", "done"])
        self.assertEqual(calls[0][1:], (True, leases.before_review, {"lease_wait": wait}))
        rows = {row["run_id"]: row["parked_at"] for row in history.ended_runs(0, NOW + WEEK)}
        self.assertEqual(rows, {})          # stopped rows are no ended work
        self.assertEqual(history.parks(NOW - WEEK, NOW), [NOW])
        self.assertEqual(history.parks(NOW - 2 * WEEK, NOW - WEEK), [])
        board = scoreboard.compute(NOW)
        self.assertEqual(board["parks"], [{"parked": 1}, {"parked": 0}])
        row = [line for line in scoreboard.render() if line.startswith("parks")][0]
        self.assertIn("1 runs stopped by the park to wait on an older change's lines", row)
        self.assertIn("0 runs stopped", row)

    def test_a_park_on_the_weeks_boundary_counts_once_in_the_newer_week(self):
        history.start_run("young", repo="acme", started_at=NOW - WEEK - 60)
        history.update_run("young", parked_at=NOW - WEEK)
        self.assertEqual(scoreboard.compute(NOW)["parks"], [{"parked": 1}, {"parked": 0}])

    def test_a_new_install_has_no_park_count_and_no_built_row(self):
        self.assertIsNone(history.parks(NOW - WEEK, NOW))
        board = scoreboard.compute(NOW)
        self.assertEqual((board["built"], board["parks"]), ([None, None], [None, None]))
        lines = scoreboard.render()
        self.assertIn("built     no runs ended", "\n".join(lines))
        self.assertIn("parks     not recorded", "\n".join(lines))


class OverlappingScans(LiveRuns):
    def test_a_scan_that_saw_the_run_live_moves_neither_its_park_nor_its_wait(self):
        self.collide()
        history.start_run(YOUNGER, repo=str(self.repo), started_at=1000)
        leases.scan(self.repo, now=2000)
        parked = self.state(YOUNGER)
        self.assertEqual(parked["lease_wait"]["since"], 2000)
        # an older scan that listed the younger run before that park reaches it only now
        self.assertIsNone(leases.park({"run": YOUNGER}, OLDER, ["api.py"], 2100))
        self.assertEqual(self.state(YOUNGER)["lease_wait"], parked["lease_wait"])
        self.assertEqual(history.parks(0, 3000), [2000])


if __name__ == "__main__":
    unittest.main()
