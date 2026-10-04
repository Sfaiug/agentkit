"""The host moves to a new agentkit commit only once its tests/live.sh passed on exactly it.

The tick starts each check detached, in a directory of its own under the state directory, in a
throwaway worktree of the commit with the acceptance gate's environment and a marker naming the
check; one runs while anything carries that marker, one at a time, and one past its cap is ended
by its own runner and by that marker, and counted red.  A red check keeps the host where it is, is handed back once with its failures
and closing lines, however far main moved since, and is tried again on watch.RETRY_BACKOFF from its end, or
from its cap; a newer origin/main is tried as soon as nothing runs.  Every caller of update_agentkit moves
only to a commit that passed, exactly it, and a commit without tests/live.sh moves as before.
`ak update`'s harness upgrade runs tests/live.sh after tests/smoke.sh and reverts on its failure.

Offline throughout: origin is a throwaway bare repository, ~/agentkit is its clone under a
temporary HOME, install.sh and tests/live.sh are fakes committed there, the only processes
signalled are the ones these checks started, and the seat a failure is handed to is a fake.
The real ~/agentkit, its origin, its seats and its harnesses are never read or written here.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
import fcntl
import io
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, update, watch, worker

INSTALL = '#!/bin/sh\necho installed >>"$HOME/installs"\n'
LIVE = f"""#!/bin/sh
python3 -c 'import fcntl, sys; fcntl.flock(open(sys.argv[1]), fcntl.LOCK_SH)' "$HOME/tick"
echo "$(git rev-parse HEAD) ${{AGENTKIT_ACCEPTANCE_REQUIRED:-}} ${{{worker.RUN_MARKER}:-}} $(pwd)" \\
  >>"$HOME/lives"
echo "live: check 3 green"
[ ! -e "$HOME/red" ] || {{ echo "live: check 4 red"; exit 1; }}
"""
HOLD = """#!/bin/sh
echo "live: waiting"
sh -c 'until [ -e "$HOME/release" ]; do sleep 0.05; done' &
wait
"""
AWAY = """#!/bin/sh
python3 -c 'import os, sys; os.setsid(); os.execvp("sh", ["sh", *sys.argv[1:]])' \\
  -c 'touch "$HOME/away"; until [ -e "$HOME/release" ]; do sleep 0.05; done' >/dev/null 2>&1 &
