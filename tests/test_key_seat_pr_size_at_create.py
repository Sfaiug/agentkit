"""A seat's `gh pr create` is refused when its branch adds more lines than the seat builds.

`orchestrator_lines` is the most a seat builds; the gh guard counts the branch against its base
as the review gate does, before the PR exists, so a seat never opens a PR the gate would refuse.
Black-box: install.sh of the checkout `AK_BIN` names installs it in a Home of
tests/fixtures/akbin.py, the host's tools the refusing fakes of tests/fixtures/installer.py, so
the guard judged is that build's own; a seat's `gh` is the one the install left first on its
PATH, in ~/.agentkit/bin, and the real gh behind it a fake that only keeps its calls.  The
project is a clone under HOME/code of a bare origin on disk; the seat stands in a worktree of it.
"""

import json
import os
import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import LOG, Home


class SeatPrSizeAtCreate(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        installer.prepare(home)
        installed = installer.run(home)
        self.assertEqual(installed.code, 0, installed.err)
        home.fake("gh", LOG.format(python=shlex.quote(sys.executable),
                                   log=shlex.quote(str(home.log("gh")))))
        home.write(".agentkit/state/session-acme.json", "{}\n")
        self.path = os.pathsep.join([str(home.path / ".agentkit/bin"), home.env["PATH"]])
        origin, clone = home.path / "origin.git", home.path / "code/widgets"
        self.git(home.path, "init", "-q", "--bare", "-b", "main", str(origin))
        self.git(home.path, "clone", "-q", str(origin), str(clone))
        (clone / "AGENTS.md").write_text("# widgets\n")
        self.git(clone, "add", "-A")
        self.git(clone, "commit", "-qm", "init")
        self.git(clone, "push", "-q", "-u", "origin", "main")
        self.git(clone, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.seat = home.path / ".agentkit/wt/grow"
        self.git(clone, "worktree", "add", "-q", "-b", "grow", str(self.seat), "main")

    def git(self, where, *args):
        done = self.home.run("git", "-C", str(where), *args)
        self.assertEqual(done.code, 0, done.err)

    def build(self, lines, *argv, limit=50, **env):
        """The seat's branch adding `lines` lines (none: deleting AGENTS.md), then its
        `gh pr create` with `argv` (`--fill` when none), and the calls the real gh got."""
        self.home.write(".agentkit/config.toml", f"orchestrator_lines = {json.dumps(limit)}\n")
        if lines:
            (self.seat / "grow.py").write_text("".join(f"row_{n} = {n}\n" for n in range(lines)))
        else:
            (self.seat / "AGENTS.md").unlink()
        self.git(self.seat, "add", "-A")
        self.git(self.seat, "commit", "-qm", "grow", "--allow-empty")
        self.home.log("gh").unlink(missing_ok=True)
        done = self.home.run("gh", "pr", "create", *(argv or ["--fill"]), cwd=self.seat,
                             env={"AGENTKIT_SESSION": "acme", "PATH": self.path, **env}, timeout=60)
        return done, self.home.calls("gh")

    def test_a_branch_past_the_limit_is_refused_before_the_pr_exists(self):
        done, ran = self.build(60)
        self.assertNotEqual(done.code, 0)
        for word in ("60", "50", "from:"):
            self.assertIn(word, done.err)
        self.assertEqual(ran, [])

    def test_a_branch_within_the_limit_reaches_gh_unchanged(self):
        done, ran = self.build(10)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(ran, [["pr", "create", "--fill"]])

    def test_no_limit_lets_every_create_through(self):
        done, ran = self.build(60, limit="no limit")
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(ran, [["pr", "create", "--fill"]])

    def test_none_lets_no_create_through(self):
        # 0: the seat builds nothing, so even a change that only deletes is too much
        done, ran = self.build(0, limit=0)
        self.assertNotEqual(done.code, 0)
        self.assertEqual(ran, [])

    def test_the_branch_is_read_as_gh_reads_it(self):
        # main adds nothing, grouped behind a switch or after an empty title; a title that only
        # reads like a head is none, a switch may carry its value, and an empty base is the default
        for argv, reaches in ((["-fHmain"], True), (["-t=", "--head", "main", "--fill"], True),
                              (["--title", "--head=main", "--fill"], False),
                              (["--fill=true"], False), (["-f=true", "-B="], False)):
            with self.subTest(argv=argv):
                done, ran = self.build(60, *argv)
                self.assertEqual(done.code == 0, reaches, done.err)
                self.assertEqual(ran, [["pr", "create", *argv]] if reaches else [])

    def test_what_the_shim_cannot_measure_reaches_gh(self):
        # another repository's PR, and help: the review gate still holds what reaches GitHub
        for argv, env in ((["--fill", "--repo", "acme/elsewhere"], {}),
                          (["--fill"], {"GH_REPO": "forge.example/acme/widgets"}),
                          (["--help"], {})):
            with self.subTest(argv=argv, env=env):
                done, ran = self.build(60, *argv, **env)
                self.assertEqual(done.code, 0, done.err)
                self.assertEqual(ran, [["pr", "create", *argv]])


if __name__ == "__main__":
    unittest.main()
