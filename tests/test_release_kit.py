"""The release kit releases only commits ak stamped and puts the previous release back by itself."""

from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
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
install = "echo installed >> .venv/installs"
health = "test -f healthy"
health_seconds = 0
migrate = "{migrate}"
unit_files = "deploy/systemd"
keep = {keep}
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
        fake = base / "systemctl"
        fake.write_text(f'#!/bin/sh\necho "$*" >> {self.calls}\n')
        fake.chmod(0o755)
        # a stand-in interpreter: `python -m venv DIR` makes the folder a virtualenv lives in
        self.python = base / "python"
        self.python.write_text('#!/bin/sh\nmkdir -p "$3/bin"\n')
        self.python.chmod(0o755)
        for name, value in (("SYSTEMCTL", str(fake)), ("UNIT_DIR", self.units)):
            patcher = patch.object(release, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(base, "clone", "-q", str(self.origin), str(self.work))
        self.first = self.commit(healthy=True)
        self.root.mkdir()
        self.git(base, "clone", "-q", str(self.origin), str(self.root / "repo"))

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                              text=True, env=GIT_ENV).stdout.strip()

    def commit(self, healthy=True, stamp=True, migrate="true", unit="v1", keep=5,
               requirements=None):
        work = self.work
        (work / "deploy" / "systemd").mkdir(parents=True, exist_ok=True)
        (work / "deploy" / "release.toml").write_text(
            CONFIG.format(migrate=migrate, keep=keep, python=self.python))
        (work / "deploy" / "systemd" / "acme.service").write_text(f"[Service]\n# {unit}\n")
        (work / "healthy").unlink(missing_ok=True)
        if healthy:
            (work / "healthy").write_text("yes\n")
        (work / "counter").write_text(f"{len(list(self.counter()))}\n")
        if requirements is not None:
            (work / "requirements.txt").write_text(requirements)
        self.git(work, "add", "-A")
        tree = self.git(work, "write-tree")
        message = f"acme change\n\n{release.STAMP}: {tree}\n" if stamp else "acme change\n"
        self.git(work, "commit", "-q", "-m", message)
        self.git(work, "push", "-q", "origin", "HEAD:main")
        return self.git(work, "rev-parse", "HEAD")

    def counter(self):
        path = self.work / "counter"
        return range(int(path.read_text()) + 1 if path.exists() else 0)

    def tick(self, *extra):
        out = io.StringIO()
        with redirect_stdout(out):
            code = release.main(["release.py", str(self.root), *extra])
        return code, out.getvalue()

    def live(self):
        return (self.root / "released").read_text().split()[0]

    def current(self):
        return os.readlink(self.root / "current")

    def restarts(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_adopt_then_release_the_newest_stamped_commit_only(self):
        self.assertEqual(self.tick("--adopt")[0], 0)
        self.assertEqual(self.live(), self.first)
        self.assertEqual(self.restarts(), [])        # adopting restarts nothing
        stamped = self.commit()
        self.commit(stamp=False)                     # untested: never released on its own
        code, out = self.tick()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.live(), stamped)
        self.assertEqual(self.current(), f"releases/{stamped}")
        self.assertIn("restart acme.service", self.restarts())
        self.assertEqual(self.tick(), (0, ""))       # nothing newer: a quiet tick

    def test_a_failing_health_puts_the_previous_release_back(self):
        self.tick("--adopt")
        (self.units / "acme.service").write_text("[Service]\n# v1\n")
        broken = self.commit(healthy=False, unit="v2")
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} failed and {self.first[:12]} is back live", out)
        self.assertEqual(self.live(), self.first)
        self.assertEqual(self.current(), f"releases/{self.first}")
        self.assertEqual((self.units / "acme.service").read_text(), "[Service]\n# v1\n")
        self.assertEqual(self.restarts().count("daemon-reload"), 2)
        self.assertEqual(self.restarts().count("restart acme.service"), 2)
        # the failed commit waits for a newer one
        self.assertEqual(self.tick(), (0, ""))
        fixed = self.commit()
        self.assertEqual(self.tick()[0], 0)
        self.assertEqual(self.live(), fixed)

    def test_a_failing_migration_changes_nothing_live(self):
        self.tick("--adopt")
        broken = self.commit(migrate="echo schema refused >&2; exit 3")
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} not released, nothing live changed: migrate failed (exit 3)", out)
        self.assertIn("schema refused", out)
        self.assertEqual(self.current(), f"releases/{self.first}")
        self.assertEqual(self.restarts(), [])

    def test_never_releases_backward(self):
        self.tick("--adopt")
        newer = self.commit()
        self.tick()
        self.git(self.work, "push", "-q", "--force", "origin", f"{self.first}:main")
        self.assertEqual(self.tick(), (0, ""))
        self.assertEqual(self.live(), newer)

    def test_no_earlier_release_to_restore_says_so(self):
        self.git(self.root / "repo", "checkout", "-q", "--detach", self.first)
        broken = self.commit(healthy=False)
        code, out = self.tick()
        self.assertEqual(code, 1)
        self.assertIn(f"{broken[:12]} failed and there is no earlier release to restore", out)

    def test_keeps_the_newest_releases_and_their_virtualenvs(self):
        self.tick("--adopt")
        for index in range(4):
            self.commit(keep=2, requirements=f"# acme {index % 2}\n")
            self.assertEqual(self.tick()[0], 0)
        releases = sorted(p.name for p in (self.root / "releases").iterdir())
        self.assertLessEqual(len(releases), 3)        # keep 2, and the previous release
        self.assertIn(self.live(), releases)
        venvs = {os.path.realpath(self.root / "releases" / r / ".venv") for r in releases
                 if (self.root / "releases" / r / ".venv").is_symlink()}
        self.assertEqual({str(p) for p in (self.root / "venvs").iterdir()}, venvs)
        self.assertTrue(all((Path(v) / ".complete").is_file() for v in venvs))
        # each requirements file is installed once, then its virtualenv is reused
        self.assertTrue(all((Path(v) / "installs").read_text() == "installed\n" for v in venvs))

    def test_a_failed_virtualenv_changes_nothing_live(self):
        self.tick("--adopt")
        self.python.write_text('#!/bin/sh\necho no venv module >&2; exit 1\n')
        broken = self.commit(requirements="acme==1\n")
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
