"""`ak plan add` and `ak plan check` refuse a check that names the project's own checkout.

A check runs in a clean checkout of the project's default branch (`plan.default_branch`), so
one that goes into the checkout itself -- `cd ~/code/acme && ...` -- tests whatever is checked
out there: it can fail after the work landed, until that checkout moves, or pass before
it.  The checkout's path is refused however the check spells it: absolute, under `~`, `$HOME`
or `${HOME}`, quoted or not; a path beside it (`acme-old`, `acme backup`, `acme~`) is not the
checkout.  Offline: a throwaway HOME, a local origin and checkout.
"""

import os
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, plan

SEAT = "fix-api"


class CheckInCheckout(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            config.SESSION_ENV: SEAT, "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1"}))
        self.repo = config.CODE / "acme"
        self.repo.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("-c", "user.name=Plan test", "-c", "user.email=plan@localhost",
                 "commit", "-q", "--allow-empty", "-m", "base")
        origin = self.root / "origin.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.repo), str(origin)],
                       check=True, capture_output=True)
        self.git("remote", "add", "origin", str(origin))
        self.git("fetch", "-q", "origin")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        config.save_session(self.cfg, SEAT, "opus", ["opus"],
                            {"cwd": str(self.root), "repo": str(self.repo)})

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def plan_text(self):
        path = config.plan_path(SEAT)
        return path.read_text() if path.exists() else ""

    def refused(self, call):
        before = self.plan_text()
        with self.assertRaises(config.Error) as raised:
            call()
        self.assertIn("this check names ~/code/acme, the project's checkout", str(raised.exception))
        self.assertEqual(self.plan_text(), before)

    def test_add_refuses_the_checkout_however_it_is_spelled(self):
        for check in (f"cd {self.repo} && python3 tests/test_x.py",
                      "cd ~/code/acme && python3 tests/test_x.py",
                      "cd $HOME/code/acme && python3 tests/test_x.py",
                      'cd "${HOME}/code/acme" && python3 tests/test_x.py',
                      'cd "$HOME"/code/acme; python3 tests/test_x.py',
                      "python3 ~/code/acme/tests/test_x.py",
                      f"git -C '{self.repo}' log -1",
                      'test "$(cat <~/code/acme/result)" = ready',
                      "cd ~/code/acme"):
            with self.subTest(check=check):
                self.refused(lambda: plan.add(SEAT, "the parser parses", check))

    def test_add_takes_a_relative_check_or_a_path_beside_the_checkout(self):
        for check in ("python3 tests/test_x.py", "cd ~/code/acme-old && python3 tests/test_x.py",
                      "test -d ~/code/acme.bak", 'test -f "$HOME/code/acme backup/x"',
                      "test -d ~/code/acme+tools", "test -d ~/code/acme~"):
            with self.subTest(check=check):
                self.assertIn(f"check: `{check}`", plan.add(SEAT, "the parser parses", check))

    def test_a_quote_in_the_checkout_s_name_is_part_of_its_path(self):
        repo = self.repo.rename(self.repo.with_name("acme's"))
        for check in (f'cd "{repo}" && test -f x', 'cd "$HOME/code/acme\'s" && test -f x',
                      'cd "${HOME}/code/acme\'s" && test -f x'):
            with self.subTest(check=check):
                with self.assertRaises(config.Error) as raised:
                    plan.add(SEAT, "the parser parses", check, repo=repo)
                self.assertIn("this check names ~/code/acme's,", str(raised.exception))

    def test_check_refuses_the_checkout_in_place_of_a_line_s_check(self):
        plan.add(SEAT, "the parser parses", "python3 tests/test_x.py")
        self.refused(lambda: plan.recheck(SEAT, 1, "cd ~/code/acme && python3 tests/test_y.py"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
