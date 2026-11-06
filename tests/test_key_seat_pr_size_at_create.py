"""A seat's `gh pr create` is refused when its branch adds more lines than the seat builds.

`orchestrator_lines` is the most a seat builds; the gh shim counts the branch against its base as
the review gate does, before the PR exists, so a seat never opens a PR the gate would refuse.
Offline: the shim is `gh` first on PATH, a fake real gh behind it only logs its argv, and the
project is a clone under HOME/code of a bare origin on disk; the seat stands in a worktree of it.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
REAL = "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$RAN_LOG\"\n"


class SeatPrSizeAtCreate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        for place in ("state", "tmp", "bin"):
            (self.home / ".agentkit" / place).mkdir(parents=True)
        (self.home / ".agentkit/state/session-acme.json").write_text("{}\n")
        (self.home / ".agentkit/bin/gh").symlink_to(REPO / "tools/gh-shim")
        (self.home / "real").mkdir()
        (self.home / "real/gh").write_text(REAL)
        (self.home / "real/gh").chmod(0o755)
        self.ran = self.home / "ran.log"
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("AK_", "AGENTKIT_", "GIT_"))}
        self.env.update(HOME=str(self.home), AGENTKIT_SESSION="acme", RAN_LOG=str(self.ran),
                        GIT_AUTHOR_NAME="a", GIT_AUTHOR_EMAIL="a@example.com",
                        GIT_COMMITTER_NAME="a", GIT_COMMITTER_EMAIL="a@example.com",
                        PATH=os.pathsep.join([str(self.home / ".agentkit/bin"), str(self.home / "real"),
                                              os.environ["PATH"]]))
        origin, clone = self.home / "origin.git", self.home / "code/widgets"
        self.git(self.home, "init", "-q", "--bare", "-b", "main", str(origin))
        self.git(self.home, "clone", "-q", str(origin), str(clone))
        (clone / "AGENTS.md").write_text("# widgets\n")
        self.git(clone, "add", "-A")
        self.git(clone, "commit", "-qm", "init")
        self.git(clone, "push", "-q", "-u", "origin", "main")
        self.git(clone, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.seat = self.home / ".agentkit/wt/grow"
        self.git(clone, "worktree", "add", "-q", "-b", "grow", str(self.seat), "main")

    def git(self, where, *args):
        subprocess.run(["git", "-C", str(where), *args], check=True, env=self.env, capture_output=True)

    def build(self, lines, *argv, limit=50, **env):
        """The seat's branch adding `lines` lines (none: deleting AGENTS.md), then its
        `gh pr create` with `argv` (`--fill` when none)."""
        (self.home / ".agentkit/config.toml").write_text(f"orchestrator_lines = {json.dumps(limit)}\n")
        if lines:
            (self.seat / "grow.py").write_text("".join(f"row_{n} = {n}\n" for n in range(lines)))
        else:
            (self.seat / "AGENTS.md").unlink()
        self.git(self.seat, "add", "-A")
        self.git(self.seat, "commit", "-qm", "grow", "--allow-empty")
        self.ran.write_text("")
        done = subprocess.run(["gh", "pr", "create", *(argv or ["--fill"])], cwd=self.seat,
                              env={**self.env, **env}, capture_output=True, text=True, timeout=60)
        return done, self.ran.read_text()

    def test_a_branch_past_the_limit_is_refused_before_the_pr_exists(self):
        done, ran = self.build(60)
        self.assertNotEqual(done.returncode, 0)
        for word in ("60", "50", "from:"):
            self.assertIn(word, done.stderr)
        self.assertEqual(ran, "")

    def test_a_branch_within_the_limit_reaches_gh_unchanged(self):
        done, ran = self.build(10)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(ran, "pr create --fill\n")

    def test_no_limit_lets_every_create_through(self):
        done, ran = self.build(60, limit="no limit")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(ran, "pr create --fill\n")

    def test_none_lets_no_create_through(self):
        # 0: the seat builds nothing, so even a change that only deletes is too much
        done, ran = self.build(0, limit=0)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(ran, "")

    def test_the_branch_is_read_as_gh_reads_it(self):
        # main adds nothing, grouped behind a switch or after an empty title; a title that only
        # reads like a head is none, a switch may carry its value, and an empty base is the default
        for argv, reaches in ((["-fHmain"], True), (["-t=", "--head", "main", "--fill"], True),
                              (["--title", "--head=main", "--fill"], False),
                              (["--fill=true"], False), (["-f=true", "-B="], False)):
            with self.subTest(argv=argv):
                done, ran = self.build(60, *argv)
                self.assertEqual(done.returncode == 0, reaches, done.stderr)
                self.assertEqual(ran, f"pr create {' '.join(argv)}\n" if reaches else "")

    def test_what_the_shim_cannot_measure_reaches_gh(self):
        # another repository's PR, and help: the review gate still holds what reaches GitHub
        for argv, env in ((["--fill", "--repo", "acme/elsewhere"], {}),
                          (["--fill"], {"GH_REPO": "forge.example/acme/widgets"}),
                          (["--help"], {})):
            with self.subTest(argv=argv, env=env):
                done, ran = self.build(60, *argv, **env)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(ran, f"pr create {' '.join(argv)}\n")


if __name__ == "__main__":
    unittest.main()
