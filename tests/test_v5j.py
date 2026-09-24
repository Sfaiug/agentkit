"""agentkit v5j: two suites never collide on the smoke repo, and a branch name is unique on origin.

Entirely offline: the only remotes here are bare repositories under a temporary directory, and
the only lock is /tmp/agentkit-smoke-remote.lock, which is what the suites themselves use.  No
tmux, no network, no harness call.

This file is one more caller of that lock, so it queues for it exactly like a suite rather than
assuming it is free: an ordinary done-when may well run beside a live `tests/smoke.sh`, and the
whole point of the lock is that the second of them waits instead of failing.
"""

import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run

SMOKE = REPO / "tests/smoke.sh"
E2E = REPO / "tests/e2e-fresh.sh"
LOCK = "/tmp/agentkit-smoke-remote.lock"
WAITING = "check 4: waiting for another suite's turn"
# As long as a suite may hold it, and overridable the same way the suites' own wait is.
TURN_WAIT = float(os.environ.get("AK_SMOKE_LOCK_WAIT", 3600))


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def open_lock():
    """Open the shared lock the way the suites do, without ever asking to create what is there.

    /tmp is sticky and world-writable, and under fs.protected_regular=2 an O_CREAT open of a
    file a third account owns there fails with EACCES even read-only -- which is precisely
    suites running as different accounts meeting on this file.
    """
    try:
        return os.open(LOCK, os.O_RDONLY)
    except FileNotFoundError:
        pass
    try:
        made = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return os.open(LOCK, os.O_RDONLY)
    try:
        os.fchmod(made, 0o644)
    finally:
        os.close(made)
    return os.open(LOCK, os.O_RDONLY)


def probe(seconds):
    """`tests/smoke.sh --lock-probe <seconds>`, bounded well past its own wait."""
    return subprocess.run(["bash", str(SMOKE), "--lock-probe", str(seconds)],
                          capture_output=True, text=True, timeout=seconds + 120)


def lock_program(script):
    """The lock program a suite embeds, lifted out of the shell that carries it."""
    return script.read_text().split("SMOKE_LOCK_PY='", 1)[1].split("\n'\n", 1)[0]


def lock_argv(script, path, seconds):
    """Both copies take the same file and wait; only smoke.sh's has a probe mode.

    A parent of -1 is no live process, so e2e's copy -- which only ever holds -- falls straight
    out of its `while os.getppid() == parent` watch once it has reported, instead of standing
    there until this test does.
    """
    if script == SMOKE:
        return [str(path), str(seconds), "probe", "-1"]
    return [str(path), str(seconds), "-1"]


class SuiteLock(unittest.TestCase):
    """The host-wide turn, taken and reported by the suite itself.

    The class holds the turn for its whole run, so `busy` here is this test standing in for the
    other suite and never an accident of timing.
    """

    @classmethod
    def setUpClass(cls):
        cls.fd = open_lock()
        if not cls.take(TURN_WAIT):
            os.close(cls.fd)
            # Not a skip: these are the checks this file owes, and a green run without them
            # would say the lock works when nothing here ever asked it.
            raise AssertionError(
                f"another suite held {LOCK} for the whole {TURN_WAIT:g}s wait, so none of the "
                "lock checks ran")

    @classmethod
    def tearDownClass(cls):
        os.close(cls.fd)

    @classmethod
    def take(cls, wait):
        """Wait for the turn the way a suite does; False if the wait ran out."""
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(cls.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(1)

    def probe_with_the_turn_given_back(self, seconds, attempts=3):
        """Give the turn back, probe, take it again -- retrying a real suite that slips in.

        A probe that waited for somebody else and then got the lock has done its job, so only
        the verdict is retried and never the waiting line: on a file the whole host shares, no
        test can say whether waiting was warranted.  `LockProtocol` asks that on its own file.
        """
        result = None
        for _ in range(attempts):
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            result = probe(seconds)
            self.assertTrue(self.take(TURN_WAIT), "could not take the turn back")
            if result.returncode == 0:
                break
        return result

    def test_v5j_lock_probe_is_busy_while_another_suite_holds_the_remote(self):
        result = probe(1)
        self.assertEqual(result.returncode, 75, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "busy", result.stdout)
        # one line, and it names the check the caller is waiting for
        self.assertIn(WAITING, result.stderr)
        self.assertEqual(result.stderr.count(WAITING), 1, result.stderr)

    def test_v5j_lock_probe_is_held_once_the_other_suite_is_done(self):
        result = self.probe_with_the_turn_given_back(30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "held", result.stdout)
        # and the probe gave its own turn back when it exited, so the next caller waits for it
        again = self.probe_with_the_turn_given_back(30)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)

    def test_v5j_lock_probe_clones_nothing_and_the_file_is_open_to_any_account(self):
        busy = probe(1)
        held = self.probe_with_the_turn_given_back(30)
        for result in (busy, held):
            self.assertNotIn("Cloning", result.stdout + result.stderr)
            self.assertNotIn("agentkit-smoke", result.stdout)
            self.assertEqual(len(result.stdout.split()), 1, result.stdout)
        # a suite running as another account has to be able to open it read-only and flock it
        self.assertTrue(os.stat(LOCK).st_mode & 0o044, oct(os.stat(LOCK).st_mode))



