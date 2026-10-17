"""`ak plan add` and `ak plan check` refuse a check whose text holds the project's checkout path.

A check runs in a clean checkout of the default branch, so one that goes to the project's own
checkout (`cd ~/agentkit && ...`) tests what that checkout holds, uncommitted work or ak's
install behind main, instead.  The guard reads text, not the shell: the path written from `/`,
`~`, `$HOME` or `${HOME}`, quotes and backslashes dropped from both sides, so every quoting of
it is found, and a longer name that starts with it is refused too.  Each spelling below is first
run by bash to show it really enters the checkout.  Offline: a throwaway HOME and checkout.
"""

import os
import shlex
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, plan

SEAT = "fix-api"


class HoldsCheckout(Sandbox):
    NAME = "acme"

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            config.SESSION_ENV: SEAT, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        self.repo = config.CODE / self.NAME
        self.repo.mkdir(parents=True)
        origin = self.root / "origin.git"
        for args in (["init", "-q", "-b", "main"],
                     ["-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-q",
                      "--allow-empty", "-m", "base"],
                     ["clone", "-q", "--bare", ".", str(origin)],
                     ["remote", "add", "origin", str(origin)], ["fetch", "-q", "origin"],
                     ["symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"]):
            subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)
        config.save_session(self.cfg, SEAT, "opus", ["opus"],
                            {"cwd": str(self.root), "repo": str(self.repo)})
        plan.add(SEAT, "the feature exists", "test -f feature.txt")

    def spellings(self):
        rel = f"code/{self.NAME}"
        escaped = "".join("\\" + char for char in rel)
        return [f"cd {shlex.quote(str(self.repo))} && test -f feature.txt",
                f"cd ~/{shlex.quote(rel)} && test -f feature.txt",
                f"cd ~/{escaped} && test -f feature.txt",
                f'cd "$HOME"/{shlex.quote(rel)} && test -f feature.txt',
                f'cd "${{HOME}}/{rel}" && test -f feature.txt',
                f'test "$(cat <~/{shlex.quote(rel)}/result)" = ready',
                "bash -c " + shlex.quote(f"cd ~/{shlex.quote(rel)} && test -f feature.txt"),
                f"test -d ~/{shlex.quote(rel + '-old')}"]

    def test_every_spelling_of_the_checkout_is_refused_by_add_and_check(self):
        (self.repo / "feature.txt").write_text("")
        (self.repo / "result").write_text("ready\n")
        (self.repo.parent / f"{self.NAME}-old").mkdir()
        before = config.plan_path(SEAT).read_text()
        for check in self.spellings():
            with self.subTest(check=check):
                ran = subprocess.run(["bash", "-c", check], cwd=self.root, capture_output=True)
                self.assertEqual(ran.returncode, 0, ran.stderr)
                for call in (lambda: plan.add(SEAT, "the feature is there", check),
                             lambda: plan.recheck(SEAT, 1, check)):
                    with self.assertRaisesRegex(config.Error, "the path of the project's checkout"):
                        call()
                    self.assertEqual(config.plan_path(SEAT).read_text(), before)

    def test_a_check_inside_the_repository_or_elsewhere_is_planned(self):
        self.assertIn("python3 tests/test_x.py", plan.recheck(SEAT, 1, "python3 tests/test_x.py"))
        line = plan.add(SEAT, "the other checkout has it", "test -f ~/code/other/feature.txt")
        self.assertIn("~/code/other/feature.txt", line)


class QuoteInName(HoldsCheckout):
    NAME = "acme's tools"


if __name__ == "__main__":
    unittest.main()
