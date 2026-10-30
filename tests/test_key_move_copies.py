"""`ak move ALIAS` copies this home to the same path on the machine `ssh ALIAS` reaches, and a
repeat pass sends only what changed and deletes there what was deleted here.

Left out, so neither sent nor deleted there: ak's tmp folder, `~/.ssh/authorized_keys` and the
browser profile's `Singleton*` locks.  Sockets and pipes are not sent, a file that vanishes during
a pass is no failure, and nothing here changes.  It refuses, changing nothing anywhere, a machine
that is this one, one whose home is another path, and one where ak's tick is installed.

The other machine is this one through a fake ssh: bubblewrap puts another directory at this
home's path and another /etc/machine-id there, and that machine's own `crontab` and `rsync` first
on its PATH.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import SYSTEM, Home, boxable

RSYNC = shutil.which("rsync", path=os.pathsep.join(SYSTEM))
TICK = "*/3 * * * * ~/agentkit/bin/ak watch >>~/.agentkit/tmp/watch.log 2>&1 # agentkit watch"
# `ssh [OPTIONS] ALIAS COMMAND`: `self` is this machine, any other alias another one with this
# home's path, but for `elsewhere`, whose home is another path.  `ticking` has ak's tick in its
# crontab, and `mini` a tick paused by hand.
SSH = """#!{python}
import os, sys
args = sys.argv[1:]
while args[0].startswith("-"):
    flag = args.pop(0)
    if len(flag) == 2 and flag[1] in "BbcDEeFIiJLlmOoPpQRSWw":   # its value is the next word
        args.pop(0)
alias, command = args[0], " ".join(args[1:])
if alias == "self":
    os.execv("/bin/sh", ["sh", "-c", command])
home = os.environ["HOME"]
box = ["bwrap", "--dev-bind", "/", "/", "--bind", home, {here!r},
       "--ro-bind", {machine!r}, "/etc/machine-id",
       "--setenv", "PATH", {bin!r} + ":" + os.environ["PATH"],
       "--setenv", "CRONTAB", {{"ticking": {tick!r}, "mini": "# " + {tick!r}}}.get(alias, "")]
box += ["--setenv", "HOME", {there!r}] if alias == "elsewhere" else ["--bind", {there!r}, home]
os.execvp("bwrap", [*box, "--", "sh", "-c", command])
"""
CRONTAB = """#!/bin/sh
[ -n "$CRONTAB" ] || { echo "no crontab for $USER" >&2; exit 1; }
printf '%s\\n' "$CRONTAB"
"""
# The rsync there, which takes vanish.txt away here as a.bin starts arriving: listed, not yet read.
REMOTE_RSYNC = """#!{python}
import glob, os, subprocess, sys, threading
server = subprocess.Popen([{rsync!r}, *sys.argv[1:]], stdin=subprocess.PIPE)
def forward():
    while chunk := os.read(0, 65536):
        if glob.glob(os.environ["HOME"] + "/.a.bin.*") and os.path.exists({gone!r}):
            os.unlink({gone!r})
        server.stdin.write(chunk)
        server.stdin.flush()
