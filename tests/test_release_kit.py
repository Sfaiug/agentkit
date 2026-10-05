"""The release kit releases only commits ak stamped and puts the previous release back by itself."""

from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", REPO / "tools" / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "acme", "GIT_AUTHOR_EMAIL": "acme@localhost",
           "GIT_COMMITTER_NAME": "acme", "GIT_COMMITTER_EMAIL": "acme@localhost"}
CONFIG = """units = ["acme.service"]
python = "{python}"
health = "test -f healthy{built}"
health_seconds = 0
migrate = "{migrate}"
unit_files = "deploy/systemd"
keep = {keep}
{install}
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
        self.fail_restart = base / "fail-restart"
        fake = base / "systemctl"
        fake.write_text(f'#!/bin/sh\necho "$*" >> {self.calls}\n'
                        f'[ "$1" = restart ] && [ -f {self.fail_restart} ] && exit 1\nexit 0\n')
        fake.chmod(0o755)
        # a stand-in interpreter: `python -m venv DIR` makes a virtualenv whose pip logs installs
        self.python = base / "python"
        self.python.write_text('#!/bin/sh\nmkdir -p "$3/bin"\n'
                               'printf \'#!/bin/sh\\necho "$*" >> %s/installs\\n\' "$3" > "$3/bin/pip"\n'
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
               files=None, install=None):
        work = self.work
        systemd = work / "deploy" / "systemd"
        if systemd.exists():
            for old in systemd.iterdir():
                old.unlink()
        systemd.mkdir(parents=True, exist_ok=True)
        (work / "deploy" / "release.toml").write_text(CONFIG.format(
            migrate=migrate, keep=keep, python=self.python,
            built=" && test -f built" if install else "",
            install=f'install = "{install}"' if install else ""))
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
        self.git(work, "commit", "-q", "-m", message)
        self.git(work, "push", "-q", "--force", "origin", "HEAD:main")
        return self.git(work, "rev-parse", "HEAD")

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
        broken = self.commit(healthy=False, units=("v2", "extra"))
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live", out)
        self.assertEqual(self.live(), self.first)
        self.assertEqual(self.current(), f"releases/{self.first}")
        self.assertEqual((self.units / "acme.service").read_text(), "[Service]\n# v1\n")
        # a unit only the failed release added is stopped and its file removed
        self.assertFalse((self.units / "acme-extra1.service").exists())
        self.assertIn("disable --now acme-extra1.service", self.calls_made())
        self.assertFalse((self.root / "attempt").exists())
        # the failed commit waits for a newer one
        self.assertEqual(self.tick(), (0, ""))
        fixed = self.commit()
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.live(), fixed)

    def test_a_failed_tip_is_a_floor_its_older_parents_wait_behind(self):
        self.tick("--adopt")
        self.commit()
        self.commit(healthy=False)
        self.assertEqual(self.tick()[0], 1)
        self.assertEqual(self.tick(), (0, ""))
        self.assertEqual(self.live(), self.first)

    def test_a_host_error_after_the_switch_still_restores(self):
        self.tick("--adopt")
        (self.units / "acme.service").write_text("[Service]\n# v1\n")
        (self.units / "acme.service").chmod(0o444)     # the new unit file cannot be written
        broken = self.commit(units=("v2",))
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live: PermissionError", out)
        self.assertEqual(self.current(), f"releases/{self.first}")

    def test_a_cut_off_or_failed_restore_finishes_on_a_later_tick(self):
        self.tick("--adopt")
        broken = self.commit(healthy=False)
        self.fail_restart.write_text("")
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn("the next tick tries again", out)
        self.assertTrue((self.root / "attempt").exists())
        self.fail_restart.unlink()
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live", out)
        self.assertEqual(self.current(), f"releases/{self.first}")
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
        self.git(self.work, "checkout", "-q", "-b", "side", self.first)
        self.commit(files={"side.txt": "side\n"})     # an older line, stamped, force-pushed
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"main no longer contains the live release {newer[:12]}", out)
        self.assertEqual(self.live(), newer)

    def test_no_live_release_asks_to_adopt(self):
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn("--adopt", out)

    def test_an_install_runs_without_requirements(self):
        self.tick("--adopt")
        built = self.commit(install="touch built")
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.live(), built)

    def test_virtualenvs_follow_their_requirements_and_includes(self):
        self.tick("--adopt")
        self.commit(files={"requirements.txt": "-r deps.txt\n", "deps.txt": "acme==1\n"})
        self.assertEqual(self.tick()[0], 0)
        first = os.path.realpath(self.root / "current" / ".venv")
        self.assertEqual(Path(first, "installs").read_text(), "install -q -r requirements.txt\n")
        self.commit(files={"deps.txt": "acme==1\n"})       # unchanged: reused, not reinstalled
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(os.path.realpath(self.root / "current" / ".venv"), first)
        self.commit(files={"deps.txt": "acme==2\n"})       # an included file changed: fresh
        self.assertEqual(self.tick()[0], 0)
        self.assertNotEqual(os.path.realpath(self.root / "current" / ".venv"), first)

    def test_keeps_the_newest_releases_and_their_virtualenvs(self):
        self.tick("--adopt")
        for index in range(4):
            self.commit(keep=2, files={"requirements.txt": f"# acme {index % 2}\n"})
            self.assertEqual(self.tick()[0], 0)
        releases = sorted(p.name for p in (self.root / "releases").iterdir())
        self.assertLessEqual(len(releases), 3)         # keep 2, and the previous release
        self.assertIn(self.live(), releases)
        venvs = {os.path.realpath(self.root / "releases" / r / ".venv") for r in releases
                 if (self.root / "releases" / r / ".venv").is_symlink()}
        self.assertEqual({str(p) for p in (self.root / "venvs").iterdir()}, venvs)
        self.assertTrue(all((Path(v) / ".complete").is_file() for v in venvs))

    def test_a_failed_virtualenv_changes_nothing_live(self):
        self.tick("--adopt")
        self.python.write_text('#!/bin/sh\necho no venv module >&2; exit 1\n')
        broken = self.commit(files={"requirements.txt": "acme==1\n"})
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} not released, nothing live changed", out)
        self.assertIn("no venv module", out)
        self.assertEqual(self.current(), f"releases/{self.first}")

    def test_usage(self):
        with redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
            self.assertEqual(release.main(["release.py"]), 2)
            self.assertEqual(release.main(["release.py", str(self.root), "--now"]), 2)


if __name__ == "__main__":
    unittest.main()
