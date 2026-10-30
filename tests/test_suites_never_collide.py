"""Two suites never collide: their runs and seats are named apart, and a branch name is unique
on origin.  (Their branches in the sandbox repository: tests/test_one_sandbox_repo.py.)

Entirely offline: the only remotes here are bare repositories under a temporary directory.
No tmux, no network, no harness call.
"""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, deliver, gitcall, run

SMOKE = (REPO / "tests/smoke.sh").read_text()


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


class TwoSuitesApart(unittest.TestCase):
    """Two suites started in the same minute give their runs and seats different names."""

    # Every task file the suite writes, and every fixed seat name made of the suite's pid --
    # with the repository name a review run's id is made of.
    TASKS = re.findall(r'^cat >"\$WORK/[\w.-]+\.md" <<\'?MD\'?\n---\n.*?\nMD\n', SMOKE, re.M | re.S)
    SEATS = re.findall(r'\b\w+="?((?:smoke|stall)[\w-]*-\$\$)', SMOKE)

    def suites(self):
        """What two suites started together make of those lines, each in a shell of its own."""
        procs = []
        for _ in range(2):
            work = tempfile.TemporaryDirectory(prefix="smoke-names-")
            self.addCleanup(work.cleanup)
            script = "R=/r; TR=/tr\n" + "".join(self.TASKS) + "echo $$ " + " ".join(self.SEATS)
            procs.append((Path(work.name), subprocess.Popen(
                ["bash", "-c", script], env={**os.environ, "WORK": work.name},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)))
        return [(work, *proc.communicate(timeout=30)) for work, proc in procs]

    def names(self, work, out):
        """Every run id and fixed seat name one suite gives, all in the same minute."""
        pid, *seats = out.split()
        found = set(seats)
        for task in sorted(work.glob("*.md")):
            title = re.search(r"^# (.+)$", task.read_text(), re.M).group(1)
            # the pid has to survive the slug's cut to 40 characters, the widest one included
            for token in (pid, "4194304"):
                self.assertTrue(run.slugify(title.replace(pid, token)).endswith("-" + token),
                                (task.name, title))
            found.add(f"20260930-1200-{run.slugify(title)}")
        return pid, found

    def test_two_suites_started_together_name_nothing_alike(self):
        self.assertGreaterEqual(len(self.TASKS), 7)
        (work1, out1, err1), (work2, out2, err2) = self.suites()
        self.assertEqual(err1 + err2, "")
        first, ours = self.names(work1, out1)
        second, theirs = self.names(work2, out2)
        self.assertNotEqual(first, second)
        self.assertEqual(len(ours), len(self.TASKS) + len(self.SEATS))
        self.assertEqual(ours & theirs, set())
        for seat in ("smoke-slice-", "smoke-ov-1-", "smoke-ov-2-", "smoke-inbox-",
                     "stall-claude-", "smokerepo-"):
            self.assertIn(seat + first, ours)



