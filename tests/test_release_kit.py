"""The release kit releases only commits ak stamped and puts the previous release back by itself."""

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
CONFIG = """units = {units}
python = "{python}"
health = "{health}"
health_seconds = 1
migrate = "{migrate}"
unit_files = "deploy/systemd"
keep = {keep}
{extra}
"""


class ReleaseKit(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-release-kit-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.origin, self.work, self.root = base / "origin.git", base / "work", base / "acme"
        self.units = base / "units"
        self.units.mkdir()
        self.calls = base / "systemctl.log"
        self.failing = base / "fail"          # a file per systemctl verb that fails once
        self.failing.mkdir()
        self.state = base / "state"           # active.<unit> and enabled.<unit>, systemd's view
        self.state.mkdir()
        fake = base / "systemctl"
        fake.write_text(f"""#!/bin/sh
echo "$*" >> {self.calls}
if [ -f {self.failing}/"$1" ]; then rm {self.failing}/"$1"; exit 1; fi
verb=$1; shift
case $verb in
  restart) for u; do touch {self.state}/active.$u; done ;;
  enable) for u; do [ -e {self.units}/$u ] || exit 1; done
          for u; do touch {self.state}/enabled.$u; done ;;
  disable) [ -e {self.units}/$2 ] || exit 1; rm -f {self.state}/active.$2 {self.state}/enabled.$2 ;;
  show) a=inactive; [ -f {self.state}/active.$5 ] && a=active
        f=; [ -e {self.units}/$5 ] && f=disabled; [ -f {self.state}/enabled.$5 ] && f=enabled
        printf 'ActiveState=%s\\nUnitFileState=%s\\n' $a $f ;;
esac
""")
        fake.chmod(0o755)
        # a stand-in interpreter: `python -m venv DIR` makes a virtualenv whose pip logs the
        # requirements file it was given
        self.python = base / "python"
        self.python.write_text('#!/bin/sh\nmkdir -p "$3/bin"\n'
                               'printf \'#!/bin/sh\\necho "$4" >> %s/installs\\n\' "$PWD/$3" > "$3/bin/pip"\n'
                               'chmod +x "$3/bin/pip"\n')
        self.python.chmod(0o755)
        for name, value in (("SYSTEMCTL", str(fake)), ("UNIT_DIR", self.units)):
            patcher = patch.object(release, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(base, "clone", "-q", str(self.origin), str(self.work))
        self.first = self.commit()
        self.root.mkdir()
        self.git(base, "clone", "-q", str(self.origin), str(self.root / "repo"))

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                              text=True, env=GIT_ENV).stdout.strip()

    def commit(self, healthy=True, stamp=True, migrate="true", units=("v1",), keep=5,
               files=None, extra="", health="test -f healthy", configured=("acme.service",),
               merge=None):
        work = self.work
        systemd = work / "deploy" / "systemd"
        if systemd.exists():
            for old in systemd.iterdir():
                old.unlink()
        systemd.mkdir(parents=True, exist_ok=True)
        (work / "deploy" / "release.toml").write_text(CONFIG.format(
            migrate=migrate, keep=keep, python=self.python, extra=extra, health=health,
            units="[" + ", ".join(f'"{u}"' for u in configured) + "]"))
        for index, version in enumerate(units):
            name = "acme.service" if index == 0 else f"acme-extra{index}.service"
            (systemd / name).write_text(f"[Service]\n# {version}\n")
        (work / "healthy").unlink(missing_ok=True)
        if healthy:
            (work / "healthy").write_text("yes\n")
        count = work / "counter"
        count.write_text(f"{int(count.read_text()) + 1 if count.exists() else 0}\n")
        for name, text in (files or {}).items():
            (work / name).write_text(text)
        self.git(work, "add", "-A")
        tree = self.git(work, "write-tree")
        message = f"acme change\n\n{release.STAMP}: {tree}\n" if stamp else "acme change\n"
        has_head = subprocess.run(["git", "-C", str(work), "rev-parse", "-q", "--verify", "HEAD"],
                                  capture_output=True, env=GIT_ENV).returncode == 0
        parents = (["-p", "HEAD"] if has_head else []) + (["-p", merge] if merge else [])
        sha = self.git(work, "commit-tree", tree, *parents, "-m", message)
        self.git(work, "reset", "-q", "--hard", sha)
        self.git(work, "push", "-q", "--force", "origin", "HEAD:main")
        return sha

    def tick(self, *extra):
        out = io.StringIO()
        with redirect_stdout(out):
            code = release.main(["release.py", str(self.root), *extra])
        if extra == ("--adopt",) and code == 0:
            # an adopted host already runs its release's units, installed by hand
            for unit in (self.root / "current" / "deploy" / "systemd").iterdir():
                if not (self.units / unit.name).exists():
                    (self.units / unit.name).write_bytes(unit.read_bytes())
        return code, out.getvalue()

    def live(self):
        return (self.root / "released").read_text().split()[0]

    def current(self):
        return os.readlink(self.root / "current")

    def calls_made(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def running(self, unit):
        return (self.state / f"active.{unit}").exists()

    def enabled(self, unit):
        return (self.state / f"enabled.{unit}").exists()

    def host_unit(self, unit):
        """A unit installed on the host by hand, running and enabled."""
        (self.units / unit).write_text("[Service]\n")
        (self.state / f"active.{unit}").touch()
        (self.state / f"enabled.{unit}").touch()

    def test_adopt_then_release_the_newest_stamped_commit_only(self):
        self.assertEqual(self.tick("--adopt")[0], 0)
        self.assertEqual(self.live(), self.first)
        self.assertEqual(self.calls_made(), [])       # adopting restarts nothing
        stamped = self.commit()
        self.commit(stamp=False)                      # untested: never released on its own
        code, out = self.tick()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.live(), stamped)
        self.assertEqual(self.current(), f"releases/{stamped}")
        self.assertIn("restart acme.service", self.calls_made())
        self.assertTrue(self.enabled("acme.service"))
        self.assertEqual(self.tick(), (0, ""))        # nothing newer: a quiet tick

    def test_a_failing_health_puts_the_previous_release_back(self):
        self.tick("--adopt")
        (self.units / "acme.service").write_text("[Service]\n# v1\n")
        (self.units / "acme-host.service").write_text("[Service]\n")
        broken = self.commit(healthy=False, units=("v2", "extra"),
                             configured=("acme.service", "acme-extra1.service",
                                         "acme-host.service"))
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live", out)
        self.assertEqual(self.live(), self.first)
        self.assertEqual(self.current(), f"releases/{self.first}")
        self.assertEqual((self.units / "acme.service").read_text(), "[Service]\n# v1\n")
        # units only the failed release ran are stopped and disabled, the live one's run,
        # and a unit file only the failed release brought is gone again
        for unit in ("acme-extra1.service", "acme-host.service"):
            self.assertFalse(self.running(unit) or self.enabled(unit), unit)
        self.assertFalse((self.units / "acme-extra1.service").exists())
        self.assertTrue(self.running("acme.service") and self.enabled("acme.service"))
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
        self.git(repo, "fetch", "-q", "--prune", "origin", "+refs/heads/main:refs/remotes/origin/main")
        self.git(repo, "reflog", "expire", "--expire=now", "--all")
        self.git(repo, "gc", "-q", "--prune=now")
        self.assertEqual(self.tick(), (0, ""))
        self.assertEqual(self.live(), self.first)

    def test_a_unit_the_failed_release_never_installed_needs_no_retiring(self):
        self.tick("--adopt")
        # its config names a unit with no file anywhere: enabling it fails after the switch
        broken = self.commit(configured=("acme.service", "acme-extra1.service"))
        code, out = self.tick()
        self.assertEqual(code, 1, out)
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live", out)
        self.assertFalse((self.root / "attempt").exists())

    def test_a_unit_the_new_release_no_longer_names_is_stopped_and_disabled(self):
        self.first = self.commit(configured=("acme.service", "acme-worker.service"))
        self.git(self.root / "repo", "pull", "-q", "origin", "main")
        self.tick("--adopt")
        self.host_unit("acme-worker.service")
        self.commit()
        self.assertEqual(self.tick()[0], 0)
        self.assertFalse(self.running("acme-worker.service") or self.enabled("acme-worker.service"))

    def test_a_restore_enables_the_units_a_failed_release_retired(self):
        self.first = self.commit(configured=("acme.service", "acme-worker.service"))
        self.git(self.root / "repo", "pull", "-q", "origin", "main")
        self.tick("--adopt")
        self.host_unit("acme-worker.service")
        self.commit(healthy=False)
        self.assertEqual(self.tick()[0], 1)
        self.assertTrue(self.running("acme-worker.service") and self.enabled("acme-worker.service"))

    def releases(self):
        return {p.name for p in (self.root / "releases").iterdir()}

    def test_keep_zero_leaves_the_live_and_the_previous_release(self):
        self.tick("--adopt")
        previous = self.commit(keep=0)
        self.assertEqual(self.tick()[0], 0)
        newest = self.commit(keep=0)
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.tick(), (0, ""))          # every tick prunes first
        self.assertEqual(self.releases(), {newest, previous})

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

    def test_a_failure_after_the_switch_restores_whatever_it_was(self):
        self.tick("--adopt")
        (self.failing / "restart").write_text("")         # the new release's restart fails once
        broken = self.commit()
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live: systemctl restart", out)
        self.assertEqual(self.current(), f"releases/{self.first}")

    def test_a_failed_restore_keeps_its_attempt_until_a_later_tick_finishes_it(self):
        self.tick("--adopt")
        broken = self.commit(healthy=False, units=("v1", "extra"),
                             configured=("acme.service", "acme-extra1.service"))
        (self.failing / "disable").write_text("")         # retiring the brought unit fails once
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn("the next tick tries again", out)
        self.assertTrue((self.root / "attempt").exists())
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live", out)
        self.assertFalse(self.running("acme-extra1.service"))
        self.assertEqual(self.tick(), (0, ""))
        # a tick cut off right after the switch: the next one puts the live release back
        newer = self.commit()
        self.cut_off(newer, switched=True)
        code, out = self.tick()
        self.assertIn(f"{newer[:12]} failed and {self.first[:12]} is back live: the tick "
                      "releasing it was cut off", out)
        self.assertEqual(self.current(), f"releases/{self.first}")

    def cut_off(self, sha, switched):
        repo = self.root / "repo"
        self.git(repo, "fetch", "-q", "origin", "+refs/heads/main:refs/remotes/origin/main")
        config, _ = release.prepare(self.root, sha)
        (self.root / "attempt").write_text(f"{sha} {self.live()}\n")
        if switched:
            release.save_units(self.root, sorted(release.unit_files(repo, config, sha)))
            release.switch(self.root, sha)

    def test_an_attempt_that_never_switched_changes_nothing_live_and_is_tried_again(self):
        self.tick("--adopt")
        newer = self.commit()
        self.cut_off(newer, switched=False)
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{newer[:12]} not released, nothing live changed: the tick releasing it "
                      "was cut off", out)
        self.assertEqual(self.calls_made(), [])
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

    def test_a_host_failure_before_the_switch_is_tried_again(self):
        self.tick("--adopt")
        newer = self.commit()
        git = release.git

        def refused(repo, *args, **kwargs):
            if args[:2] == ("worktree", "add"):
                raise release.Failed("git worktree add: a lock held elsewhere")
            return git(repo, *args, **kwargs)
        with patch.object(release, "git", refused):
            code, out = self.tick()
        self.assertIn(f"{newer[:12]} not released, nothing live changed: git worktree add", out)
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.live(), newer)

    def test_a_restore_puts_back_the_host_unit_files_a_failed_release_replaced(self):
        units = ("acme.service", "acme-worker.service")
        self.first = self.commit(configured=units)
        self.git(self.root / "repo", "pull", "-q", "origin", "main")
        self.tick("--adopt")
        self.host_unit("acme-worker.service")
        host = "[Service]\nExecStart=/opt/acme/current/old-worker\n"
        (self.units / "acme-worker.service").write_text(host)
        self.commit(healthy=False, configured=units, files={
            "deploy/systemd/acme-worker.service": "[Service]\nExecStart=/new-worker\n"})
        code, out = self.tick()
        self.assertIn("is back live", out)
        self.assertEqual((self.units / "acme-worker.service").read_text(), host)

    def test_a_retirement_systemd_cannot_confirm_fails(self):
        self.first = self.commit(configured=("acme.service", "acme-worker.service"))
        self.git(self.root / "repo", "pull", "-q", "origin", "main")
        self.tick("--adopt")
        self.host_unit("acme-worker.service")
        self.commit()
        (self.failing / "show").write_text("")
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn("is back live: systemctl show", out)
        self.assertEqual(self.live(), self.first)

    def test_root_reads_the_config_and_unit_files_from_the_commit_never_the_release(self):
        self.tick("--adopt")
        live = self.root / "releases" / self.first
        (live / "deploy" / "release.toml").write_text('units = ["acme.service"]\nhealth = "false"')
        (live / "deploy" / "systemd" / "acme.service").write_text("[Service]\nExecStart=/bin/x\n")
        broken = self.commit(healthy=False)
        code, out = self.tick()
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live", out)
        self.assertEqual((self.units / "acme.service").read_text(), "[Service]\n# v1\n")

    def test_a_health_that_passes_only_after_its_time_fails(self):
        self.tick("--adopt")
        self.commit(health="sleep 3; true")
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn("health failed (exit 124)", out)
        # a pass counts only within the time, however slow the command was to start
        slow, environment = [], release.environment

        def starting(config):
            if not slow:
                slow.append(time.sleep(1.5))
            return environment(config)
        self.commit(health="true", migrate="")              # health is the first command
        with patch.object(release, "environment", starting):
            code, out = self.tick()
        self.assertIn("health failed (passed after its 1s)", out)
        self.assertEqual(self.live(), self.first)

    def test_the_command_drops_to_the_user_before_it_starts(self):
        seen = {}

        class Started(Exception):
            pass

        def popen(argv, **kwargs):
            seen.update(kwargs, argv=argv)
            raise Started
        entry = type("Entry", (), {"pw_uid": 4321, "pw_gid": 4321, "pw_dir": str(self.root)})
        with patch.object(release.pwd, "getpwnam", return_value=entry), \
                patch.object(release.os, "getgrouplist", return_value=[4321, 27]), \
                patch.object(release.subprocess, "Popen", popen), self.assertRaises(Started):
            release.run({"user": "acme-app"}, self.root, ["bash", "-c", "true"])
        self.assertEqual(seen["argv"], ["bash", "-c", "true"])       # no launcher root runs
        self.assertEqual((seen["user"], seen["group"], seen["extra_groups"]), (4321, 4321, [4321, 27]))

    def test_a_linked_env_file_is_refused(self):
        target = self.root / "secret"
        target.write_text("TOKEN=root-only\n")
        (self.root / "app.env").symlink_to(target)
        code, out = release.run({"env_file": str(self.root / "app.env")}, self.root, ["true"])
        self.assertEqual(code, 1)
        self.assertIn("OSError", out)

    def test_a_command_s_group_ends_before_its_leader_is_reaped(self):
        states, killpg = [], os.killpg

        def ending(pid, sig):
            # raises ChildProcessError once the leader is reaped and its id free for reuse
            states.append(os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT))
            killpg(pid, sig)
        with patch.object(release.os, "killpg", ending):
            self.assertEqual(release.run({}, self.root, ["true"])[0], 0)
            self.assertEqual(release.run({}, self.root, ["sleep", "5"], 0.2)[0], 124)
        self.assertIsNotNone(states[0])

    def test_a_linked_unit_file_is_replaced_never_written_through(self):
        self.tick("--adopt")
        source = self.root / "releases" / self.first / "deploy" / "systemd" / "acme.service"
        (self.units / "acme.service").unlink()
        (self.units / "acme.service").symlink_to(source)
        self.commit(healthy=False, units=("v2",))
        self.assertEqual(self.tick()[0], 1)
        self.assertEqual(source.read_text(), "[Service]\n# v1\n")
        self.assertEqual(os.readlink(self.units / "acme.service"), str(source))   # put back

    def test_a_command_s_leftover_children_end_with_it(self):
        self.tick("--adopt")
        self.commit(health="(sleep 1; touch late) & exit 1")
        self.assertEqual(self.tick()[0], 1)
        time.sleep(1.5)
        self.assertEqual(list((self.root / "releases").glob("*/late")), [])

    def test_a_failing_migration_changes_nothing_live(self):
        self.tick("--adopt")
        broken = self.commit(migrate="echo schema refused >&2; exit 3")
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} not released, nothing live changed: migrate failed (exit 3)", out)
        self.assertIn("schema refused", out)
        self.assertEqual(self.current(), f"releases/{self.first}")
        self.assertEqual(self.calls_made(), [])
        self.assertIn("migrate failed", self.tick()[1])     # nothing live changed: tried again

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

    def test_each_release_installs_its_own_virtualenv(self):
        self.tick("--adopt")
        name = "production requirements.txt"
        one = self.commit(extra=f'requirements = "{name}"', files={name: "acme==1\n"})
        self.assertEqual(self.tick()[0], 0)
        two = self.commit(extra=f'requirements = "{name}"', files={name: "acme==1\n"})
        self.assertEqual(self.tick()[0], 0)
        for sha in (one, two):
            venv = self.root / "releases" / sha / ".venv"
            self.assertTrue(venv.is_dir() and not venv.is_symlink())
            self.assertEqual((venv / "installs").read_text(), f"{name}\n")

    def test_failed_releases_obey_the_keep_count(self):
        self.tick("--adopt")
        for index in range(5):
            self.commit(keep=2, healthy=index % 2 == 0, migrate="true" if index % 3 else "exit 1")
            self.tick()
        self.tick()
        self.assertLessEqual(len(self.releases()), 4)       # two besides live and previous

    def test_usage(self):
        with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
            self.assertEqual(release.main(["release.py"]), 2)
            self.assertEqual(release.main(["release.py", str(self.root), "--now"]), 2)


if __name__ == "__main__":
    unittest.main()
