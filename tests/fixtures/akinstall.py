"""The live install of an answer-key Home: the program `AK_BIN` names, as ~/agentkit holds it.

A tick moves agentkit only when it runs from HOME/agentkit, the checkout the cron line runs, so
a test of that copies the program there.  `make(root)` makes a bare origin,
`<root>/remotes/acme/agentkit.git`, whose main holds the program as its checkout holds it --
every file it tracks but its tests, which no tick runs, and the program itself however it was
built -- with an install.sh that only adds a line to HOME/installed, and nothing at `--prepare`,
and a `notes` file, and `<root>/seed` pushing to it.  `Install(home)` makes one in the home's
root, or takes the `origin` homes share (tests/fixtures/twohomes.py); HOME/agentkit is a clone
of it on main, and `install.ak` its `bin/ak` as the home's commands find it.  Its origin reads
as GitHub's acme/agentkit, `ORIGIN`, so a pull request merged there is on its repository: an
`ssh` serves git's fetch of it, `FETCH`, from the bare origin, and refuses all else.
`advance()` adds a line to `notes` in one more commit on origin's main.  `refs()` are the refs
origin holds under refs/agentkit/, `commit(sha)` one as it holds it, and `set_ref` changes one,
or deletes it, as a stranger would, from no machine.  `seat(name)` opens a
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

import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from .akbin import AK, REFUSE, SYSTEM
from .akseat import Seat

# Go's bin/ak is nested under go/: keep the checkout's ignore rules at their own paths.
PROGRAM = next((folder for folder in Path(AK).resolve().parents if (folder / ".git").exists()),
               Path(AK).parents[1])
INSTALL = '#!/bin/sh\n[ "$1" != --prepare ] || exit 0\necho installed >>"$HOME/installed"\n'
ORIGIN = "git@github.com:acme/agentkit.git"
# git fetches, and pushes, over ssh by running its last word on the far end, where the
# repositories are; only ORIGIN's is served.
FETCH, PUSH = (("git@github.com", f"{program} 'acme/agentkit.git'")
               for program in ("git-upload-pack", "git-receive-pack"))
SSH = f"""#!/bin/sh
case "$*" in
  *"{' '.join(FETCH)}") exec git-upload-pack {{bare}} ;;
esac
echo "ssh: not scripted in this test" >&2
exit 1
"""
PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
BARE = Path("remotes", "acme", "agentkit.git")


def _git(where, *args):
    """Run git in `where` on the test's side, as no home's command, for an origin is no home's;
    its output, stripped."""
    done = subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True,
                          timeout=120, env={
                              "PATH": os.pathsep.join(SYSTEM), "GIT_CONFIG_NOSYSTEM": "1",
                              "GIT_CONFIG_GLOBAL": os.devnull,
                              "GIT_CEILING_DIRECTORIES": str(Path(where).parent),
                              "GIT_AUTHOR_NAME": "acme", "GIT_AUTHOR_EMAIL": "acme@example.com",
                              "GIT_COMMITTER_NAME": "acme",
                              "GIT_COMMITTER_EMAIL": "acme@example.com"})
    assert done.returncode == 0, f"git {' '.join(args)}: {done.stderr}"
    return done.stdout.strip()


def _push(seed, message):
    """Commit all of `seed` and push it to origin's main; its sha."""
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", message)
    _git(seed, "push", "-q", "origin", "HEAD:main")
    return _git(seed, "rev-parse", "HEAD")


def make(root):
    """The bare origin and its seed, made in `root`; `root`."""
    bare, seed = root / BARE, root / "seed"
    _git(root, "init", "-q", "--bare", "-b", "main", str(bare))
    _git(root, "clone", "-q", str(bare), str(seed))
    copy_tracked(seed)
    (seed / "bin").mkdir(exist_ok=True)
    shutil.copy2(AK, seed / "bin" / "ak")
    (seed / "install.sh").write_text(INSTALL)
    (seed / "install.sh").chmod(0o755)
    (seed / "notes").write_text("notes\n")
    _push(seed, "the program")
    return root


class Install:
    def __init__(self, home, origin=None):
        self.home = home
        origin = origin or make(home.root)
        self.bare, self.seed = origin / BARE, origin / "seed"
        self.path = home.path / "agentkit"
        self.at = Path(home.env["HOME"], "agentkit")     # where the home's commands find it
        self.ak = str(self.at / "bin" / "ak")
        self.installed = home.path / "installed"
        _offline(home)
        _git(home.root, "clone", "-q", str(self.bare), str(self.path))
        self.git("remote", "set-url", "origin", ORIGIN)
        linked = home.path / ".local" / "bin" / "ak"
        linked.parent.mkdir(parents=True, exist_ok=True)
        linked.symlink_to(self.ak)
        home.fake("ssh", SSH.format(bare=shlex.quote(str(self.bare))))

    def advance(self):
        """One more commit on origin's main; its sha."""
        with (self.seed / "notes").open("a") as notes:
            notes.write("one more line on origin\n")
        return self._push("one more line")

    def refs(self):
        """Each ref origin holds under refs/agentkit/, and the commit it names."""
        listed = _git(self.bare, "for-each-ref", "--format=%(refname) %(objectname)",
                      "refs/agentkit/")
        return dict(line.split() for line in listed.splitlines())

    def commit(self, sha):
        """The commit `sha` as origin holds it."""
        return _git(self.bare, "cat-file", "commit", sha)

    def set_ref(self, ref, value):
        """Have origin's `ref` name `value`, a commit it holds; None deletes it."""
        _git(self.bare, "update-ref", *(("-d", ref) if value is None else (ref, value)))

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
        """Run git in HOME/agentkit, on the home; its output, stripped."""
        done = self.home.run("git", "-C", str(self.at), *args)
        assert done.code == 0, f"git {' '.join(args)}: {done.err}"
        return done.out.strip()

    def head(self):
        """The commit HOME/agentkit has checked out."""
        return self.git("rev-parse", "HEAD")

    def origin(self):
        """The commit origin's main names."""
        return _git(self.bare, "rev-parse", "main")

    def installs(self):
        """How many times install.sh ran."""
        return len(self.installed.read_text().splitlines()) if self.installed.exists() else 0

    def _push(self, message):
        return _push(self.seed, message)

    _git = staticmethod(_git)


def copy_tracked(to):
    """Copy to `to` each file the program's checkout tracks, its tests aside."""
    for name in _tracked():
        source, copy = PROGRAM / name, to / name
        if source.is_symlink() or source.is_file():
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copy, follow_symlinks=False)


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
    log = home.at / home.log("npm").relative_to(home.root)     # where its commands find it
    home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{port}"))
    home.fake("npm", REFUSE.format(python=shlex.quote(sys.executable), name="npm",
                                   log=shlex.quote(str(log))))
