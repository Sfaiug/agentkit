"""A launch whose worker box cannot start is refused before it makes anything, saying why.

`ak run` with one task file, with several and with `--review-pr` each first check that this
host can start a worker's box: bubblewrap on PATH, a probe of it that does not fail, Git in a
directory PATH names in full, and every credential folder open to the user, as the box must see
what it hides.  A refusal exits 2 with `ak run: <reason>` and nothing else: no run or job
directory, no harness turn, no call to GitHub, no branch or worktree.  A probe still silent
after its 10 seconds is a loaded host rather than one that cannot nest a box, so the launch
goes on.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on a project from gitrig.py, a config from akconfig.py, tasks from
taskfile.py and scripted harnesses from fakeadapter.py; a fake `bwrap` stands in for the host's
and takes whatever arguments it is given.
"""

import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

INSTALL = "sudo apt-get install -y bubblewrap"
NESTING = "the host must allow nested unprivileged user and PID namespaces"
WORDS = "bwrap: setting up uid map: Permission denied"
# Each kernel setting that keeps a box from nesting: its value doing so, and the one that lets it.
SETTINGS = (("unprivileged_userns_clone", "0", "1"),
            ("apparmor_restrict_unprivileged_userns", "1", "0"))
SPLIT_IT = ("4 done-when checks: a task has at most 3, one behaviour a reviewer holds in one "
            "read; split it")


def remedy():
    """What this host's kernel settings call for: the first keeping a box from nesting turned
    the other way, else bubblewrap installed."""
    for name, closed, opened in SETTINGS:
        try:
            if Path("/proc/sys/kernel", name).read_text().strip() == closed:
                return f"sudo sysctl -w kernel.{name}={opened}"
        except OSError:
            continue
    return INSTALL


class RefusedAtLaunch(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.rig = Rig(home, "widgets")
        akconfig.write(home, ["opus", "astra"])
        self.fakes = fakeadapter.install(home, claude="work", codex="pass")
        tasks = [str(taskfile.write(home, self.rig.path, title))
                 for title in ("Add retry file", "Add other file")]
        self.launches = {"one task": tasks[:1], "several tasks": tasks, "a PR to review":
                         ["--review-pr", "https://github.com/acme/widgets/pull/7"]}

    def bwrap(self, script):
        """A bwrap ahead of the host's on the Home's PATH, running `script`."""
        self.home.fake("bwrap", f"#!/bin/sh\n{script}\n")

    def without(self, name, *ahead):
        """A PATH of the Home's fakes, `ahead`, and every other program the Home's PATH finds
        but `name`."""
        tools = self.home.root / f"without-{name}"
        tools.mkdir()
        fakes, *rest = self.home.env["PATH"].split(os.pathsep)
        # reversed, so the first directory holding a name is the one its link leads to
        found = {program.name: program for directory in reversed(rest)
                 for program in Path(directory).glob("*")}
        found.pop(name, None)
        for program in found.values():
            (tools / program.name).symlink_to(program)
        return os.pathsep.join([fakes, *ahead, str(tools)])

    def assertRefused(self, reason, env=None):
        for launch, args in self.launches.items():
            with self.subTest(launch):
                done = self.home.ak("run", *args, env=env)
                self.assertEqual((done.code, done.out, done.err), (2, "", f"ak run: {reason}\n"))
        for place in ("runs", "jobs"):
            self.assertEqual(list((self.home.path / ".agentkit" / place).glob("*")), [], place)
        self.assertEqual((self.fakes["claude"].n, self.fakes["codex"].n), (0, 0))
        self.assertEqual(self.home.calls("gh"), [])
        self.assertEqual(self.rig.branches(remote=False), ["main"])
        self.assertEqual(self.rig.branches(), ["main"])
        listed = self.rig.git("worktree", "list", "--porcelain").splitlines()
        self.assertEqual([line for line in listed if line.startswith("worktree ")],
                         [f"worktree {self.rig.path}"])

    def test_no_bubblewrap_on_path_is_refused_with_its_install(self):
        self.assertRefused(f"worker box needs bubblewrap; run `{INSTALL}`",
                           {"PATH": self.without("bwrap")})

    def test_a_failing_probe_is_refused_with_its_words_and_the_kernel_s_remedy(self):
        for words, said in ((WORDS, WORDS), ("", "exit 1")):
            with self.subTest(said):
                self.bwrap(f"printf %s {shlex.quote(words)} >&2\nexit 1")
                self.assertRefused(f"worker box cannot start: {said}; run `{remedy()}`; {NESTING}")

    def test_git_only_in_a_relative_path_entry_is_refused(self):
        self.bwrap("exit 0")
        git = shutil.which("git", path=self.home.env["PATH"])
        (self.home.path / "bin").mkdir()
        (self.home.path / "bin" / "git").symlink_to(git)
        # each launch runs in HOME, where `bin` holds that Git
        self.assertRefused("worker box needs git in a directory PATH names in full",
                           {"PATH": self.without("git", "bin")})

    def test_a_credential_folder_closed_to_the_user_is_named_with_the_chmod_opening_it(self):
        self.bwrap("exit 0")
        ssh = self.home.path / ".ssh"
        ssh.mkdir(mode=0)
        self.addCleanup(ssh.chmod, 0o700)
        self.assertRefused(f"{ssh} is closed to you, so the worker box cannot see what it must "
                           f"hide there; run `chmod u+rx {shlex.quote(str(ssh))}`")

    def test_a_probe_silent_past_ten_seconds_admits_the_launch(self):
        self.bwrap("exec sleep 60")
        task = taskfile.write(self.home, "none", "Fix api", done_when=("true",) * 4)
        done = self.home.ak("run", str(task), timeout=300)
        state = json.loads((taskfile.only_run(self.home) / "run.json").read_text())
        self.assertEqual((done.code, state["state"], state["error"]), (2, "error", SPLIT_IT),
                         done.out + done.err)


if __name__ == "__main__":
    unittest.main()
