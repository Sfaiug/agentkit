"""A seat's own pull request's review is parked while an older live change holds its lines.

Reservation is the line-level park, never declared paths: a seat's own pull request's first
review runs the lease scan itself before any reviewer is picked (`run.park_own_review`), and a
diff that cannot merge with an older live change is stopped there, its branch kept, waiting on
that change (`leases.park`), as a task run is at ak's commit step; once the change has landed,
the tick starts the review of that pull request again for the seat (`leases.restart`), which
the seat's `ak wait` on the stopped run follows.  Another's pull request's review, and a review
past its reviewer turn, are only written down.  Offline: the lease stage (`fixtures.leases`),
a fake launch.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.leases import OLDER, YOUNGER, LiveRuns
from agentkit import config, leases, run, transitions
from agentkit import record

URL = "https://github.com/acme/widget/pull/7"


class SeatReservation(LiveRuns):
    def own_review(self, name, started, own=True, step=None, rounds=0, session="seat-b", line=5):
        """A seat's own pull request's review, as its record stands before its reviewer turn:
        its checkout holds the pull request's head, committed, changing `line`."""
        worktree = self.run_on(name, started, step=step, rounds=rounds, session=session)
        directory = config.RUNS / name
        record.save_state(directory, {**record.read_state(directory), "review_pr": URL, "pr": URL,
                                      "own_pr": own, "launch_opts": {"--review-pr": URL, "--bg": True}})
        self.edit(worktree, "api.py", line, f"the pull request's line {line}", commit=True)
        return worktree

    def holder(self):
        """An older task run still building, which changed line 5."""
        older = self.run_on(OLDER, 900, step="executor", rounds=0)
        self.edit(older, "api.py", 5, "older's line 5", commit=True)
        return older

    def test_an_own_review_whose_lines_an_older_change_holds_is_parked_before_its_reviewer_turn(self):
        self.holder()
        self.own_review(YOUNGER, 1000)
        found = leases.scan(self.repo, self.logs.append, now=2000)
        self.assertEqual(found[YOUNGER]["waits_on"], OLDER)
        state = self.state(YOUNGER)
        self.assertEqual(state["state"], "stopped")
        self.assertEqual(state["lease_wait"], {"on": OLDER, "files": ["api.py"], "since": 2000})
        self.assertIn("the younger is stopped, its branch kept, to start again once the older "
                      "has landed or is over", self.logs[-1])
        self.assertTrue(transitions.going(state))      # its seat's wait follows the restart

    def test_anothers_review_and_a_review_past_its_reviewer_turn_are_only_written_down(self):
        self.holder()
        for name, how in (("20260101-1000-theirs", {"own": False}),
                          ("20260101-1100-reviewing", {"step": "reviewer"}),
                          ("20260101-1200-second-round", {"rounds": 1, "step": "executor"})):
            self.own_review(name, 1000, **how)
        found = leases.scan(self.repo, self.logs.append, now=2000)
        self.assertEqual({name: each["waits_on"] for name, each in found.items()},
                         {"20260101-1000-theirs": OLDER, "20260101-1100-reviewing": OLDER,
                          "20260101-1200-second-round": OLDER})
        for name in found:
            self.assertEqual(self.state(name)["state"], "running", name)
        self.assertEqual([line.endswith("the younger is only written down") for line in self.logs],
                         [True, True, True])

    def test_the_review_runs_the_scan_itself_and_its_save_raises_the_stop(self):
        self.holder()
        self.own_review(YOUNGER, 1000)
        clear = "20260101-1100-clear"
        self.own_review(clear, 1100, line=15)                   # other lines: nothing in its way
        directory = config.RUNS / YOUNGER
        with self.assertRaises(record.StopRequested):
            run.park_own_review(self.repo, directory, dict(record.read_state(directory)), self.logs.append)
        self.assertEqual(self.state(YOUNGER)["lease_wait"]["on"], OLDER)
        directory = config.RUNS / clear
        run.park_own_review(self.repo, directory, dict(record.read_state(directory)), self.logs.append)
        self.assertEqual(self.state(clear)["state"], "running")        # the save went through

    def test_once_the_holder_has_landed_the_review_starts_again_for_its_seat(self):
        self.holder()
        self.own_review(YOUNGER, 1000)
        leases.scan(self.repo, now=2000)
        self.assertEqual(self.state(YOUNGER)["state"], "stopped")
        launched = []
        with patch.object(run, "preflight"), \
                patch.object(run, "spawn_bg", side_effect=lambda d, argv: launched.append((d, argv))):
            leases.restart(log=self.logs.append, now=3000)                  # the holder still going
            self.assertEqual(launched, [])
            holder = config.RUNS / OLDER
            record.save_state(holder, {**record.read_state(holder), "state": "pass", "merged": True})
            leases.restart(log=self.logs.append, now=3200)
            leases.restart(log=self.logs.append, now=3300)                  # never twice
        self.assertEqual(len(launched), 1)
        fresh, argv = launched[0]
        self.assertEqual(argv, ["--review-pr", URL])
        self.assertFalse((fresh / "task.md").exists())
        state = record.read_state(fresh)
        self.assertEqual((state["state"], state["launched_session"], state["review_pr"]),
                         ("queued", "seat-b", URL))
        self.assertEqual(state["restarted"], {"run": YOUNGER, "why": f"{OLDER} has landed"})
        self.assertEqual(self.state(YOUNGER)["lease_restarted"], fresh.name)
        self.assertIn(f"the review of {URL} starts again on the landed base",
                      (fresh / "log.txt").read_text())
        self.assertIn(f"{YOUNGER} started again as {fresh.name}: {OLDER} has landed", self.logs[-1])

    def test_the_review_started_again_keeps_the_writer_of_the_head_it_reviewed(self):
        # the seat switched models while its review was parked: the head it reviewed is still
        # the first model's work (a head pushed since: `test_review_own_pr.py`)
        self.holder()
        head = self.git(self.own_review(YOUNGER, 1000), "rev-parse", "HEAD")
        directory = config.RUNS / YOUNGER
        record.save_state(directory, {**record.read_state(directory), "own_orchestrator": "opus",
                                      "head_sha": head})
        leases.scan(self.repo, now=2000)
        holder = config.RUNS / OLDER
        record.save_state(holder, {**record.read_state(holder), "state": "pass", "merged": True})
        config.save_session(config.load(), "seat-b", "astra", ["opus", "astra"])
        info = {"state": "OPEN", "title": "Change line 5", "author": "owner", "baseRefName": "main",
                "headRefOid": head}
        launched = []
        with patch.object(run, "viewer_login", return_value="owner"), \
                patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "spawn_bg", side_effect=lambda d, argv: launched.append(d)):
            leases.restart(log=self.logs.append, now=3000)
        state = record.read_state(launched[0])
        self.assertEqual((state["own_pr"], state["own_orchestrator"], state["head_sha"]),
                         (True, "opus", head))


if __name__ == "__main__":
    unittest.main(verbosity=2)
