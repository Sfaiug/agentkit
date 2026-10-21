"""The live install of an answer-key Home: the program `AK_BIN` names, as ~/agentkit holds it.

A tick moves agentkit only when it runs from HOME/agentkit, the checkout the cron line runs, so
a test of that copies the program there.  `Install(home)` makes a bare origin,
`<root>/remotes/acme/agentkit.git`, whose main holds the program as its checkout holds it --
every file it tracks but its tests, which no tick runs, and the program itself however it was
built -- with an install.sh that only adds a line to HOME/installed, and a `notes` file;
HOME/agentkit is a clone of it on main, and `install.ak` its `bin/ak`.  `advance()` adds a line
to `notes` in one more commit on origin's main.  The tick asks the public model boards over HTTP
itself, so every proxy an HTTP client honours names a loopback port nobody listens on, and npm,
which a harness's latest release is read from, is refused like every other host tool.

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
from pathlib import Path

from .akbin import AK, REFUSE

PROGRAM = Path(AK).parents[1]
INSTALL = '#!/bin/sh\necho installed >>"$HOME/installed"\n'
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

    def advance(self):
        """One more commit on origin's main; its sha."""
        with (self.seed / "notes").open("a") as notes:
            notes.write("one more line on origin\n")
        return self._push("one more line")

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
