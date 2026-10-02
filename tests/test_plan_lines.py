"""`ak plan add` writes an outcome with the check that proves it, only when that check fails on
the project's default branch; `--eye` lines are ticked on the owner's word, check lines never by
hand.

Offline: a throwaway HOME, a real git checkout whose origin is itself, and the check run there.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from test_v4n import Sandbox
from agentkit import config, plan


class PlanLines(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            config.SESSION_ENV: "fix-api", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1"}))
        self.repo = config.CODE / "acme"
        self.repo.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Plan test")
        self.git("config", "user.email", "plan@localhost")
        (self.repo / "base.txt").write_text("base\n")
        self.commit("base")
        self.git("remote", "add", "origin", str(self.repo))
        self.git("fetch", "-q", "origin")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.git("checkout", "-q", "-b", "work")
        (self.repo / "feature.txt").write_text("done\n")
        self.commit("the work, not on main")
        config.save_session(self.cfg, "fix-api", "opus", ["opus"],
                            {"cwd": str(self.root), "repo": str(self.repo)})

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-q", "-m", message)

    def ak(self, *args):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(plan.main(list(args)), 0)
        return out.getvalue()

    def plan_lines(self):
        return config.plan_path("fix-api").read_text().splitlines()

    def test_a_check_failing_on_main_is_written_and_listed(self):
        line = self.ak("add", "the feature exists", "--check", "test -f feature.txt").strip()
        self.assertRegex(line, r"^- \[ \] the feature exists · check: `test -f feature.txt` · "
                               r"acme · written \d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertEqual(self.plan_lines(), [line])
        self.assertEqual(self.ak().strip(), f"1  {line}")
        self.assertTrue(plan.LINE.match(line))

    def test_a_check_passing_on_main_proves_nothing_and_is_refused(self):
        with self.assertRaisesRegex(config.Error, "already passes on acme's default branch"):
            plan.main(["add", "the base exists", "--check", "test -f base.txt"])
        self.assertFalse(config.plan_path("fix-api").exists())
        with self.assertRaisesRegex(config.Error, "without backticks"):
            plan.main(["add", "quoted", "--check", "test `true`"])

    def test_the_check_runs_without_the_seats_variables(self):
        self.ak("add", "only a seat would see it", "--check", 'test -n "$AGENTKIT_SESSION"')
        self.assertEqual(len(self.plan_lines()), 1)

    def test_an_eye_line_is_ticked_on_the_owners_word_and_a_check_line_never_by_hand(self):
        self.ak("add", "the feature exists", "--check", "test -f feature.txt")
        eye = self.ak("add", "the hero looks calm", "--eye").strip()
        self.assertIn(" · your eye · acme · written ", eye)
        with self.assertRaisesRegex(config.Error, "ticked by ak once its check passes"):
            plan.main(["tick", "1"])
        ticked = self.ak("tick", "2").strip()
        self.assertRegex(ticked, r"^- \[x\] the hero looks calm · your eye · acme · written .+"
                                 r" · done your yes \d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertEqual(plan.LINE.match(ticked)["done"][:8], "your yes")
        with self.assertRaisesRegex(config.Error, "already done"):
            plan.main(["tick", "2"])
        with self.assertRaisesRegex(config.Error, "no plan line 3"):
            plan.main(["tick", "3"])

    def test_outside_a_seat_or_without_a_project_it_is_refused(self):
        with patch.dict(os.environ, {config.SESSION_ENV: ""}), \
                self.assertRaisesRegex(config.Error, "belongs to a session"):
            plan.main([])
        config.save_session(self.cfg, "fix-api", "opus", ["opus"], {"cwd": str(self.root)})
        with self.assertRaisesRegex(config.Error, "filed under no project"):
            plan.main(["add", "anything", "--eye"])
        with self.assertRaisesRegex(config.Error, "usage: ak plan"):
            plan.main(["add", "anything"])


if __name__ == "__main__":
    unittest.main()
