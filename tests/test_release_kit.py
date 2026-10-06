"""The release kit releases only commits ak stamped and puts the live release back by itself."""

from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", REPO / "tools" / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "acme", "GIT_AUTHOR_EMAIL": "acme@localhost",
           "GIT_COMMITTER_NAME": "acme", "GIT_COMMITTER_EMAIL": "acme@localhost"}
CONFIG = """restart = '{restart}'
python = "{python}"
health = "{health}"
health_seconds = {health_seconds}
migrate = "{migrate}"
keep = {keep}
{extra}
"""


class ReleaseKit(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-release-kit-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.origin, self.work, self.root = base / "origin.git", base / "work", base / "acme"
        self.restarts = base / "restarts"     # the release each restart ran in, one per line
        self.failing = base / "fail"          # a file named after a release fails its restart once
        self.failing.mkdir()
        # a stand-in interpreter: `python -m venv DIR` makes a virtualenv whose pip logs the
        # requirements file it was given
        self.python = base / "python"
        self.python.write_text('#!/bin/sh\nmkdir -p "$3/bin"\n'
                               'printf \'#!/bin/sh\\necho "$4" >> %s/installs\\n\' "$PWD/$3" > "$3/bin/pip"\n'
                               'chmod +x "$3/bin/pip"\n')
        self.python.chmod(0o755)
        self.branch = "main"                  # the branch ak lands on, as origin/HEAD names it
        self.git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(base, "clone", "-q", str(self.origin), str(self.work))
        self.first = self.commit()
        self.root.mkdir()
        self.git(base, "clone", "-q", str(self.origin), str(self.root / "repo"))

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                              text=True, env=GIT_ENV).stdout.strip()

    def commit(self, healthy=True, stamp=True, migrate="true", keep=5, files=None, extra="",
               health="test -f healthy", merge=None, health_seconds=1):
        work = self.work
        restart = (f"n=${{PWD##*/}}; if [ -f {self.failing}/$n ]; then rm {self.failing}/$n; "
                   f"exit 1; fi; echo $n >> {self.restarts}")
        (work / "deploy").mkdir(exist_ok=True)
        (work / "deploy" / "release.toml").write_text(CONFIG.format(
            restart=restart, migrate=migrate, keep=keep, python=self.python, extra=extra,
            health=health, health_seconds=health_seconds))
        (work / "healthy").unlink(missing_ok=True)
        if healthy:
            (work / "healthy").write_text("yes\n")
        count = work / "counter"
        count.write_text(f"{int(count.read_text()) + 1 if count.exists() else 0}\n")
        for name, text in (files or {}).items():
            (work / name).parent.mkdir(parents=True, exist_ok=True)
            (work / name).write_text(text)
        self.git(work, "add", "-A")
        tree = self.git(work, "write-tree")
        message = f"acme change\n\n{release.STAMP}: {tree}\n" if stamp else "acme change\n"
        has_head = subprocess.run(["git", "-C", str(work), "rev-parse", "-q", "--verify", "HEAD"],
                                  capture_output=True, env=GIT_ENV).returncode == 0
        parents = (["-p", "HEAD"] if has_head else []) + (["-p", merge] if merge else [])
        sha = self.git(work, "commit-tree", tree, *parents, "-m", message)
        self.git(work, "reset", "-q", "--hard", sha)
        self.git(work, "push", "-q", "--force", "origin", f"HEAD:{self.branch}")
        return sha

    def tick(self, *extra):
        out = io.StringIO()
        with redirect_stdout(out):
            code = release.main(["release.py", str(self.root), *extra])
        return code, out.getvalue()

    def live(self):
        return (self.root / "released").read_text().split()[0]

    def current(self):
        return os.readlink(self.root / "current")

    def restarted(self):
        return self.restarts.read_text().split() if self.restarts.exists() else []

    def releases(self):
        return {p.name for p in (self.root / "releases").iterdir()}

    def cut_off(self, sha, switched):
        self.git(self.root / "repo", "fetch", "-q", "origin",
                 f"+refs/heads/{self.branch}:refs/remotes/origin/{self.branch}")
        release.prepare(self.root, sha)
        (self.root / "attempt").write_text(f"{sha} {self.live()}\n")
        if switched:
            release.switch(self.root, sha)

    def test_adopt_then_release_the_newest_stamped_commit_only(self):
        self.assertEqual(self.tick("--adopt")[0], 0)
        self.assertEqual(self.live(), self.first)
        self.assertEqual(self.restarted(), [])         # adopting restarts nothing
        stamped = self.commit()
        self.commit(stamp=False)                      # untested: never released on its own
        code, out = self.tick()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.live(), stamped)
        self.assertEqual(self.current(), f"releases/{stamped}")
        self.assertEqual(self.restarted(), [stamped])
        self.assertEqual(self.tick(), (0, ""))        # nothing newer: a quiet tick

    def test_a_failing_health_puts_the_live_release_back(self):
        self.tick("--adopt")
        broken = self.commit(healthy=False)
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live", out)
        self.assertEqual(self.live(), self.first)
        self.assertEqual(self.current(), f"releases/{self.first}")
        self.assertEqual(self.restarted(), [broken, self.first])
        self.assertFalse((self.root / "attempt").exists())
        # the failed commit waits for a newer one
        self.assertEqual(self.tick(), (0, ""))
        fixed = self.commit()
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.live(), fixed)

    def test_a_failed_commit_is_a_floor_also_after_a_rewrite(self):
        self.tick("--adopt")
        parent = self.commit()
        self.commit(healthy=False)
        self.assertEqual(self.tick()[0], 1)
        self.assertEqual(self.tick(), (0, ""))
        self.git(self.work, "push", "-q", "--force", "origin", f"{parent}:main")
        self.assertEqual(self.tick(), (0, ""))
        self.assertEqual(self.live(), self.first)

    def test_the_failed_floor_survives_git_garbage_collection(self):
        self.tick("--adopt")
        parent = self.commit()
        self.commit(healthy=False)
        self.assertEqual(self.tick()[0], 1)
        self.git(self.work, "push", "-q", "--force", "origin", f"{parent}:main")
        repo = self.root / "repo"
        self.git(repo, "fetch", "-q", "--prune", "origin",
                 "+refs/heads/main:refs/remotes/origin/main")
        self.git(repo, "reflog", "expire", "--expire=now", "--all")
        self.git(repo, "gc", "-q", "--prune=now")
        self.assertEqual(self.tick(), (0, ""))
        self.assertEqual(self.live(), self.first)

    def test_a_failed_restart_restores_too(self):
        self.tick("--adopt")
        broken = self.commit()
        (self.failing / broken).touch()
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live: restart failed", out)
        self.assertEqual(self.current(), f"releases/{self.first}")
        self.assertEqual(self.restarted(), [self.first])

    def test_a_failed_restore_keeps_its_attempt_until_a_later_tick_finishes_it(self):
        self.tick("--adopt")
        broken = self.commit(healthy=False)
        (self.failing / self.first).touch()          # restarting the live release fails once
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn("the next tick tries again", out)
        self.assertIn("restoring", (self.root / "attempt").read_text())
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live", out)
        self.assertFalse((self.root / "attempt").exists())
        self.assertEqual(self.tick(), (0, ""))

    def test_a_tick_cut_off_after_the_switch_is_restored_by_the_next(self):
        self.tick("--adopt")
        newer = self.commit()
        self.cut_off(newer, switched=True)
        code, out = self.tick()
        self.assertIn(f"{newer[:12]} failed and {self.first[:12]} is back live: the tick "
                      "releasing it was cut off", out)
        self.assertEqual(self.current(), f"releases/{self.first}")

    def test_an_attempt_that_never_switched_changes_nothing_live_and_is_tried_again(self):
        self.tick("--adopt")
        newer = self.commit()
        self.cut_off(newer, switched=False)
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{newer[:12]} not released, nothing live changed: the tick releasing it "
                      "was cut off", out)
        self.assertEqual(self.restarted(), [])
        self.assertEqual(self.current(), f"releases/{self.first}")
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.live(), newer)
        # a switch that fails leaves the live release untouched too
        newest = self.commit()
        with patch.object(release, "switch", side_effect=OSError("link refused")):
            code, out = self.tick()
        self.assertIn(f"{newest[:12]} not released, nothing live changed: OSError: link refused",
                      out)
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.live(), newest)

    def test_a_host_failure_before_the_switch_is_tried_again(self):
        self.tick("--adopt")
        newer = self.commit()
        git = release.git

        def refused(repo, *args):
            if args[:2] == ("worktree", "add"):
                raise release.Failed("git worktree add: a lock held elsewhere")
            return git(repo, *args)
        with patch.object(release, "git", refused):
            code, out = self.tick()
        self.assertIn(f"{newer[:12]} not released, nothing live changed: git worktree add", out)
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.live(), newer)

    def test_a_failing_migration_changes_nothing_live_and_is_tried_again(self):
        self.tick("--adopt")
        broken = self.commit(migrate="echo schema refused >&2; exit 3")
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} not released, nothing live changed: migrate failed "
                      "(exit 3)", out)
        self.assertIn("schema refused", out)
        self.assertEqual(self.current(), f"releases/{self.first}")
        self.assertEqual(self.restarted(), [])
        self.assertIn("migrate failed", self.tick()[1])

    def test_keep_zero_leaves_the_live_and_the_previous_release(self):
        self.tick("--adopt")
        previous = self.commit(keep=0)
        self.assertEqual(self.tick()[0], 0)
        newest = self.commit(keep=0)
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.tick(), (0, ""))          # every tick prunes first
        self.assertEqual(self.releases(), {newest, previous})

    def test_a_tick_cut_off_after_going_live_finishes_and_pruning_resumes(self):
        self.tick("--adopt")
        previous = self.commit(keep=0)
        self.tick()
        newer = self.commit(keep=0)
        self.cut_off(newer, switched=True)
        (self.root / "released").write_text(f"{newer} now {previous}\n")
        self.assertEqual(self.tick(), (0, ""))
        self.assertFalse((self.root / "attempt").exists())
        with patch.object(release, "remove", side_effect=OSError("cut off while pruning")):
            with self.assertRaises(OSError):
                self.tick()
        self.assertEqual(self.tick(), (0, ""))
        self.assertEqual(self.releases(), {newer, previous})

    def test_failed_releases_obey_the_keep_count(self):
        self.tick("--adopt")
        for index in range(5):
            self.commit(keep=2, healthy=index % 2 == 0, migrate="true" if index % 3 else "exit 1")
            self.tick()
        self.tick()
        self.assertLessEqual(len(self.releases()), 4)       # two besides live and previous

    def test_adopting_twice_is_refused(self):
        self.tick("--adopt")
        code, out = self.tick("--adopt")
        self.assertEqual(code, 1)
        self.assertIn("is adopted already", out)
        self.assertTrue((self.root / "releases" / self.first).is_dir())

    def test_only_commits_that_descend_from_live_are_released(self):
        self.tick("--adopt")
        # an older stamped line, with live merged in as its merge's second parent
        self.git(self.work, "checkout", "-q", "--orphan", "older")
        self.git(self.work, "rm", "-rqf", ".")
        side = self.commit(files={"side.txt": "side\n"})
        self.commit(stamp=False, merge=self.first)
        self.assertNotEqual(side, self.first)
        self.assertEqual(self.tick(), (0, ""))
        self.assertEqual(self.live(), self.first)

    def test_a_rewritten_main_is_refused_never_released_backward(self):
        self.tick("--adopt")
        newer = self.commit()
        self.tick()
        self.git(self.work, "reset", "-q", "--hard", self.first)
        self.commit(files={"side.txt": "side\n"})      # an older line, stamped, force-pushed
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"main no longer contains the live release {newer[:12]}", out)
        self.assertEqual(self.live(), newer)

    def test_it_releases_from_the_branch_origin_head_names(self):
        repo = self.root / "repo"
        self.git(self.work, "push", "-q", "origin", "HEAD:trunk")
        self.git(self.origin, "symbolic-ref", "HEAD", "refs/heads/trunk")
        self.git(self.work, "push", "-q", "origin", ":main")      # no main at all
        self.git(repo, "fetch", "-q", "--prune", "origin")
        self.git(repo, "remote", "set-head", "origin", "trunk")
        self.branch = "trunk"
        self.tick("--adopt")
        newer = self.commit()
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.live(), newer)
        self.git(repo, "remote", "set-head", "origin", "-d")
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn("has no origin/HEAD", out)

    def test_no_live_release_asks_to_adopt(self):
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn("--adopt", out)

    def test_adopting_builds_the_release_so_it_can_be_restored(self):
        self.work.joinpath("built").unlink(missing_ok=True)
        self.first = self.commit(extra='install = "touch built"', health="test -f built")
        self.git(self.root / "repo", "pull", "-q", "origin", "main")
        self.assertEqual(self.tick("--adopt")[0], 0)
        broken = self.commit(extra='install = "touch built"', health="false")
        code, out = self.tick()
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live", out)

    def test_each_release_installs_its_own_fresh_virtualenv(self):
        self.tick("--adopt")
        name = "production requirements.txt"
        one = self.commit(extra=f'requirements = "{name}"', files={name: "acme==1\n"})
        self.assertEqual(self.tick()[0], 0)
        # a virtualenv committed by mistake is never reused
        two = self.commit(extra=f'requirements = "{name}"',
                          files={name: "acme==1\n", ".venv/stale.py": "stale\n"})
        self.assertEqual(self.tick()[0], 0)
        for sha in (one, two):
            venv = self.root / "releases" / sha / ".venv"
            self.assertTrue(venv.is_dir() and not venv.is_symlink())
            self.assertEqual((venv / "installs").read_text(), f"{name}\n")
        self.assertFalse((self.root / "releases" / two / ".venv" / "stale.py").exists())

    def test_a_command_s_leftover_children_end_with_it(self):
        self.tick("--adopt")
        self.commit(health="(sleep 1; touch late) & exit 1")
        self.assertEqual(self.tick()[0], 1)
        time.sleep(1.5)
        self.assertEqual(list((self.root / "releases").glob("*/late")), [])

    def test_a_command_s_group_ends_before_its_leader_is_reaped(self):
        states, killpg = [], os.killpg

        def ending(pid, sig):
            # raises ChildProcessError once the leader is reaped and its id free for reuse
            states.append(os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT))
            killpg(pid, sig)
        with patch.object(release.os, "killpg", ending):
            self.assertEqual(release.run(self.root, ["true"])[0], 0)
            self.assertEqual(release.run(self.root, ["sleep", "5"], 0.2)[::2], (124, True))
        self.assertIsNotNone(states[0])

    def test_health_passes_only_within_its_time_and_retries_until_then(self):
        self.tick("--adopt")
        self.commit(health="sleep 3; true")
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn("health failed (exit 124)", out)
        # a command that keeps failing says its own exit and output, not a timeout, also when
        # its last try had less time left than it takes to fail
        for pause in ("0.1", "0.4"):
            self.commit(health=f"sleep {pause}; echo refused-now; exit 7")
            code, out = self.tick()
            self.assertIn("health failed (exit 7)", out)
            self.assertIn("refused-now", out)
        # one try may take as much of the health time as it needs
        slow = self.commit(health="sleep 1.5; true", health_seconds=3)
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.live(), slow)
        # one failed try does not end it while time is left
        flaky = self.commit(health="test -f tried || { touch tried; exit 1; }")
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.live(), flaky)
        # a pass counts only within the time, however slow the command was to start
        delayed, popen = [], release.subprocess.Popen

        def starting(argv, **kwargs):
            if argv[-1] == "true" and not delayed:
                delayed.append(time.sleep(1.5))
            return popen(argv, **kwargs)
        self.commit(health="true", migrate="")
        with patch.object(release.subprocess, "Popen", starting):
            code, out = self.tick()
        self.assertIn("health failed (passed after its 1s)", out)
        self.assertEqual(self.live(), flaky)

    def test_usage_and_never_root(self):
        with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()) as said:
            self.assertEqual(release.main(["release.py"]), 2)
            self.assertIn("release.py ROOT --adopt  make ROOT/repo's checked-out commit", said.getvalue())
            self.assertEqual(release.main(["release.py", str(self.root), "--now"]), 2)
            with patch.object(release.os, "geteuid", return_value=0):
                self.assertEqual(release.main(["release.py", str(self.root)]), 2)


if __name__ == "__main__":
    unittest.main()
