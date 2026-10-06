"""The git guard: a seat's `git` shim refuses a `git worktree add` into ~/code, which holds only the
owner's checkouts, and runs the real git otherwise -- a call that never names `worktree` without
starting Python.

Offline: the shim is `git` first on PATH and the real git sits behind it; HOME is a temporary one,
so ~/code and ~/.agentkit/wt are the test's own.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, guard  # noqa: E402

SHIM = REPO / "tools/git-shim"


class GitShim(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.shimdir = self.home / "shim"
        self.shimdir.mkdir()
        (self.shimdir / "git").symlink_to(SHIM)          # the shim is `git`, first on PATH
        live = str(Path.home() / ".agentkit" / "bin")     # the caller's own shims stay out
        path = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part != live]
        self.env = {k: v for k, v in os.environ.items() if k not in ("AK_RUN_ROLE", "AGENTKIT_SESSION")}
        self.env.update(HOME=str(self.home), AGENTKIT_SESSION="mine",
                        PATH=os.pathsep.join([str(self.shimdir), *path]))
        self.code = self.home / "code"
        self.repo = self.code / "acme"
        self.git(self.code, "init", "-q", "-b", "main", str(self.repo))
        self.git(self.repo, "-c", "user.name=a", "-c", "user.email=a@localhost", "commit", "-q",
                 "--allow-empty", "-m", "base")

    def git(self, cwd, *args, **env):
        cwd.mkdir(parents=True, exist_ok=True)
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60,
                              env={**self.env, **env})

    def test_a_seats_worktree_in_code_is_refused_and_nothing_is_made(self):
        for cwd, args in ((self.repo, ["worktree", "add", "../acme-fix", "-b", "fix"]),
                          (self.home, ["-C", str(self.repo), "-c", "x.y=z", "worktree", "add", "-q",
                                       "-b", "fix", "../acme-fix"]),
                          (self.repo, ["worktree", "add", "-fb", "fix", str(self.code / "acme-fix")]),
                          (self.repo, ["worktree", "add", "--lock", "--reason", "mine", "--",
                                       "../acme-fix"])):
            with self.subTest(args=args):
                ran = self.git(cwd, *args)
                self.assertEqual(ran.returncode, 1, ran.stderr)
                self.assertIn("ak refused `git worktree add", ran.stderr)
                self.assertEqual(sorted(os.listdir(self.code)), ["acme"])
                self.assertNotIn("acme-fix", self.git(self.repo, "worktree", "list").stdout)

    def test_every_other_call_runs_the_real_git(self):
        wt = self.home / ".agentkit" / "wt"
        # Under ~/.agentkit/wt, its options' values read as values, not as the path.
        for name, args in (("plain", ["-b", "plain"]), ("bundled", ["-fb", "bundled"]),
                           ("locked", ["--lock", "--reason", "mine", "-b", "locked"]),
                           ("dashed", ["-b", "dashed", "--"])):
            ran = self.git(self.repo, "worktree", "add", "-q", *args, str(wt / name))
            self.assertEqual(ran.returncode, 0, (name, ran.stderr))
            self.assertTrue((wt / name / ".git").exists(), name)
        # A worker's, and whatever runs with no seat -- ak's own, a test's sandbox -- pass too.
        self.assertEqual(self.git(self.repo, "worktree", "add", "-q", "../acme-worker", "-b", "w",
                                  AK_RUN_ROLE="worker").returncode, 0)
        seatless = {k: v for k, v in self.env.items() if k != "AGENTKIT_SESSION"}
        ran = subprocess.run(["git", "worktree", "add", "-q", "../acme-seatless", "-b", "s"],
                             cwd=self.repo, capture_output=True, text=True, timeout=60, env=seatless)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        for args in (["status", "--porcelain"], ["log", "--oneline"], ["worktree", "list"],
                     ["commit", "-q", "--allow-empty", "-m", "worktree"]):
            ran = self.git(self.repo, "-c", "user.name=a", "-c", "user.email=a@localhost", *args)
            self.assertEqual(ran.returncode, 0, (args, ran.stderr))

    def test_a_wrapper_ahead_of_the_shim_reaches_the_real_git(self):
        # A git of its own first on PATH that hands every call to the shim, as a test's slow git does.
        wrapper = self.home / "wrapper"
        wrapper.mkdir()
        (wrapper / "git").write_text(f'#!/bin/sh\nexec "{self.shimdir / "git"}" "$@"\n')
        (wrapper / "git").chmod(0o755)
        ran = self.git(self.repo, "--version", PATH=os.pathsep.join([str(wrapper), self.env["PATH"]]))
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertTrue(ran.stdout.startswith("git version"), ran.stdout)

    def test_a_guard_that_will_not_import_stops_no_git(self):
        # The shim beside a broken agentkit: git still runs, a seat's checkout in ~/code included.
        broken = self.home / "broken"
        (broken / "tools").mkdir(parents=True)
        (broken / "agentkit").mkdir()
        (broken / "agentkit" / "__init__.py").write_text("")
        (broken / "agentkit" / "guard.py").write_text("raise ImportError('broken')\n")
        (broken / "tools" / "git-shim").write_bytes(SHIM.read_bytes())
        (broken / "tools" / "git-shim").chmod(0o755)
        (self.shimdir / "git").unlink()
        (self.shimdir / "git").symlink_to(broken / "tools" / "git-shim")
        ran = self.git(self.repo, "worktree", "add", "-q", "../acme-fix", "-b", "fix")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertTrue((self.code / "acme-fix" / ".git").exists())

    def test_the_shim_is_installed_as_git(self):
        with patch.object(config, "HOME", self.home / ".agentkit"):
            self.assertEqual((guard.install_shim() / "git").resolve(), SHIM.resolve())


if __name__ == "__main__":
    unittest.main()
