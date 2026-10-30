"""The live install of an answer-key Home: the program `AK_BIN` names, as ~/agentkit holds it.

A tick moves agentkit only when it runs from HOME/agentkit, the checkout the cron line runs, so
a test of that copies the program there.  `Install(home)` makes a bare origin,
`<root>/remotes/acme/agentkit.git`, whose main holds the program as its checkout holds it --
every file it tracks but its tests, which no tick runs, and the program itself however it was
built -- with an install.sh that only adds a line to HOME/installed, and a `notes` file;
HOME/agentkit is a clone of it on main, and `install.ak` its `bin/ak`.  Its origin reads as
GitHub's acme/agentkit, `ORIGIN`, so a pull request merged there is on its repository: an `ssh`
serves git's fetch of it from the bare origin, and refuses all else.
`advance()` adds a line to `notes` in one more commit on origin's main.  `seat(name)` opens a
seat of tests/fixtures/akseat.py in HOME/agentkit, at its prompt, holding a run that merged into
acme/agentkit: the seat a tick hands agentkit's own faults back to.  The tick asks the public
model boards over HTTP itself, so every proxy an HTTP client honours names a loopback port nobody
listens on, and npm, which a harness's latest release is read from, is refused like every other
host tool.

    from fixtures.akbin import Home
    from fixtures.akinstall import Install
    with Home() as home:
        install = Install(home)
        tip = install.advance()
        home.run(install.ak, "watch")
"""

import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from .akbin import AK, REFUSE
from .akseat import Seat

PROGRAM = Path(AK).parents[1]
INSTALL = '#!/bin/sh\necho installed >>"$HOME/installed"\n'
ORIGIN = "git@github.com:acme/agentkit.git"
# git fetches over ssh by running its last word on the far end; only ORIGIN's is served.
SSH = """#!/bin/sh
case "$*" in
  *"git@github.com git-upload-pack 'acme/agentkit.git'") exec git-upload-pack {bare} ;;
esac
echo "ssh: not scripted in this test" >&2
exit 1
"""
PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


class Install:
    def __init__(self, home):
        self.home = home
        self.bare = home.root / "remotes" / "acme" / "agentkit.git"
        self.seed, self.path = home.root / "seed", home.path / "agentkit"
        self.ak = str(self.path / "bin" / "ak")
        self.installed = home.path / "installed"
        _offline(home)
        self._git(home.root, "init", "-q", "--bare", "-b", "main", str(self.bare))
        self._git(home.root, "clone", "-q", str(self.bare), str(self.seed))
        for name in _tracked():
            source, copy = PROGRAM / name, self.seed / name
            if source.is_symlink() or source.is_file():
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, copy, follow_symlinks=False)
        (self.seed / "bin").mkdir(exist_ok=True)
        shutil.copy2(AK, self.seed / "bin" / "ak")
        (self.seed / "install.sh").write_text(INSTALL)
        (self.seed / "install.sh").chmod(0o755)
        (self.seed / "notes").write_text("notes\n")
        self._push("the program")
        self._git(home.root, "clone", "-q", str(self.bare), str(self.path))
        self.git("remote", "set-url", "origin", ORIGIN)
        home.fake("ssh", SSH.format(bare=shlex.quote(str(self.bare))))

    def advance(self):
        """One more commit on origin's main; its sha."""
        with (self.seed / "notes").open("a") as notes:
            notes.write("one more line on origin\n")
        return self._push("one more line")

    def seat(self, name="atoll"):
        """A seat in HOME/agentkit that merged a pull request into acme/agentkit."""
        seat = Seat(self.home, name, cwd=self.path)
        now, run = time.time(), f"20261020-1200-agentkit-{name}"
        self.home.write(f".agentkit/runs/{run}/run.json", {
            "run_id": run, "state": "pass", "verdict": "PASS", "merged": True,
            "finished_at": now - 600, "started_at": now - 1200, "repo": str(self.path),
            "pr": "https://github.com/acme/agentkit/pull/1", "launched_session": name})
        return seat

    def git(self, *args):
        """Run git in HOME/agentkit; its output, stripped."""
        return self._git(self.path, *args)

    def head(self):
        """The commit HOME/agentkit has checked out."""
        return self.git("rev-parse", "HEAD")

    def origin(self):
        """The commit origin's main names."""
        return self._git(self.bare, "rev-parse", "main")

    def installs(self):
        """How many times install.sh ran."""
        return len(self.installed.read_text().splitlines()) if self.installed.exists() else 0

    def _push(self, message):
        self._git(self.seed, "add", "-A")
        self._git(self.seed, "commit", "-q", "-m", message)
        self._git(self.seed, "push", "-q", "origin", "HEAD:main")
        return self._git(self.seed, "rev-parse", "HEAD")

    def _git(self, where, *args):
        done = self.home.run("git", "-C", str(where), *args)
        assert done.code == 0, f"git {' '.join(args)}: {done.err}"
        return done.out.strip()


def _tracked():
    """The files the program's checkout tracks, its tests aside; none where it is no checkout."""
    listed = subprocess.run(["git", "-C", str(PROGRAM), "ls-files", "-z"], capture_output=True,
                            text=True, timeout=60)
    return [name for name in listed.stdout.split("\0")
            if name and not name.startswith("tests/")] if listed.returncode == 0 else []


def _offline(home):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{port}"))
    home.fake("npm", REFUSE.format(python=shlex.quote(sys.executable), name="npm",
                                   log=shlex.quote(str(home.log("npm")))))
