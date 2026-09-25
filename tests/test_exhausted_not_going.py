"""An `exhausted` run keeps its seat working only while the tick can resume it by itself.

A quota run waits on a window and a run off a dead reviewer waits on a reviewer: those two
`watch.resume_exhausted` brings back, by the one test `run.exhausted_wait` holds, so they
are going.  Any other `exhausted` run -- rounds spent, a stopped tool, no verdict -- waits
on nobody: it is not going, its seat reads `needs you` with the run's hand-back, and it is
in no running tally.  Offline: a fake seat, fake run receipts, the real ladder.
"""

import os
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import config, menu, notify, orch, run, watch, worker

NOW = 1_800_000_000
SPENT = ("unfinished review; done-when and review are pending at round 4, but the round "
         "budget (3) is spent; split or re-scope the task")


class ExhaustedNotGoing(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        (config.CODE / "acme" / ".git").mkdir(parents=True)
        self.repo = str(config.CODE / "acme")
        self.seat = {"name": "acme", "repo": self.repo, "path": self.repo,
                     "created": NOW - 5 * 86400, "attached": False, "exited": False,
                     "legacy": False, "resumable": False}
        config.save_session(self.cfg, "acme", "fable", ["opus"],
                            {"repo": self.repo, "cwd": self.repo})
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[self.seat]))
        self.stack.enter_context(patch.object(orch, "listing", return_value=[self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(watch, "pane_text", return_value="$ "))
        # the harness's `auth` verb, stubbed: no real adapter is asked about a real token
        self.stack.enter_context(patch.object(
            worker, "auth_ok", side_effect=lambda h, seat=False: (True, f"{h}: stub")))

    def receipt(self, name, **extra):
        """One `exhausted` run of this seat's, stopped ten minutes ago."""
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        state = {"run_id": name, "title": f"Task {name}", "state": "exhausted", "verdict": None,
                 "launched_session": "acme", "reported": False, "repo": self.repo,
                 "executor": "opus", "reviewer": "astra", "rounds": 3, "round_summaries": [],
                 "finished_at": NOW - 600, "started_at": NOW - 3600, **extra}
        run.save_state(directory, state)
        return directory, state

    def decide(self):
        harness, live = watch.look_at(self.seat, cfg=self.cfg)
        return watch.session_state("acme", NOW, session=self.seat, cfg=self.cfg,
                                   live=live, harness=harness)

    def test_a_quota_dry_run_keeps_its_seat_working(self):
        _, state = self.receipt("20260101-0900-window", quota_dry=True,
                                error="every provider is out of budget", title="Parked on a window")
        self.assertEqual(run.exhausted_wait(state), "window")
        self.assertTrue(run.going(state))
        self.assertEqual(menu.run_state_word(state), "working")
        found = self.decide()
        self.assertEqual((found["word"], found["reason"], found["since"]),
                         ("working", "1 running · Parked on a window", NOW - 3600))

    def test_b_run_off_a_dead_reviewer_keeps_its_seat_working(self):
        directory, state = self.receipt("20260101-0900-reviewer", title="Waiting for a reviewer",
                                        error="reviewer astra died on API/transport errors")
        self.assertEqual(run.exhausted_wait(state), "reviewer")
        self.assertTrue(run.going(state))
        self.assertEqual(run.parked_line(state, directory.name, now=NOW),
                         "exhausted · resumes when a reviewer is eligible")
        found = self.decide()
        self.assertEqual((found["word"], found["reason"]),
                         ("working", "1 running · Waiting for a reviewer"))

    def test_c_rounds_spent_handed_back_run_is_not_going_and_its_seat_needs_him(self):
        directory, state = self.receipt(
            "20260101-0900-spent", error=SPENT, handed_back=NOW - 590,
            recovery_notified="orchestrator",
            review_pending={"round": 4, "summary": "Re-review after the rebase of origin/main"})
        self.assertEqual(run.exhausted_wait(state), "")
        self.assertFalse(run.going(state))
        self.assertEqual(menu.run_state_word(state), "needs you")
        # the tick's own pass leaves it alone, by the same test: nothing it can bring back
        log = []
        watch.resume_exhausted(self.cfg, providers={}, workers=[], dry_run=True,
                               log=log.append, now=NOW)
        self.assertEqual(log, [])
        found = self.decide()
        self.assertEqual(found["word"], "needs you")
        self.assertEqual(found["reason"], f"run {directory.name} parked: {SPENT}")
        self.assertEqual(found["since"], NOW - 600)
        # ... above the seat's own last word, which would otherwise call it recovering
        notify.record("acme", "done", "Shipped it")
        self.assertEqual(self.decide()["word"], "needs you")
        # once he has acknowledged it the run is settled, and the seat's own word stands
        run.save_state(directory, {**state, "recovery_acknowledged_at": NOW})
        self.assertEqual(self.decide()["word"], "done")

    def test_d_such_a_run_is_in_no_running_tally(self):
        self.receipt("20260101-0900-spent", error=SPENT, handed_back=NOW - 590,
                     recovery_notified="orchestrator")
        self.receipt("20260101-1000-window", quota_dry=True, title="Parked on a window")
        tallies = run.seat_tallies((state for _, state in menu.run_records()), now=NOW)
        self.assertEqual(tallies["acme"][0], 1)
        self.assertEqual(menu.tally(tallies["acme"]), "1 running · 0 merged")
        self.assertEqual(menu.bar_tally(tallies["acme"]), "1 running")
        self.assertEqual(self.decide()["reason"], "1 running · Parked on a window")


if __name__ == "__main__":
    unittest.main()