threading.Thread(target=forward, daemon=True).start()
sys.exit(server.wait())     # the client keeps its end open till this ends
"""
LEFT_OUT = (".agentkit/tmp", ".ssh/authorized_keys", ".local/share/browser-bridge/profile/Singleton")
PROFILE = ".local/share/browser-bridge/profile"


def put(root, files):
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def tree(root):
    """Each entry under `root`: a file's bytes, a link's target or another kind, and its mode."""
    entries = {}
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        entries[str(path.relative_to(root))] = (
            path.read_bytes() if stat.S_ISREG(mode) else
            os.readlink(path) if stat.S_ISLNK(mode) else stat.S_IFMT(mode), stat.S_IMODE(mode))
    return entries


def left_out(name):
    return name.startswith(LEFT_OUT)


@unittest.skipUnless(RSYNC and boxable(), "no rsync, or no bwrap able to box another machine here")
class Move(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        root = self.home.root
        self.here, self.there = self.home.path, root / "there"
        for directory in (self.there, root / "here", root / "remote"):
            directory.mkdir()
        (root / "machine-id").write_text("0123456789abcdef0123456789abcdef\n")
        python = sys.executable
        self.home.fake("ssh", SSH.format(python=python, here=str(root / "here"), there=str(self.there),
                                         machine=str(root / "machine-id"), bin=str(root / "remote"),
                                         tick=TICK))
        for name, script in (("crontab", CRONTAB),
                             ("rsync", REMOTE_RSYNC.format(python=python, rsync=RSYNC,
                                                           gone=str(root / "here/vanish.txt")))):
            (root / "remote" / name).write_text(script)
            (root / "remote" / name).chmod(0o755)

    def mirror(self, kept):
        """There, as a pass should leave it: here's entries but sockets, pipes and the left out,
        which stay there as `kept`."""
        return {**{name: entry for name, entry in tree(self.here).items()
                   if not left_out(name) and name not in ("pipe", "sock")}, **kept}

    def test_a_pass_mirrors_this_home_there_and_a_repeat_sends_only_what_changed(self):
        here, there = self.here, self.there
        put(here, {"notes.md": b"plans\n", "a.bin": bytes(1 << 23), "vanish.txt": b"soon gone\n",
                   "code/acme/run.sh": b"#!/bin/sh\n", ".ssh/id_ed25519": b"key\n",
                   ".agentkit/tmp/scratch": b"here's\n", ".ssh/authorized_keys": b"ssh-ed25519 HERE\n",
                   f"{PROFILE}/Default/Cookies": b"logins\n"})
        (here / "code/acme/run.sh").chmod(0o755)
        (here / "code/run").symlink_to("acme/run.sh")
        for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            (here / PROFILE / lock).symlink_to(f"vm-{lock}")
        os.mkfifo(here / "pipe")
        subprocess.run([sys.executable, "-c", "import socket; socket.socket(socket.AF_UNIX).bind('sock')"],
                       cwd=here, check=True)
        put(there, {"stale.txt": b"old\n", ".agentkit/tmp/theirs": b"there's\n",
                    ".ssh/authorized_keys": b"ssh-ed25519 THERE\n"})
        (there / PROFILE).mkdir(parents=True)
        (there / PROFILE / "SingletonLock").symlink_to("mini-1")
        kept = {name: entry for name, entry in tree(there).items() if left_out(name)}
        before = tree(here)

        done = self.home.ak("move", "mini")
        self.assertEqual(done.code, 0, done.err)
        del before["vanish.txt"]      # gone as a.bin went, after the pass listed it
        self.assertEqual(tree(here), before)
        self.assertEqual(tree(there), self.mirror(kept))

        # One file changed here, one deleted, one new.  A key altered there alone, its size and
        # time kept, stays as it is: a file that did not change here is not sent again.
        (here / "notes.md").write_bytes(b"plans, revised\n")
        (here / "code/acme/run.sh").unlink()
        (here / "code/acme/new.py").write_bytes(b"print()\n")
        key = there / ".ssh/id_ed25519"
        times = key.stat()
        key.write_bytes(b"KEY\n")
        os.utime(key, ns=(times.st_atime_ns, times.st_mtime_ns))
        done = self.home.ak("move", "mini")
        self.assertEqual(done.code, 0, done.err)
        want = self.mirror(kept)
        want[".ssh/id_ed25519"] = (b"KEY\n", want[".ssh/id_ed25519"][1])
        self.assertEqual(tree(there), want)

    def test_a_refusal_changes_nothing_anywhere(self):
        put(self.here, {"notes.md": b"plans\n"})
        put(self.there, {"stale.txt": b"old\n"})
        before = tree(self.here), tree(self.there)
        for alias in ("self", "elsewhere", "ticking"):
            with self.subTest(alias):
                done = self.home.ak("move", alias)
                self.assertNotEqual(done.code, 0, done.out)
                self.assertIn(alias, done.err)
                self.assertEqual((tree(self.here), tree(self.there)), before)


if __name__ == "__main__":
    unittest.main()
