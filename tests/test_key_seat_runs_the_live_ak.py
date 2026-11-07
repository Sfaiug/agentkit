"""A seat a run reopens runs the live ak, never the version that run is pinned to.

On 5 Nov 2026 a run pinned to its checkout under ~/.agentkit/versions reopened its gone seat,
which ran that checkout's wrapper with its `bin` first on PATH: every `ak` the seat typed after
ran the run's code.  Black-box: the git work tree holding the program `AK_BIN` names is copied,
the program among it, to a version under a Home's ~/.agentkit/versions, the Home's ~/agentkit is
linked to that checkout, and the copy's program reopens a seat tmux lost
(tests/fixtures/akseat.py) as a run pinned there would, on a tmux server such a run started.
The harness is a fake that writes down its environment; what the seat runs is its pane's start
command and the command lines of the processes under its pane.  A path is ~/agentkit's when it
lies under that link or the checkout it names.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, REAL_TMUX, SOCKET, Home
from fixtures.akseat import Seat

VERSION = "3c263bd0a1b2c3d4e5f60718293a4b5c6d7e8f90"
# Its environment written whole, by a rename, and then it waits as a harness does.
HARNESS = """#!{python}
import json, os, signal
path = os.path.join({folder!r}, os.environ["AGENTKIT_SESSION"] + ".json")
with open(path + ".part", "w") as fh:
    json.dump(dict(os.environ), fh)
os.replace(path + ".part", path)
signal.pause()
"""


def checkout():
    """The git work tree the program lies in, and the program's path in it."""
    folder = Path(AK).parent.resolve()
    found = subprocess.run(["git", "-C", str(folder), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=60)
    if found.returncode:
        raise AssertionError(f"{AK} lies in no git work tree: {found.stderr.strip()}")
    top = Path(found.stdout.strip())
    return top, folder.relative_to(top) / Path(AK).name


def commands(pid):
    """Each word of the command lines of the process `pid` and every process under it."""
    children = {}
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            parent = int((entry / "stat").read_bytes().rsplit(b")", 1)[1].split()[1])
        except OSError:     # gone meanwhile
            continue
        children.setdefault(parent, []).append(int(entry.name))
    words, todo = [], [pid]
    while todo:
        pid = todo.pop()
        try:
            words += Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\0")
        except OSError:
            continue
        todo += children.get(pid, [])
    return words


class SeatRunsTheLiveAk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checkout, cls.program = checkout()
        if not REAL_TMUX:
            raise unittest.SkipTest("no tmux installed")
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        own = home.path / ".agentkit"
        cls.versions, cls.live = own / "versions", home.path / "agentkit"
        copy = cls.versions / VERSION
        shutil.copytree(cls.checkout, copy, symlinks=True, ignore=lambda folder, names: [
            name for name in names if name in (".git", "__pycache__")
            or name == "tests" and Path(folder) == cls.checkout])
        cls.live.symlink_to(cls.checkout)
        cls.harnessed = home.root / "harness"
        cls.harnessed.mkdir()
        home.fake("claude", HARNESS.format(python=sys.executable, folder=str(cls.harnessed)))
        for name in ("acme", "beta"):
            Seat(home, name, alive=False)
        # the seats' server, started by a run pinned to the copy: it holds that run's environment
        started = home.run("tmux", "-L", SOCKET, "-f", "/dev/null", "start-server", ";",
                           "set-option", "-s", "exit-empty", "off", env=cls.pinned(copy))
        assert started.code == 0, started.err
        cls.seat = cls.reopen("acme", copy)
        cls.conf = (own / "state" / "tmux.conf").read_text()
        cls.links = {str(path): path.resolve() for path in own.rglob("*")
                     if path.is_symlink() and not path.is_relative_to(cls.versions)}
        # the same copy where a worktree or another clone is, and a run pinned to it there
        cls.moved = home.root / "fix-api"
        copy.rename(cls.moved)
        cls.elsewhere = cls.reopen("beta", cls.moved)

    @classmethod
    def pinned(cls, code):
        """A pinned run's environment: its code named, and its program's folder first on PATH
        twice, as the run and each ak it starts leave it."""
        folder = str(code / cls.program.parent)
        return {"AK_RUN_CODE": str(code),
                "PATH": os.pathsep.join((folder, folder, cls.home.env["PATH"]))}

    @classmethod
    def reopen(cls, name, code):
        """`orch name` by the program in `code`: the words of what the seat runs, and the
        environment its harness started with."""
        done = cls.home.run(str(code / cls.program), "orch", name, env=cls.pinned(code))
        assert done.code == 0, done.err
        written, deadline = cls.harnessed / f"{name}.json", time.monotonic() + 60
        while not written.exists():
            assert time.monotonic() < deadline, f"{name}'s harness never started"
            time.sleep(0.05)
        shown = cls.home.tmux("display-message", "-p", "-t", f"={name}:",
                              "#{pane_pid}\t#{pane_start_command}")
        assert shown.code == 0, shown.err
        pid, start = shown.out.rstrip("\n").split("\t", 1)
        return [start, *commands(int(pid))], json.loads(written.read_text())

    def assertNamesTheLiveOnly(self, words, other):
        self.assertEqual([word for word in words if str(other) in word], [])
        self.assertNotEqual([word for word in words if str(self.live) in word
                             or str(self.checkout) in word], [], words)

    def test_the_seat_runs_the_live_checkouts_wrapper(self):
        self.assertNamesTheLiveOnly(self.seat[0], self.versions)

    def test_its_path_holds_no_version_and_its_environment_no_run_code(self):
        env = self.seat[1]
        self.assertEqual([entry for entry in env["PATH"].split(os.pathsep)
                          if Path(entry).is_relative_to(self.versions)], [])
        self.assertNotIn("AK_RUN_CODE", env)

    def test_a_starter_in_any_other_checkout_names_the_live_one_too(self):
        self.assertNamesTheLiveOnly(self.elsewhere[0], self.moved)

    def test_its_shims_and_its_servers_hooks_are_the_live_checkouts(self):
        self.assertTrue(str(self.live / self.program) in self.conf
                        or str(self.checkout / self.program) in self.conf, self.conf)
        self.assertNotIn(str(self.versions), self.conf)
        self.assertEqual({link: target for link, target in self.links.items()
                          if target.is_relative_to(self.versions)}, {})


if __name__ == "__main__":
    unittest.main()