class BranchNames(unittest.TestCase):
    """`make_worktree` picks a name no local branch and no head on `origin` already has."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="v5j-branches-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patcher = patch.object(config, "WT", self.root / "wt")
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.root / "wt").mkdir()

    def repo(self, name="repo", remote=True):
        """A repository with one commit, and a bare `origin` it has already pushed `main` to."""
        path = self.root / name
        path.mkdir()
        git(path, "init", "-q", "-b", "main")
        git(path, "config", "user.email", "fixture@localhost")
        git(path, "config", "user.name", "fixture")
        (path / "keep").write_text("seed\n")
        git(path, "add", "-A")
        git(path, "commit", "-qm", "seed")
        if remote:
            bare = self.root / f"{name}.git"
            subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True,
                           capture_output=True)
            git(path, "remote", "add", "origin", str(bare))
            git(path, "push", "-q", "origin", "main")
        return path

    def on_origin(self, path, *branches):
        for branch in branches:
            git(path, "push", "-q", "origin", f"main:refs/heads/{branch}")

    def make(self, path, slug, run_id="run"):
        base = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        _, branch = run.make_worktree(path, run_id, slug, base)
        return branch

    def broken_ls_remote(self, error):
        """Everything git does still works; only the remote lookup fails, as a stub's would."""
        real = gitcall.run_capped

        def fake(argv, *args, **kwargs):
            if "ls-remote" in argv:
                raise error
            return real(argv, *args, **kwargs)

        return patch.object(gitcall, "run_capped", side_effect=fake)

    def test_v5j_a_branch_name_origin_already_has_is_not_reused(self):
        path = self.repo()
        self.on_origin(path, "ak/smoke-make-hello-pass")
        self.assertEqual(self.make(path, "smoke-make-hello-pass"),
                         "ak/smoke-make-hello-pass-2")

    def test_v5j_local_and_remote_names_are_both_skipped(self):
        path = self.repo()
        git(path, "branch", "ak/smoke-make-hello-pass")
        self.on_origin(path, "ak/smoke-make-hello-pass-2")
        self.assertEqual(self.make(path, "smoke-make-hello-pass"),
                         "ak/smoke-make-hello-pass-3")

    def test_v5j_a_free_name_is_still_the_plain_one(self):
        path = self.repo()
        self.on_origin(path, "ak/something-else", "ak/smoke-make-hello-pass-thing")
        # `ak/<slug>*` matches the longer name too; only an exact collision may push the suffix
        self.assertEqual(self.make(path, "smoke-make-hello-pass"), "ak/smoke-make-hello-pass")

    def test_v5j_no_origin_and_an_unreachable_origin_name_the_branch_locally(self):
        nowhere = self.repo("lonely", remote=False)
        self.assertEqual(self.make(nowhere, "smoke-make-hello-pass", "run-lonely"),
                         "ak/smoke-make-hello-pass")
        broken = self.repo("broken", remote=False)
        git(broken, "remote", "add", "origin", str(self.root / "does-not-exist.git"))
        self.assertEqual(self.make(broken, "smoke-make-hello-pass", "run-broken"),
                         "ak/smoke-make-hello-pass")

    def test_v5j_a_remote_lookup_that_cannot_run_still_names_the_branch(self):
        # naming information this run does not have -- a stubbed git, a timeout, no git at all --
        # is never a reason to refuse it a branch, even with the name taken on origin
        for n, error in enumerate((subprocess.TimeoutExpired("git", 1), OSError("no git here"),
                                   ValueError("stubbed argv"))):
            with self.subTest(error=type(error).__name__):
                path = self.repo(f"stubbed-{n}")
                self.on_origin(path, "ak/smoke-make-hello-pass")
                with self.broken_ls_remote(error):
                    branch = self.make(path, "smoke-make-hello-pass", f"run-stub-{n}")
                self.assertEqual(branch, "ak/smoke-make-hello-pass")


class RejectedPush(unittest.TestCase):
    """A push refused because origin already carries the branch says exactly that."""

    class Fake:
        def __init__(self, root):
            self.run_dir, self.wt = root, root
            self.state = {"branch": "ak/smoke-make-hello-pass", "verdict": "PASS",
                          "review": {"verdict": "PASS"}}
            self.lines = []

        def log(self, line):
            self.lines.append(line)

        def write(self):
            pass

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="v5j-push-")
        self.addCleanup(tmp.cleanup)
        self.lp = self.Fake(Path(tmp.name))

    def note(self):
        with patch.object(deliver, "require_review_pass"):
            self.assertFalse(run.push(self.lp))
        return self.lp.state["merge_note"]

    def test_v5j_a_stale_info_rejection_names_the_run_that_took_the_branch(self):
        rejected = (" ! [rejected]        ak/smoke-make-hello-pass -> "
                    "ak/smoke-make-hello-pass (stale info)\n"
                    "error: failed to push some refs to 'github.com:caller/agentkit-smoke-throwaway'")
        with patch.object(gitcall, "git_out", return_value=(1, rejected)):
            note = self.note()
        self.assertIn("origin already has ak/smoke-make-hello-pass", note)
        self.assertIn("this run did not push it", note)
        self.assertIn("taken by another run", note)
        self.assertIn("stale info", note)          # git's own tail is still there
        self.assertTrue(self.lp.state["merge_failed"])

    def test_v5j_any_other_push_failure_reads_as_it_did(self):
        with patch.object(gitcall, "git_out", return_value=(1, "fatal: could not read Username")):
            note = self.note()
        self.assertIn("pushing ak/smoke-make-hello-pass to origin failed", note)
        self.assertNotIn("origin already has", note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
