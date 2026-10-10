"""A review follow-up is a deferred line in the owning seat's plan: open until its check
passes on the default branch, holding no `ak notify done`, and ticking itself once its fix is
on the default branch, while a line no run took is the seat's own and holds its done.  The
hand-in and the weighing: tests/test_followups_never_block.py; the fix runs:
tests/test_followup_runs.py.  Offline: a real repository and plan.
"""

import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox, account_home
from agentkit import config, gate, orch, plan, run, stop
from agentkit import record as run_record

SEAT = "fix-api"


class Planned(Sandbox):
    """A deferred line: open until its check passes, holding no done."""

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            config.SESSION_ENV: SEAT, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        self.stack.enter_context(patch.object(plan.os, "killpg"))
        self.repo = config.CODE / "acme"
        self.repo.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Plan test")
        self.git("config", "user.email", "plan@localhost")
        (self.repo / "base.txt").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.origin = self.root / "origin.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.repo), str(self.origin)],
                       check=True, capture_output=True)
        self.git("remote", "add", "origin", str(self.origin))
        self.git("fetch", "-q", "origin")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        config.save_session(self.cfg, SEAT, "opus", ["opus"],
                            {"cwd": str(self.root), "repo": str(self.repo)})

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_an_open_line_holding_the_check_is_kept_with_the_mark_the_call_asks(self):
        own = plan.add(SEAT, "Fix api.py:1 - mode is wrong", "test -f feature.txt", self.repo,
                       proven=self.base, deferred=False)
        self.assertFalse(plan.deferred(own))
        kept = plan.add(SEAT, "Fix api.py:1 - mode is wrong", "test -f feature.txt", self.repo,
                        proven=self.base, deferred=True)          # a run takes it ...
        self.assertEqual(kept.replace(plan.DEFERRED, ""), own)
        self.assertEqual(plan.open_lines(SEAT), [kept])           # ... no duplicate ...
        self.assertFalse(stop.owed(SEAT))                         # ... and the seat owes nothing
        self.assertEqual(plan.add(SEAT, "Fix it another way", "test -f feature.txt", self.repo,
                                  proven=self.base, deferred=False), own)   # none has it any more
        self.assertEqual(plan.open_lines(SEAT), [own])
        self.assertTrue(stop.owed(SEAT))

    def test_a_fix_run_no_run_has_any_more_gives_its_line_back_to_the_seat(self):
        def defer():
            return plan.add(SEAT, "Fix api.py:1 - mode is wrong", "test -f feature.txt", self.repo,
                            proven=self.base, deferred=True)
        deferred = defer()
        directory = config.RUNS / "fix"
        directory.mkdir(parents=True)
        (directory / "log.txt").write_text("not merged: the rebase of origin/main conflicted\n")
        fix = {"run_id": "fix", "launched_session": SEAT, "repo": str(self.repo), "base_sha": self.base,
               "followup": {"run": "source", "text": "api.py:1 - mode is wrong", "place": "api.py:1",
                            "check": "test -f feature.txt"}}
        now = time.time()
        logs = []
        for ending in ({"state": "not_needed"}, {"state": "pass", "merged": True},  # it ticks itself
                       # ... or the run is still on its way: the tick's wait on main, its retry, and
                       # the conflict it parks and resumes
                       {"state": "waiting", "waiting_on": {"ref": "origin/main"}, "finished_at": now},
                       {"state": "error", "finished_at": now, "error_retry_at": now + 3600},
                       {"state": "fail", "merge_note": "the rebase of origin/main conflicted",
                        "worktree": str(self.repo), "branch": "ak/fix-api", "base": "main",
                        "rounds": 3, "round_summaries": [{}], "finished_at": now}):
            self.assertIsNone(run.followup_returned({**fix, **ending}, directory, logs.append))
            self.assertEqual(plan.open_lines(SEAT), [deferred])

        def failed():
            run.followup_returned({**fix, "state": "fail", "finished_at": now}, directory, logs.append)

        def stopped():          # `ak run stop`
            with patch.object(orch, "user_manager", return_value=False), \
                    patch.object(stop, "marker_pids", return_value=[]):
                stop.end(directory, keep=True, why="stopped by the user", log=logs.append)

        def crashed():          # the loop raises: drive's error, which reaches no finish
            def harness():
                raise RuntimeError("the harness crashed")
            with patch.object(gate, "wait_for_slot", return_value={**fix, "state": "running"}), \
                    patch.object(run, "announce"), patch.object(run, "stop_run_tree"), \
                    patch.dict(os.environ, {"AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}):
                for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
                    os.environ.pop(name, None)
                self.assertEqual(run.drive(self.cfg, directory, {}, logs.append, job=harness), 2)

        for end in (failed, crashed, stopped):     # a stopped record takes no save after it
            run_record.save_state(directory, {**fix, "state": "running"})
            end()
            self.assertEqual(plan.open_lines(SEAT), [deferred.replace(plan.DEFERRED, "")], end.__name__)
            self.assertTrue(stop.owed(SEAT))                          # the seat's own again
            defer()
        self.assertIn("Its line is yours again, in your plan: Fix api.py:1 - mode is wrong",
                      (directory / "result.md").read_text())
        self.assertEqual(logs.count(f"follow-up for {SEAT}: Fix api.py:1 - mode is wrong (in its plan)"), 3)

    def test_a_deferred_line_is_open_yet_owed_by_nobody_and_ticks_itself(self):
        line = plan.add(SEAT, "Fix api.py:1 - mode is wrong", "test -f feature.txt", self.repo,
                        proven=self.base, deferred=True)
        self.assertIn(f" · {plan.named(self.repo)} · deferred · written ", line)
        self.assertTrue(plan.deferred(line))
        self.assertEqual(plan.open_lines(SEAT), [line])
        self.assertEqual(plan.outcomes(SEAT), [])
        proven = plan.require_done(SEAT)            # nothing owed: a done may be recorded ...
        plan.still_done(SEAT, proven)
        self.assertFalse(stop.owed(SEAT))                  # ... and no turn is held for it ...
        self.assertEqual(plan.open_lines(SEAT), [line])    # ... while the line stays open
        plan.add(SEAT, "the hero looks calm", None)          # ... and an owed line still holds it
        self.assertTrue(stop.owed(SEAT))
        with self.assertRaisesRegex(config.Error, r"1 plan line\(s\) still open"):
            plan.require_done(SEAT)
        # its fix lands: the check passes on the default branch and the line ticks
        (self.repo / "feature.txt").write_text("fixed\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Fix the follow-up")
        self.git("push", "-q", "origin", "main")
        plan.verify(SEAT)
        [ticked, _] = plan.lines(SEAT)
        self.assertRegex(ticked, r"^- \[x\] Fix api\.py:1 - mode is wrong · check: `test -f feature\.txt` · .+ · deferred · written .+ · done [0-9a-f]{12} Fix the follow-up$")
        self.assertFalse(plan.is_open(ticked))


if __name__ == "__main__":
    unittest.main(verbosity=2)