until [ -e "$HOME/away" ]; do sleep 0.05; done
echo "live: check 3 green"
"""
CHAIN = """#!/bin/sh
python3 -c 'import os; print(os.getpgrp())' >"$HOME/group"
hop='sleep 0.05; sh -c "$0" "$0" &'
sh -c "$hop" "$hop" &
echo "live: check 3 green"
"""


def git(where, *args):
    return subprocess.run(["git", "-C", str(where), *args], check=True, capture_output=True,
                          text=True, timeout=60).stdout.strip()


class GoLiveWaitsForLiveChecks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-go-live-checks-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}))
        stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        self.origin, self.seed, self.clone = (self.root / "origin.git", self.root / "seed",
                                              self.root / "agentkit")
        stack.enter_context(patch.object(config, "REPO", self.clone))
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)],
                       check=True, timeout=60)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.seed)],
                       check=True, capture_output=True, timeout=60)
        git(self.seed, "symbolic-ref", "HEAD", "refs/heads/main")
        (self.seed / "install.sh").write_text(INSTALL)
        (self.seed / "install.sh").chmod(0o755)
        self.first = self.merge("first")
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.clone)],
                       check=True, capture_output=True, timeout=60)
        (self.seed / "tests").mkdir()
        (self.seed / "tests" / "live.sh").write_text(LIVE)
        self.handed, self.seat = [], True
        self.addCleanup(self.end_checks)

    def end_checks(self):
        """Whatever a check of this test's own still runs ends with it."""
        (self.root / "release").touch()
        for _, _, check in update.live_checks():
            worker.kill_marked(str(check), grace=2)

    def merge(self, text, live=None):
        if live is not None:
            (self.seed / "tests" / "live.sh").write_text(live)
        (self.seed / "notes").write_text(text + "\n")
        git(self.seed, "add", "-A")
        git(self.seed, "commit", "-q", "-m", text)
        git(self.seed, "push", "-q", "origin", "main")
        return git(self.seed, "rev-parse", "HEAD")

    def head(self):
        return git(self.clone, "rev-parse", "HEAD")

    def count(self, name):
        path = self.root / name
        return len(path.read_text().splitlines()) if path.exists() else 0

    def checks(self):
        return [(commit, check) for _, commit, check in update.live_checks()]

    def deliver(self, run_dir, run_state, key, line, log, typed=None, receipt=None, **_kw):
        """The seat a failure goes to: it takes the line while `self.seat` is up, and has it
        typed but not entered while it is False; there is none while it is None."""
        self.handed.append((key, line, typed))
        if self.seat:
            return True
        if self.seat is False:
            receipt({"line": line, "seat": 1})
        return False

    def tick(self, now=None):
        """One tick's go_live: what it logged.  A LIVE check it starts waits for it to end, as
        a real tests/live.sh, minutes long, outlasts it."""
        said = []
        with open(self.root / "tick", "w") as lock, \
                patch.object(watch, "after_merge_deliver", side_effect=self.deliver):
            fcntl.flock(lock, fcntl.LOCK_EX)
            update.go_live(said.append, now=now)
        return said

    def finish(self, commit):
        """The newest check of that commit, once it has written its exit code and nothing
        carries its marker."""
        check = [check for each, check in self.checks() if each == commit][-1]
        deadline = time.monotonic() + 60
        while (not (check / "exit").exists() or worker.marked_pids(str(check))) \
                and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue((check / "exit").exists(), list(check.iterdir()))
        self.assertEqual(worker.marked_pids(str(check)), [])
        return check

    def held(self, said="live: waiting"):
        """The one check, once its script said that: its directory."""
        check = self.checks()[0][1]
        output = check / "output.tmp"
        deadline = time.monotonic() + 60
        while not (output.exists() and said in output.read_text()) \
                and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(worker.marked_pids(str(check)))
        return check

    def cap(self, check):
        return int(check.name.rsplit("-", 1)[1]) + update.SMOKE_CAP

    def test_a_commit_goes_live_only_once_its_check_passed_on_exactly_it(self):
        new = self.merge("second")
        self.assertEqual(self.tick(), [f"checking agentkit at {new[:12]} with tests/live.sh "
                                       "before it goes live"])
        self.assertEqual((self.head(), self.count("installs")), (self.first, 0))
        check = self.finish(new)
        self.assertEqual((check / "exit").read_text(), "0\n")
        self.assertIn("live: check 3 green", (check / "output").read_text())
        ran, required, marker, where = (self.root / "lives").read_text().split()
        self.assertEqual((ran, required, marker), (new, "1", str(check)))   # exactly it, gated
        self.assertEqual(Path(where), check / "tree")
        self.assertFalse(Path(where).exists())                    # the throwaway tree is gone
        self.assertNotIn(where, git(self.clone, "worktree", "list"))
        third = self.merge("third")                               # origin moved past the pass
        self.assertEqual(self.tick(), [
            f"checking agentkit at {third[:12]} with tests/live.sh before it goes live",
            f"agentkit is live at {new[:12]}"])                   # what passed, not what is new
        self.assertEqual((self.head(), self.count("installs")), (new, 1))
        self.finish(third)
        self.assertEqual(self.tick(), [f"agentkit is live at {third[:12]}"])
        self.assertEqual((self.head(), self.count("installs")), (third, 2))
        self.assertEqual(self.tick(), [])                         # live: nothing more to run
        self.assertEqual(self.checks(), [])                       # what the checkout has goes

    def test_every_caller_moves_only_to_what_passed(self):
        new = self.merge("second")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(update.update_agentkit(), 0)        # `ak update`, `ak`'s start
        self.assertIn("update: agentkit: origin/main moves here once its tests/live.sh passed",
                      out.getvalue())
        self.assertEqual((self.head(), self.count("installs")), (self.first, 0))
        self.tick()
        self.finish(new)
        self.merge("third")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(update.update_agentkit(), 0)
        self.assertEqual((self.head(), self.count("installs")), (new, 1))

    def test_a_commit_without_the_script_moves_as_before(self):
        (self.seed / "tests" / "live.sh").unlink()
        plain = self.merge("second")
        (self.seed / "tests" / "live.sh").write_text(LIVE)
        git(self.seed, "add", "-A")
        git(self.seed, "commit", "-q", "-m", "third")
        real = update._git

        def racing(*args, **kw):
            said = real(*args, **kw)
            if args[:2] == ("cat-file", "-e"):                    # origin moves after the look
                git(self.seed, "push", "-q", "origin", "main")
            return said

        with patch.object(update, "_git", side_effect=racing):
            self.assertEqual(self.tick(), [f"agentkit is live at {plain[:12]}"])
        self.assertEqual((self.head(), self.count("lives"), self.checks()), (plain, 0, []))

    def test_a_dirty_checkout_waits_for_the_check_too(self):
        (self.clone / "scratch").write_text("somebody's work\n")  # it may be clean by the move
        new = self.merge("second")
        self.tick()
        self.assertEqual([commit for commit, _ in self.checks()], [new])
        self.assertEqual(self.head(), self.first)

    def test_one_check_runs_at_a_time_and_a_newer_tip_follows_at_once(self):
        new = self.merge("second", live=HOLD)
        self.tick()
        self.held()
        third = self.merge("third", live=LIVE)
        self.assertEqual(self.tick(), [])                         # running: waited for
        self.assertEqual([commit for commit, _ in self.checks()], [new])
        (self.root / "release").touch()
        self.finish(new)
        self.assertEqual(self.tick(), [
            f"checking agentkit at {third[:12]} with tests/live.sh before it goes live",
            f"agentkit is live at {new[:12]}"])

    def test_a_check_past_its_cap_is_ended_by_its_marker_and_counted_red(self):
        new = self.merge("second", live=HOLD)
        self.tick()
        check = self.held()
        self.assertEqual(self.tick(now=self.cap(check) - 1), [])  # still within its cap
        self.assertTrue(worker.marked_pids(str(check)))
        said = self.tick(now=self.cap(check))
        self.assertEqual(worker.marked_pids(str(check)), [])      # every process it started
        self.assertEqual(said, [
            f"WARN agentkit stays as it is: tests/live.sh failed at {new[:12]}:",
            "  live: waiting", "  [exit 124]", "  [stopped before it finished]",
            f"handed agentkit's failed tests/live.sh at {new[:12]} back to fix"])
        self.assertFalse((check / "tree").exists())               # its runner outlived it
        retry = self.cap(check) + watch.RETRY_BACKOFF[0]          # from its cap
        self.assertEqual(self.tick(now=retry - 1), [])
        self.assertEqual(self.tick(now=retry), [f"checking agentkit at {new[:12]} with "
                                                "tests/live.sh before it goes live"])
        self.assertEqual(self.head(), self.first)
        # a commit without the script moves as before, and the checks it has go, trees and all
        (self.root / "release").touch()
        self.finish(new)
        (self.seed / "tests" / "live.sh").unlink()
        plain = self.merge("third")
        self.assertEqual(self.tick(), [f"agentkit is live at {plain[:12]}"])
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.checks(), [])
        self.assertEqual(len(git(self.clone, "worktree", "list").splitlines()), 1)

    def test_a_check_that_ends_past_its_cap_is_red_whatever_it_said(self):
        new = self.merge("second", live=HOLD)
        self.tick()
        check = self.held()
        (self.root / "release").touch()
        cap = self.cap(check)
        os.utime(self.finish(new) / "exit", (cap, cap))           # it said so only at its cap
        (self.root / "release").unlink()                        # the retry must wait too
        said = self.tick(now=cap + 1)                             # red from when it is seen
        self.assertEqual(said[-2:], ["  [stopped before it finished]", f"handed agentkit's "
                                     f"failed tests/live.sh at {new[:12]} back to fix"])
        self.assertEqual((self.head(), update.live_target()), (self.first, ""))
        self.assertEqual(self.tick(now=cap + 1 + watch.RETRY_BACKOFF[0] - 1), [])
        self.assertEqual(self.tick(now=cap + 1 + watch.RETRY_BACKOFF[0]), [
            f"checking agentkit at {new[:12]} with tests/live.sh before it goes live"])
        (self.root / "release").touch()
        self.finish(new)

    def test_a_check_whose_runner_died_is_red_and_tried_again_on_the_backoff(self):
        new = self.merge("second", live=HOLD)
        self.tick()
        check = self.held()
        with patch.object(signal, "SIGTERM", signal.SIGKILL):     # as a reboot would: no TERM
            worker.kill_marked(str(check), grace=2)
        seen = self.cap(check) - update.SMOKE_CAP + 60
        said = self.tick(now=seen)
        self.assertEqual(said[1:3], ["  live: waiting", "  [stopped before it finished]"])
        self.assertEqual(self.tick(now=seen + watch.RETRY_BACKOFF[0] - 1), [])
        self.assertEqual(self.tick(now=seen + watch.RETRY_BACKOFF[0]), [
            f"checking agentkit at {new[:12]} with tests/live.sh before it goes live"])

    def test_the_newest_red_is_handed_back_while_no_seat_took_an_older_one(self):
        (self.root / "red").touch()
        new = self.merge("second")
        self.tick()
        self.finish(new)
        self.seat = None                                          # no seat at all
        self.assertEqual(self.tick()[0], f"WARN agentkit stays as it is: tests/live.sh "
                                         f"failed at {new[:12]}:")
        third = self.merge("third")
        self.tick(now=time.time() + 60)                           # a tick later, as ticks are
        self.finish(third)
        self.seat = True
        said = self.tick()
        self.assertEqual((said[0], said[-1]), (
            f"WARN agentkit stays as it is: tests/live.sh failed at {third[:12]}:",
            f"handed agentkit's failed tests/live.sh at {third[:12]} back to fix"))
        self.assertIn(third[:12], self.handed[-1][1])
        self.assertEqual(self.tick(), [])                         # once

    def test_a_child_that_left_its_group_holds_it_to_its_cap_and_its_red_outlives_main(self):
        new = self.merge("second", live=AWAY)
        self.tick()
        check = self.checks()[0][1]
        deadline = time.monotonic() + 60
        while not (check / "exit").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(worker.marked_pids(str(check)))           # its script left a child
        third = self.merge("third", live=LIVE)
        self.assertEqual(self.tick(), [])                         # running still: not green yet
        said = self.tick(now=self.cap(check))
        self.assertEqual(worker.marked_pids(str(check)), [])
        self.assertEqual(said, [                                  # the cap made it red
            f"WARN agentkit stays as it is: tests/live.sh failed at {new[:12]}:",
            "  live: check 3 green", "  [exit 0]", "  [stopped before it finished]",
            f"handed agentkit's failed tests/live.sh at {new[:12]} back to fix",
            f"checking agentkit at {third[:12]} with tests/live.sh before it goes live"])

    def test_a_check_the_tick_caps_as_a_caller_reads_it_is_never_moved_to(self):
        new = self.merge("second", live=AWAY)
        self.tick()
        check = self.checks()[0][1]
        deadline = time.monotonic() + 60
        while not (check / "exit").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        real, capped = worker.marked_pids, []

        def scan(run_id, **kw):                   # the tick caps it as the caller looks at it
            if not capped:
                capped.append(None)
                capped[0] = self.tick(now=self.cap(check))
            return real(run_id, **kw)

        with patch.object(worker, "marked_pids", side_effect=scan), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(update.update_agentkit(), 0)
        self.assertEqual(capped[0][-1], f"handed agentkit's failed tests/live.sh at {new[:12]} "
                                        "back to fix")
        self.assertEqual((self.head(), self.count("installs")), (self.first, 0))

    def test_a_check_its_kill_could_not_end_runs_on_and_keeps_its_directory(self):
        self.merge("second", live=HOLD)
        self.tick()
        check = self.held()
        self.merge("third", live=LIVE)
        with patch.object(worker, "kill_marked", return_value=False):
            self.assertEqual(self.tick(now=self.cap(check)), [])  # running: nothing starts
        (self.seed / "tests" / "live.sh").unlink()
        plain = self.merge("fourth")
        self.assertEqual(self.tick(), [f"agentkit is live at {plain[:12]}"])
        with patch.object(worker, "kill_marked", return_value=False):
            self.assertEqual(self.tick(), [])
        self.assertTrue(check.is_dir())                           # the next tick ends it
        self.assertEqual(self.tick(), [])
        self.assertEqual((self.checks(), worker.marked_pids(str(check))), ([], []))

    def test_with_no_proc_to_read_a_check_runs_until_its_cap_and_grace(self):
        new = self.merge("second", live=HOLD)
        self.tick()
        check = self.held()
        ended = self.cap(check) + worker.MARK_KILL_GRACE          # its runner has ended it
        with patch.object(update.host, "PROC", self.root / "no-proc"):
            self.assertEqual(self.tick(now=ended - 1), [])
            said = self.tick(now=ended)
        self.assertEqual(said[0], f"WARN agentkit stays as it is: tests/live.sh failed at "
                                  f"{new[:12]}:")

    def test_with_no_proc_a_check_past_its_cap_is_ended_by_its_own_runner(self):
        # Expire the real runner's wait only after its held script and the tick are observed.
        # A three-second real cap can run out before a loaded host reaches either assertion.
        # Pin its clock so the hook can reject a missing or incorrect remaining timeout.
        self.enterContext(patch.object(update, "LIVE_RUN", update.LIVE_RUN.replace(
            "try:\n    signal.signal(signal.SIGTERM", '''time.time = lambda: float(cap) - 1
wait = script.wait
def expired(timeout=None):
    assert timeout == 1, timeout
    script.wait = wait
    while not os.path.exists(os.path.join(os.environ["HOME"], "expire")):
        time.sleep(.01)
    return wait(0)
script.wait = expired
try:
    signal.signal(signal.SIGTERM''', 1)))
        self.enterContext(patch.object(worker, "MARK_KILL_GRACE", 1))
        new = self.merge("second", live=HOLD)
        self.tick()
        check = self.held()
        third = self.merge("third", live=LIVE)

        def tick(**kw):                                           # /proc hidden from the tick
            with patch.object(update.host, "PROC", self.root / "no-proc"), \
                    patch.object(worker, "marked_pids", return_value=[]):
                return self.tick(**kw)

        self.assertEqual(tick(now=self.cap(check)), [])           # its runner still ending it
        self.assertEqual([commit for commit, _ in self.checks()], [new])
        (self.root / "expire").touch()
        self.assertEqual((self.finish(new) / "exit").read_text(), "124\n")
        self.assertEqual(tick(now=self.cap(check) + worker.MARK_KILL_GRACE), [
            f"WARN agentkit stays as it is: tests/live.sh failed at {new[:12]}:",
            "  live: waiting", "  [exit 124]", "  [stopped before it finished]",
            f"handed agentkit's failed tests/live.sh at {new[:12]} back to fix",
            f"checking agentkit at {third[:12]} with tests/live.sh before it goes live"])

    def test_children_its_script_left_forking_end_before_its_exit_code(self):
        self.merge("second", live=CHAIN)
        self.tick()
        check = self.checks()[0][1]
        deadline = time.monotonic() + 60
        while not (check / "exit").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual((check / "exit").read_text(), "0\n")
        group, running = (self.root / "group").read_text().strip(), []
        for stat in Path("/proc").glob("[0-9]*/stat"):
            try:
                state, _, pgid = stat.read_text().rsplit(")", 1)[1].split()[:3]
            except OSError:                                       # gone as it was read
                continue
            if pgid == group and state != "Z":
                running.append(stat.parent.name)
        self.assertEqual(running, [])

    def test_an_install_owed_is_retried_while_the_check_waits(self):
        new = self.merge("second")
        (config.STATE / "agentkit-install-pending").touch()
        self.tick()
        self.assertEqual([commit for commit, _ in self.checks()], [new])
        self.assertEqual((self.head(), self.count("installs")), (self.first, 1))

    def test_a_red_check_keeps_the_host_and_is_handed_back_once(self):
        (self.root / "red").touch()
        new = self.merge("second")
        self.tick()
        ended = time.time()
        os.utime(self.finish(new) / "exit", (ended, ended))      # when it ended, on this clock
        self.seat = False                                         # no seat at its prompt yet
        said = self.tick(now=ended + 1)
        self.assertEqual(said[0], f"WARN agentkit stays as it is: tests/live.sh failed at "
                                  f"{new[:12]}:")
        self.assertIn("  live: check 4 red", said)
        self.assertEqual(len(self.checks()), 1)                   # not before its backoff
        self.seat = True
        self.assertEqual(self.tick(now=ended + 2),                # its composer mark comes back
                         [f"handed agentkit's failed tests/live.sh at {new[:12]} back to fix"])
        (_, first, _), (key, line, typed) = self.handed
        self.assertEqual((line, typed), (first, {"line": first, "seat": 1}))
        self.assertEqual(key, str(self.origin))                   # agentkit's own repository
        self.assertIn(new[:12], line)
        self.assertIn("live: check 3 green / live: check 4 red / [exit 1]", line)
        self.assertEqual(self.tick(now=ended + 3), [])            # once
        self.assertEqual(len(self.handed), 2)
        for tries, wait in enumerate(watch.RETRY_BACKOFF + (3600,), start=1):
            self.assertEqual(self.tick(now=ended + wait - 1), [])
            self.assertEqual(len(self.checks()), tries)
            self.tick(now=ended + wait)
            ended += wait + 100
            os.utime(self.finish(new) / "exit", (ended, ended))
            self.assertEqual(len(self.checks()), tries + 1)
        self.assertEqual(len(self.handed), 2)                     # a retry is not handed again
        self.assertEqual((self.head(), self.count("installs")), (self.first, 0))
        (self.root / "red").unlink()
        third = self.merge("third")                               # a new commit is tried at once
        self.assertEqual(self.tick(now=ended + 1), [
            f"checking agentkit at {third[:12]} with tests/live.sh before it goes live"])
        self.finish(third)
        self.assertEqual(self.tick(), [f"agentkit is live at {third[:12]}"])

    def upgrade(self, live_passes):
        """`update.upgrade` of one harness with tests/smoke.sh and tests/live.sh beside it:
        the exit code, what it said, and the gates it ran."""
        (self.clone / "tests").mkdir()
        for name in ("smoke.sh", "live.sh"):
            (self.clone / "tests" / name).write_text("#!/bin/sh\n")
        harness = {"name": "acme", "version": ["acme", "--version"],
                   "upgrade": ["acme", "upgrade"], "revert": ["acme", "install", "{version}"],
                   "env": {}, "cannot": "", "snapshot_dir": ""}
        installed, ran = ["1.0.0"], []

        def step(cmd, fh, env=None, timeout=None, **_kw):
            ran.append(cmd)
            if cmd[0] == "bash":
                self.assertEqual((env, timeout),
                                 ({"AGENTKIT_ACCEPTANCE_REQUIRED": "1"}, update.SMOKE_CAP))
                return live_passes or not cmd[-1].endswith("live.sh")
            installed[0] = "1.0.0" if cmd[-1] == "1.0.0" else "2.0.0"
            return True

        out = io.StringIO()
        with patch.object(update, "step", side_effect=step), \
                patch.object(update, "version", side_effect=lambda h: installed[0]), \
                patch.object(update, "fresh_unavailable", return_value="fixture"), \
                redirect_stdout(out), redirect_stderr(out):
            code = update.upgrade([harness], {"acme": "1.0.0"})
        return code, out.getvalue(), [cmd[-1] for cmd in ran if cmd[0] == "bash"]

    def test_a_harness_upgrade_runs_it_after_smoke_and_reverts_on_its_failure(self):
        tests = self.clone / "tests"
        code, said, gates = self.upgrade(live_passes=False)
        self.assertEqual(code, 1, said)
        self.assertEqual(gates, [str(tests / "smoke.sh"), str(tests / "live.sh")])
        self.assertIn("update: live FAILED", said)
        self.assertIn("acme: reverted, back on 1.0.0", said)

    def test_a_harness_upgrade_that_passes_it_keeps_the_new_release(self):
        code, said, gates = self.upgrade(live_passes=True)
        self.assertEqual(code, 0, said)
        self.assertEqual(len(gates), 2)
        self.assertIn("acme 1.0.0->2.0.0, smoke and live passed", said)


if __name__ == "__main__":
    unittest.main()
