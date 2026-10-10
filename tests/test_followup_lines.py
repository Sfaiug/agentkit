"""A review follow-up is a deferred line in the owning seat's plan: open until its check
passes on the default branch, holding no `ak notify done` while a run of the seat is on its way
with its check, and ticking itself once its fix is on the default branch, while a line no run
has is the seat's own and holds its done.  The
hand-in and the weighing: tests/test_followups_never_block.py; the fix runs:
tests/test_followup_runs.py.  Offline: a real repository and plan.
"""

import json
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
from agentkit import config, plan, stop

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

    def fix(self, **state):
        """The fix run's record as its last writer left it: ak's own, whichever path ended it."""
        directory = config.RUNS / "fix"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "run.json").write_text(json.dumps({
            "run_id": "fix", "launched_session": SEAT, "repo": str(self.repo.resolve()),
            "base_sha": self.base, "followup": {"run": "source", "text": "api.py:1 - mode is wrong",
                                                "place": "api.py:1", "check": "test -f feature.txt"},
            **state}))
        return directory

    def test_an_open_line_holding_the_check_is_kept_with_the_mark_the_call_asks(self):
        own = plan.add(SEAT, "Fix api.py:1 - mode is wrong", "test -f feature.txt", self.repo,
                       proven=self.base, deferred=False)
        self.assertFalse(plan.deferred(own))
        kept = plan.add(SEAT, "Fix api.py:1 - mode is wrong", "test -f feature.txt", self.repo,
                        proven=self.base, deferred=True)          # a run takes it ...
        self.fix(state="running")
        self.assertEqual(kept.replace(plan.DEFERRED, ""), own)
        self.assertEqual(plan.open_lines(SEAT), [kept])           # ... no duplicate ...
        self.assertFalse(stop.owed(SEAT))                         # ... and the seat owes nothing
        self.assertEqual(plan.add(SEAT, "Fix it another way", "test -f feature.txt", self.repo,
                                  proven=self.base, deferred=False), own)   # none has it any more
        self.assertEqual(plan.open_lines(SEAT), [own])
        self.assertTrue(stop.owed(SEAT))

    def test_a_deferred_line_is_the_seats_own_again_once_no_run_is_on_its_way_with_its_check(self):
        line = plan.add(SEAT, "Fix api.py:1 - mode is wrong", "test -f feature.txt", self.repo,
                        proven=self.base, deferred=True)
        directory = self.fix()
        (directory / "log.txt").write_text("not merged: the rebase of origin/main conflicted\n")
        now = time.time()
        on_its_way = ({"state": "running"}, {"state": "queued", "slot_waiting": True},
                      {"state": "waiting", "waiting_on": {"ref": "origin/main"}, "finished_at": now},
                      {"state": "error", "finished_at": now, "error_retry_at": now + 3600},
                      {"state": "fail", "merge_note": "the rebase of origin/main conflicted",
                       "worktree": str(self.repo), "branch": "ak/fix-api", "base": "main",
                       "rounds": 3, "round_summaries": [{}], "finished_at": now})
        ended = ({"state": "pass", "merged": True, "finished_at": now},
                 {"state": "not_needed", "finished_at": now},
                 {"state": "fail", "finished_at": now},
                 {"state": "fail", "error": "killed at its memory cap", "finished_at": now},
                 {"state": "stopped", "finished_at": now},
                 {"state": "error", "finished_at": now},
                 {"state": "error", "finished_at": now - 2 * 86400, "error_retry_at": now - 60},
                 {"state": "interrupted", "deaths": [{"at": now}], "worktree": str(self.root / "gone")},
                 {"state": "running", "launched_session": "other-seat"},
                 {"state": "running", "followup": {"run": "source", "text": "api.py:1 - mode is wrong",
                                                   "place": "api.py:1", "check": "test -f other.txt"}},
                 {"state": "running", "repo": str(self.root / "elsewhere")})
        for state in on_its_way + ended:
            self.fix(**state)
            self.assertEqual(stop.owed(SEAT), state in ended, state)
            self.assertEqual(plan.open_lines(SEAT), [line])      # read so, never written
        with self.assertRaisesRegex(config.Error, r"1 plan line\(s\) still open"):
            plan.require_done(SEAT)
        self.fix(state="running")
        plan.require_done(SEAT)

    def test_a_deferred_line_is_open_yet_owed_by_nobody_and_ticks_itself(self):
        line = plan.add(SEAT, "Fix api.py:1 - mode is wrong", "test -f feature.txt", self.repo,
                        proven=self.base, deferred=True)
        self.fix(state="running")
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
