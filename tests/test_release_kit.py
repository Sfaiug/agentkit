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
health_seconds = 0
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
        fake = base / "systemctl"
        fake.write_text(f'#!/bin/sh\necho "$*" >> {self.calls}\n'
                        f'if [ -f {self.failing}/"$1" ]; then rm {self.failing}/"$1"; exit 1; fi\n')
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
        return code, out.getvalue()

    def live(self):
        return (self.root / "released").read_text().split()[0]

    def current(self):
        return os.readlink(self.root / "current")

    def calls_made(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

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
        self.assertEqual(self.tick(), (0, ""))        # nothing newer: a quiet tick

    def test_a_failing_health_puts_the_previous_release_back(self):
        self.tick("--adopt")
        (self.units / "acme.service").write_text("[Service]\n# v1\n")
        broken = self.commit(healthy=False, units=("v2", "extra"),
                             configured=("acme.service", "acme-host.service"))
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live", out)
        self.assertEqual(self.live(), self.first)
        self.assertEqual(self.current(), f"releases/{self.first}")
        self.assertEqual((self.units / "acme.service").read_text(), "[Service]\n# v1\n")
        # a unit file only the failed release brought is stopped and removed, and a unit
        # only its configuration named is stopped
        self.assertFalse((self.units / "acme-extra1.service").exists())
        self.assertIn("disable --now acme-extra1.service", self.calls_made())
        self.assertIn("stop acme-host.service", self.calls_made())
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
        broken = self.commit(healthy=False, units=("v1", "extra"))
        (self.failing / "disable").write_text("")         # stopping the brought unit fails once
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn("the next tick tries again", out)
        self.assertTrue((self.root / "attempt").exists())
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live", out)
        self.assertFalse((self.units / "acme-extra1.service").exists())
        self.assertEqual(self.tick(), (0, ""))
        # a tick cut off right after the switch: the next one puts the live release back
        newer = self.commit()
        self.git(self.root / "repo", "fetch", "-q", "origin", "+refs/heads/main:refs/remotes/origin/main")
        release.build(self.root, newer)
        (self.root / "attempt").write_text(f"{newer} {self.first}\n")
        release.switch(self.root, newer)
        code, out = self.tick()
        self.assertIn("the tick releasing it was cut off", out)
        self.assertEqual(self.current(), f"releases/{self.first}")

    def test_a_linked_unit_file_is_replaced_never_written_through(self):
        self.tick("--adopt")
        source = self.root / "releases" / self.first / "deploy" / "systemd" / "acme.service"
        (self.units / "acme.service").symlink_to(source)
        self.commit(healthy=False, units=("v2",))
        self.assertEqual(self.tick()[0], 1)
        self.assertEqual(source.read_text(), "[Service]\n# v1\n")
        installed = self.units / "acme.service"
        self.assertFalse(installed.is_symlink())
        self.assertEqual(installed.read_text(), "[Service]\n# v1\n")

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
        self.assertLessEqual(len(list((self.root / "releases").iterdir())), 3)

    def test_usage(self):
        with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
            self.assertEqual(release.main(["release.py"]), 2)
            self.assertEqual(release.main(["release.py", str(self.root), "--now"]), 2)


if __name__ == "__main__":
    unittest.main()
