"""Git housekeeping runs at most once an hour, not on every tick.

The tick's `git housekeeping` pass keeps the time it last ran in ak's state: a tick 10 minutes
after it starts no git command, one 61 minutes after the first runs housekeeping again, and the
doctor's tick line names when it last ran.  Offline: a real throwaway repository under HOME, an
injected clock (tests/fixtures/clock.py), and a `git` on PATH that counts every git command the
tick starts before running the real one.
"""

from contextlib import redirect_stdout
import io
import os
import shlex
import shutil
import subprocess
import unittest
from unittest.mock import patch

from fixtures.clock import Clock
from fixtures.sandbox import Sandbox
from fixtures.tick import only_passes
from agentkit import config, gc, watch

MINUTE = 60
NOW = 2 * 86400


class HousekeepingHourly(Sandbox):
    def setUp(self):
        super().setUp()
        self.calls = self.root / "git-calls"
        shim = self.root / "bin"
        shim.mkdir()
        (shim / "git").write_text(f"#!/bin/sh\necho \"$*\" >> {shlex.quote(str(self.calls))}\n"
                                  f"exec {shlex.quote(shutil.which('git'))} \"$@\"\n")
        (shim / "git").chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {
            "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}",
            "GIT_CONFIG_GLOBAL": str(self.root / ".gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"}))
        repo = config.CODE / "acme"
        repo.mkdir(parents=True)
        for args in (["init", "-q", "-b", "main"],
                     ["-c", "user.name=acme", "-c", "user.email=acme@example.com",
                      "commit", "--allow-empty", "-qm", "seed"]):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        # no process of the host's holds the repository, and GitHub is not there
        self.stack.enter_context(patch.object(gc.retention, "process_dirs", return_value=[]))
        self.stack.enter_context(patch.object(watch, "gh_json", return_value=({}, "offline")))
        self.now = NOW
        clock = Clock(lambda _seconds: None)
        clock.time = lambda: self.now
        for module in (gc, watch):
            self.stack.enter_context(patch.object(module, "time", clock))

    def tick(self, at):
        """The git commands a tick `at` seconds after the first starts."""
        self.calls.unlink(missing_ok=True)
        self.now = NOW + at
        with only_passes(self.root, "git housekeeping"), redirect_stdout(io.StringIO()):
            self.assertEqual(watch.main([]), 0)
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def doctor(self, at):
        """The end of the doctor's tick line `at` seconds after the first tick."""
        self.now = NOW + at
        return watch.tick_health()[0].rsplit(" · ", 1)[1]

    def test_two_ticks_10_minutes_apart_run_housekeeping_once_and_one_61_minutes_on_again(self):
        self.assertEqual(self.doctor(0), "git housekeeping has not run yet")
        self.assertTrue(self.tick(0))
        self.assertEqual(self.doctor(MINUTE), "git housekeeping ran 1m ago")
        self.assertEqual(self.tick(10 * MINUTE), [])
        self.assertEqual(self.doctor(30 * MINUTE), "git housekeeping ran 30m ago")
        self.assertTrue(self.tick(61 * MINUTE))
        self.assertEqual(self.doctor(65 * MINUTE), "git housekeeping ran 4m ago")


if __name__ == "__main__":
    unittest.main()