class LockProtocol(unittest.TestCase):
    """What the lock program says, on a file whose contention is this test's alone to decide.

    The shared file cannot answer "did it have to wait?" -- a real suite may take it in any
    window, and rejecting a legitimate waiting line is how an ordinary concurrent done-when
    turns red.  A private file can answer it, and it is the same program either way: both
    copies are lifted out of the shells that carry them, so the two cannot drift apart
    unnoticed, in their wording or in how they open the file.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="v5j-lock-")
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "private.lock"

    def run_lock(self, script, seconds):
        return subprocess.run([sys.executable, "-c", lock_program(script),
                               *lock_argv(script, self.path, seconds)],
                              capture_output=True, text=True, timeout=seconds + 120)

    def test_v5j_a_free_lock_is_taken_at_once_and_says_nothing_about_waiting(self):
        for script in (SMOKE, E2E):
            with self.subTest(script=script.name):
                result = self.run_lock(script, 5)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.split(), ["held"], result.stdout)
                self.assertEqual(oct(os.stat(self.path).st_mode & 0o777), "0o644")

    def test_v5j_a_held_lock_says_waiting_once_and_then_busy(self):
        fd = os.open(self.path, os.O_CREAT | os.O_RDONLY, 0o644)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        for script in (SMOKE, E2E):
            with self.subTest(script=script.name):
                started = time.monotonic()
                result = self.run_lock(script, 2)
                self.assertEqual(result.returncode, 75, result.stdout + result.stderr)
                self.assertEqual(result.stdout.split(), ["waiting", "busy"], result.stdout)
                self.assertGreaterEqual(time.monotonic() - started, 2)

    def test_v5j_the_lock_file_is_opened_without_asking_to_create_it(self):
        """The ordinary path must not carry O_CREAT: see open_lock's docstring for why."""
        for script in (SMOKE, E2E):
            with self.subTest(script=script.name):
                body = lock_program(script)
                self.assertIn("os.O_CREAT | os.O_EXCL", body)
                self.assertNotIn("os.O_CREAT | os.O_RDONLY", body)


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
        real = run.subprocess.run

        def fake(argv, *args, **kwargs):
            if "ls-remote" in argv:
                raise error
            return real(argv, *args, **kwargs)

        return patch.object(run.subprocess, "run", side_effect=fake)

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

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="v5j-push-")
        self.addCleanup(tmp.cleanup)
        self.lp = self.Fake(Path(tmp.name))

    def note(self):
        with patch.object(run, "require_review_pass"), patch.object(run, "save_state"):
            self.assertFalse(run.push(self.lp))
        return self.lp.state["merge_note"]

    def test_v5j_a_stale_info_rejection_names_the_run_that_took_the_branch(self):
        rejected = (" ! [rejected]        ak/smoke-make-hello-pass -> "
                    "ak/smoke-make-hello-pass (stale info)\n"
                    "error: failed to push some refs to 'github.com:caller/agentkit-smoke-throwaway'")
        with patch.object(run, "git_out", return_value=(1, rejected)):
            note = self.note()
        self.assertIn("origin already has ak/smoke-make-hello-pass", note)
        self.assertIn("this run did not push it", note)
        self.assertIn("taken by another run", note)
        self.assertIn("stale info", note)          # git's own tail is still there
        self.assertTrue(self.lp.state["merge_failed"])

    def test_v5j_any_other_push_failure_reads_as_it_did(self):
        with patch.object(run, "git_out", return_value=(1, "fatal: could not read Username")):
            note = self.note()
        self.assertIn("pushing ak/smoke-make-hello-pass to origin failed", note)
        self.assertNotIn("origin already has", note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
