"""A shim runs the real tool behind it: the next one on PATH, with the caller's Python variables.

Every tool a seat runs through ak's shims (tmux, gh, git, scp, rsync, sftp) must still be that
tool.  The shim runs the first real one after itself on PATH, so a wrapper ahead of it that calls
it never loops; a folder or a file that cannot run is no tool; with none it says so and exits
127, as a shell does for a missing command.  The real tool gets the caller's PYTHONPATH and
PYTHONSAFEPATH as they were, so a project's own Python tools import as they would bare.  And a
shim whose guard cannot load runs the call untouched rather than failing: a broken install must
not take a seat's tmux and git with it.  Black-box: the shims a seat's launch installs
(tests/fixtures/shims.py), run as a seat's commands in front of real tools of the test's own
that keep each call; this test fails against `/bin/false`.
"""

import os
from pathlib import Path
import shlex
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import LOG, REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.shims import Shims

TOOLS = ("git", "gh", "tmux", "scp", "rsync", "sftp")
KEYS = ("PYTHONPATH", "PYTHONSAFEPATH")
# A real tool that keeps each call: its arguments and the Python variables it was handed.
REAL = """#!{python}
import json, os, sys
with open({log!r}, "a") as log:
    print(json.dumps([sys.argv[1:], [os.environ.get(key) for key in {keys!r}]]), file=log)
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ShimLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.shims = Shims(cls.home)
        # a folder of the tool's name, and a file of it that cannot run: neither is a tool
        cls.folder, cls.plain = cls.home.root / "folder", cls.home.root / "plain"
        (cls.folder / "git").mkdir(parents=True)
        cls.plain.mkdir()
        (cls.plain / "git").write_text("#!/bin/sh\nexit 0\n")

    def real(self, folder, tool="git"):
        """A real `tool` alone in a folder; `calls(folder, tool)` is what it was handed."""
        path = self.home.root / folder / tool
        path.parent.mkdir(exist_ok=True)
        path.write_text(REAL.format(python=sys.executable, keys=KEYS,
                                    log=str(self.home.log(f"{folder}-{tool}"))))
        path.chmod(0o755)
        return path.parent

    def calls(self, folder, tool="git"):
        return self.home.calls(f"{folder}-{tool}")

    def run_on(self, *path, argv=("git", "status"), seat="acme", env=None):
        """Run a seat's command with exactly these folders as its PATH."""
        env = {**self.shims.env(seat), "PATH": os.pathsep.join(map(str, path)), **(env or {})}
        return self.home.run(*argv, env=env, timeout=30)

    def test_with_no_real_tool_on_path_a_shim_says_so_and_exits_127(self):
        for seat in ("acme", None):
            with self.subTest(seat=seat):
                done = self.run_on(self.shims.dir, self.folder, self.plain,
                                   argv=("git", "--version"), seat=seat)
                self.assertEqual((done.code, done.err), (127, "git-shim: no real git on PATH\n"))

    def test_a_shim_runs_the_first_real_tool_after_itself(self):
        real, later = self.real("first"), self.real("later")
        for seat in ("acme", None):
            with self.subTest(seat=seat):
                done = self.run_on(self.shims.dir, self.folder, self.plain, real, later,
                                   self.home.env["PATH"], seat=seat)
                self.assertEqual(done.code, 0, done.err)
        self.assertEqual([argv for argv, _ in self.calls("first")], [["status"], ["status"]])
        self.assertEqual(self.calls("later"), [])

    def test_a_wrapper_ahead_of_the_shim_that_calls_it_reaches_the_real_tool_once(self):
        real = self.real("behind")
        wrapper = self.home.root / "wrapper" / "git"
        wrapper.parent.mkdir()
        wrapper.write_text(LOG.format(python=shlex.quote(sys.executable),
                                      log=shlex.quote(str(self.home.log("wrapper-git"))))
                           + f'exec {shlex.quote(str(self.shims.dir / "git"))} "$@"\n')
        wrapper.chmod(0o755)
        for seat in ("acme", None):
            with self.subTest(seat=seat):
                done = self.run_on(wrapper.parent, self.shims.dir, real, self.home.env["PATH"],
                                   seat=seat)
                self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.calls("wrapper"), [["status"], ["status"]])
        self.assertEqual([argv for argv, _ in self.calls("behind")], [["status"], ["status"]])

    def test_a_shim_run_by_its_path_off_path_runs_the_first_real_tool_on_path(self):
        real = self.real("only")
        for seat in ("acme", None):
            with self.subTest(seat=seat):
                done = self.run_on(real, self.home.env["PATH"], seat=seat,
                                   argv=(str(self.shims.dir / "git"), "status"))
                self.assertEqual(done.code, 0, done.err)
        self.assertEqual([argv for argv, _ in self.calls("only")], [["status"], ["status"]])

    def test_the_real_tool_gets_the_callers_python_variables_as_they_were(self):
        real = [self.real("python", tool) for tool in TOOLS][0]
        for given in ({}, {"PYTHONPATH": "/nowhere", "PYTHONSAFEPATH": "1"},
                      dict.fromkeys(KEYS, "")):
            for tool in TOOLS:
                with self.subTest(tool=tool, given=given):
                    done = self.run_on(self.shims.dir, real, self.home.env["PATH"],
                                       argv=(tool, "--version"),
                                       env={key: given.get(key) for key in KEYS})
                    self.assertEqual(done.code, 0, done.err)
                    self.assertEqual(self.calls("python", tool)[-1],
                                     [["--version"], [given.get(key) for key in KEYS]])

    def test_a_shim_whose_guard_cannot_load_runs_the_real_command_untouched(self):
        # the build's own shim, copied to a folder where nothing it would load lies beside it
        lone = self.home.root / "lone"
        (lone / "tools").mkdir(parents=True)
        (lone / "bin").mkdir()
        shutil.copy(os.path.realpath(self.shims.dir / "tmux"), lone / "tools" / "shim")
        (lone / "bin" / "tmux").symlink_to(lone / "tools" / "shim")
        real = self.real("fallback", "tmux")
        Seat(self.home, "beta", alive=False)
        given = {"PYTHONPATH": "/nowhere", "PYTHONSAFEPATH": "1"}
        # one call the guard would weigh refusing, and one it would add to
        calls = (["kill-session", "-t", "beta"], ["new-window", "-d"])
        for argv in calls:
            with self.subTest(argv=argv):
                done = self.run_on(lone / "bin", real, self.home.env["PATH"],
                                   argv=("tmux", *argv), env=given)
                self.assertEqual(done.code, 0, done.err)
        self.assertEqual(self.calls("fallback", "tmux"),
                         [[argv, ["/nowhere", "1"]] for argv in calls])


if __name__ == "__main__":
    unittest.main()
