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
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox, account_home
from agentkit import config, plan

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

    def test_a_deferred_line_is_open_yet_owed_by_nobody_and_ticks_itself(self):
        line = plan.add(SEAT, "Fix api.py:1 - mode is wrong", "test -f feature.txt", self.repo,
                        proven=self.base, deferred=True)
        self.assertIn(f" · {plan.named(self.repo)} · deferred · written ", line)
        self.assertTrue(plan.deferred(line))
        self.assertEqual(plan.open_lines(SEAT), [line])
        self.assertEqual(plan.outcomes(SEAT), [])
        proven = plan.require_done(SEAT)            # nothing owed: a done may be recorded ...
        plan.still_done(SEAT, proven)
        self.assertEqual(plan.open_lines(SEAT), [line])    # ... while the line stays open
        plan.add(SEAT, "the hero looks calm", None)          # ... and an owed line still holds it
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
